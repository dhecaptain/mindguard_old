"""Small, centralized commercial lifecycle and entitlement layer for workplaces."""

import json
import os
import uuid
from datetime import date, datetime, timedelta, timezone

from backend.services.crypto import decrypt_pii, encrypt_pii

STATUS_VALUES = {"PILOT", "TRIAL", "ACTIVE", "GRACE_PERIOD", "SUSPENDED", "CANCELLED", "TERMINATED"}
POPULATION_BANDS = {"1-50", "51-200", "201-500", "501-1000", "1000+", "not_recorded"}
CAPABILITIES = {"enrollment", "aggregate_analytics", "provider_services", "administrator_management", "voice_support"}
DEFAULT_GRACE_PERIOD_DAYS = 30


def grace_period_days() -> int:
    try:
        configured = int(os.getenv("WORKPLACE_COMMERCIAL_GRACE_DAYS", DEFAULT_GRACE_PERIOD_DAYS))
    except (TypeError, ValueError):
        configured = DEFAULT_GRACE_PERIOD_DAYS
    return min(365, max(1, configured))

PLANS = {
    "legacy_pilot": {"name": "Legacy pilot", "capabilities": {"enrollment": True, "aggregate_analytics": True, "provider_services": True, "administrator_management": True, "voice_support": False}, "administrator_limit": None, "provider_limit": None},
    "pilot": {"name": "Workplace pilot", "capabilities": {"enrollment": True, "aggregate_analytics": True, "provider_services": True, "administrator_management": True, "voice_support": False}, "administrator_limit": 3, "provider_limit": 2},
    "trial": {"name": "Workplace trial", "capabilities": {"enrollment": True, "aggregate_analytics": True, "provider_services": True, "administrator_management": True, "voice_support": False}, "administrator_limit": 3, "provider_limit": 2},
    "team": {"name": "Workplace team", "capabilities": {"enrollment": True, "aggregate_analytics": True, "provider_services": True, "administrator_management": True, "voice_support": False}, "administrator_limit": 5, "provider_limit": 5},
    "enterprise": {"name": "Workplace enterprise", "capabilities": {"enrollment": True, "aggregate_analytics": True, "provider_services": True, "administrator_management": True, "voice_support": False}, "administrator_limit": None, "provider_limit": None},
}

TRANSITIONS = {
    "PILOT": {"ACTIVE", "GRACE_PERIOD", "CANCELLED", "SUSPENDED"},
    "TRIAL": {"ACTIVE", "GRACE_PERIOD", "CANCELLED", "SUSPENDED"},
    "ACTIVE": {"GRACE_PERIOD", "SUSPENDED", "CANCELLED"},
    "GRACE_PERIOD": {"ACTIVE", "SUSPENDED", "CANCELLED"},
    "SUSPENDED": {"ACTIVE", "CANCELLED"},
    "CANCELLED": {"ACTIVE", "TERMINATED"},
    "TERMINATED": set(),
}


def _today() -> date:
    return datetime.now(timezone.utc).date()


def population_band_from_range(value: str | None) -> str:
    """Map the old free-text estimate to a coarse contract band, never a roster count."""
    if not value:
        return "not_recorded"
    normalized = str(value).strip().lower().replace(",", "")
    if "1000" in normalized or "1001" in normalized or "more" in normalized or "+" in normalized:
        return "1000+"
    import re
    bounds = [int(part) for part in re.findall(r"\d+", normalized)]
    if not bounds:
        return "not_recorded"
    upper = max(bounds)
    if upper <= 50:
        return "1-50"
    if upper <= 200:
        return "51-200"
    if upper <= 500:
        return "201-500"
    if upper <= 1000:
        return "501-1000"
    return "1000+"


def ensure_account(conn, company_id: str, *, population_range: str | None = None, starts_on: str | None = None, plan_key: str = "legacy_pilot") -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT OR IGNORE INTO workplace_commercial_accounts "
        "(company_id,status,plan_key,contract_start_date,population_band,created_at,updated_at) "
        "VALUES (?,'PILOT',?,?,?,?,?)",
        (company_id, plan_key, starts_on or now[:10], population_band_from_range(population_range), now, now),
    )


def _record_event(conn, company_id: str, actor_id: str | None, event_type: str, old_status: str | None, new_status: str | None, reason: str | None = None, reference: str | None = None, at: str | None = None) -> None:
    occurred_at = at or datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO workplace_commercial_events (id,company_id,actor_user_id,event_type,previous_status,new_status,reason_encrypted,reference_encrypted,occurred_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (str(uuid.uuid4()), company_id, actor_id, event_type, old_status, new_status, encrypt_pii(reason) if reason else None, encrypt_pii(reference) if reference else None, occurred_at),
    )
    conn.execute(
        "INSERT INTO workplace_audit_events (id,company_id,actor_user_id,event_type,occurred_at) VALUES (?,?,?,?,?)",
        (str(uuid.uuid4()), company_id, actor_id, f"WORKPLACE_COMMERCIAL_{event_type}", occurred_at),
    )


record_event = _record_event


def transition(conn, company_id: str, new_status: str, *, actor_id: str | None, reason: str | None = None, reference: str | None = None, occurred_at: str | None = None) -> tuple[str, str]:
    row = conn.execute("SELECT status FROM workplace_commercial_accounts WHERE company_id=?", (company_id,)).fetchone()
    if not row:
        raise ValueError("Commercial account not found")
    old_status = str(row["status"]).upper()
    new_status = str(new_status).upper()
    if new_status not in STATUS_VALUES:
        raise ValueError("Unknown workplace commercial status")
    if new_status not in TRANSITIONS.get(old_status, set()):
        raise ValueError(f"Invalid commercial transition: {old_status} to {new_status}")
    now = occurred_at or datetime.now(timezone.utc).isoformat()
    terminated = now if new_status == "TERMINATED" else None
    conn.execute(
        "UPDATE workplace_commercial_accounts SET status=?,terminated_at=COALESCE(?,terminated_at),updated_at=? WHERE company_id=?",
        (new_status, terminated, now, company_id),
    )
    transition_events = {
        ("PILOT", "ACTIVE"): "CONTRACT_ACTIVATED",
        ("TRIAL", "ACTIVE"): "CONTRACT_ACTIVATED",
        ("GRACE_PERIOD", "ACTIVE"): "GRACE_PERIOD_EXITED",
        ("SUSPENDED", "ACTIVE"): "REACTIVATED",
        ("CANCELLED", "ACTIVE"): "CANCELLATION_REVERSED",
        ("ACTIVE", "CANCELLED"): "CANCELLATION_SCHEDULED",
        ("GRACE_PERIOD", "SUSPENDED"): "COMMERCIALLY_SUSPENDED",
        (old_status, "SUSPENDED"): "COMMERCIALLY_SUSPENDED",
        ("CANCELLED", "TERMINATED"): "TERMINATED",
    }
    event_type = transition_events.get((old_status, new_status), "GRACE_PERIOD_ENTERED" if new_status == "GRACE_PERIOD" else f"STATUS_{new_status}")
    _record_event(conn, company_id, actor_id, event_type, old_status, new_status, reason, reference, now)
    return old_status, new_status


def resolve_account(conn, company_id: str, *, at: date | None = None) -> dict | None:
    """Apply date-driven expiry/grace/cancellation transitions and return current state."""
    row = conn.execute("SELECT * FROM workplace_commercial_accounts WHERE company_id=?", (company_id,)).fetchone()
    if not row:
        ensure_account(conn, company_id)
        row = conn.execute("SELECT * FROM workplace_commercial_accounts WHERE company_id=?", (company_id,)).fetchone()
    if not row:
        return None
    today = at or _today()
    status = str(row["status"]).upper()
    end_value = row["contract_end_date"]
    end_date = date.fromisoformat(end_value[:10]) if end_value else None
    if status in {"PILOT", "TRIAL", "ACTIVE"} and end_date and end_date < today:
        grace_end = end_date + timedelta(days=grace_period_days())
        transition(conn, company_id, "GRACE_PERIOD", actor_id=None, reason="Contract period ended; grace period started", occurred_at=datetime.combine(today, datetime.min.time(), timezone.utc).isoformat())
        conn.execute("UPDATE workplace_commercial_accounts SET grace_period_end=?,updated_at=? WHERE company_id=?", (grace_end.isoformat(), datetime.now(timezone.utc).isoformat(), company_id))
        status = "GRACE_PERIOD"
        row = conn.execute("SELECT * FROM workplace_commercial_accounts WHERE company_id=?", (company_id,)).fetchone()
    if status == "GRACE_PERIOD" and row["grace_period_end"] and date.fromisoformat(row["grace_period_end"][:10]) < today:
        transition(conn, company_id, "SUSPENDED", actor_id=None, reason="Grace period ended without renewal", occurred_at=datetime.combine(today, datetime.min.time(), timezone.utc).isoformat())
        row = conn.execute("SELECT * FROM workplace_commercial_accounts WHERE company_id=?", (company_id,)).fetchone()
        status = "SUSPENDED"
    cancel_value = row["cancellation_effective_date"]
    if status == "CANCELLED" and cancel_value and date.fromisoformat(cancel_value[:10]) <= today:
        transition(conn, company_id, "TERMINATED", actor_id=None, reason="Scheduled cancellation effective date reached", occurred_at=datetime.combine(today, datetime.min.time(), timezone.utc).isoformat())
        row = conn.execute("SELECT * FROM workplace_commercial_accounts WHERE company_id=?", (company_id,)).fetchone()
    return dict(row)


def entitlements(account: dict) -> dict:
    plan = PLANS.get(str(account.get("plan_key") or "legacy_pilot"), PLANS["legacy_pilot"])
    result = {**plan["capabilities"]}
    try:
        overrides = json.loads(account.get("capabilities_json") or "{}")
    except (TypeError, ValueError):
        overrides = {}
    if isinstance(overrides, dict):
        for key in CAPABILITIES - {"voice_support"}:
            if isinstance(overrides.get(key), bool):
                result[key] = overrides[key]
    # Voice remains independently launch-gated and is never enabled by contract configuration.
    result["voice_support"] = False
    return result


def can_use(conn, company_id: str, capability: str) -> bool:
    if capability not in CAPABILITIES:
        return False
    account = resolve_account(conn, company_id)
    # Operational offboarding is synchronized on the request path as well as
    # maintenance, so expiry of old links never depends on a cleanup job.
    from backend.services.workplace_lifecycle import sync_offboarding, termination_effective
    sync_offboarding(conn, company_id)
    if termination_effective(conn, company_id):
        return False
    if not account or not entitlements(account).get(capability, False):
        return False
    status = str(account["status"]).upper()
    if status in {"SUSPENDED", "TERMINATED"}:
        return False
    start = account.get("contract_start_date")
    if status in {"PILOT", "TRIAL", "ACTIVE"} and start and date.fromisoformat(start[:10]) > _today():
        return False
    if status == "CANCELLED":
        effective = account.get("cancellation_effective_date")
        if effective and date.fromisoformat(effective[:10]) <= _today():
            return False
    return True


def plan_limit(account: dict, limit_name: str) -> int | None:
    return PLANS.get(str(account.get("plan_key") or "legacy_pilot"), PLANS["legacy_pilot"]).get(limit_name)


def _pilot_state(account: dict, today: date) -> str | None:
    if str(account.get("status") or "").upper() != "PILOT":
        return None
    start = date.fromisoformat(account["contract_start_date"][:10]) if account.get("contract_start_date") else None
    end = date.fromisoformat(account["contract_end_date"][:10]) if account.get("contract_end_date") else None
    if start and start > today:
        return "UPCOMING"
    if end and end < today:
        return "ENDED"
    if end and (end - today).days <= 30:
        return "ENDING_SOON"
    return "ACTIVE"


def summary(conn, company_id: str, *, internal: bool = False) -> dict | None:
    account = resolve_account(conn, company_id)
    if not account:
        return None
    today = _today()
    plan = PLANS.get(account["plan_key"], PLANS["legacy_pilot"])
    renewal = date.fromisoformat(account["renewal_date"][:10]) if account.get("renewal_date") else None
    status = str(account["status"]).upper()
    action_required = status in {"GRACE_PERIOD", "SUSPENDED", "CANCELLED"} or bool(renewal and (renewal - today).days <= 30)
    result = {
        "status": status,
        "plan_key": account["plan_key"],
        "plan_name": plan["name"],
        "pilot_state": _pilot_state(account, today),
        "contract_start_date": account["contract_start_date"],
        "contract_end_date": account["contract_end_date"],
        "billing_cycle": account["billing_cycle"],
        "population_band": account["population_band"],
        "renewal_date": account["renewal_date"],
        "grace_period_end": account["grace_period_end"],
        "cancellation_effective_date": account["cancellation_effective_date"],
        "terminated_at": account["terminated_at"],
        "renewal_state": "overdue" if renewal and renewal < today else "due_soon" if renewal and (renewal - today).days <= 30 else "current" if renewal else None,
        "action_required": action_required,
        "enabled_capabilities": entitlements(account),
    }
    if internal:
        result.update({
            "internal_reference": decrypt_pii(account["internal_reference_encrypted"]) if account.get("internal_reference_encrypted") else None,
            "internal_notes": decrypt_pii(account["internal_notes_encrypted"]) if account.get("internal_notes_encrypted") else None,
            "cancellation_reason": decrypt_pii(account["cancellation_reason_encrypted"]) if account.get("cancellation_reason_encrypted") else None,
            "external_customer_reference": account["external_customer_reference"],
            "external_subscription_reference": account["external_subscription_reference"],
            "billing_provider": account["billing_provider"],
            "administrator_limit": plan["administrator_limit"],
            "provider_limit": plan["provider_limit"],
        })
    return result
