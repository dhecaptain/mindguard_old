"""Workplace offboarding and retention decisions.

Commercial termination is a soft lifecycle transition. Never delete an
institution or a MindGuard user as part of this service.
"""

import os
import uuid
from datetime import date, datetime, timedelta, timezone

from backend.services.crypto import encrypt_pii

ACTIVE_CASE_STATES = ("open", "active")
RETENTION_RECORD_TYPES = {
    "checkin": "DELETE",
    "closed_case": "DELETE",
    "case_message": "DELETE_WITH_CASE",
    "provider_note": "DELETE_WITH_CASE",
    "appointment": "DELETE_WITH_CASE",
    # Membership keeps a user FK today; do not claim anonymization until the
    # company-approved retention policy and safe redaction model are reviewed.
    "membership": "RETAIN",
    "company_configuration": "RETAIN",
    "provider_association": "RETAIN",
    "audit_event": "RETAIN",
    "aggregate_snapshot": "RETAIN",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def continuity_days() -> int:
    """Operational case-continuity window; legal retention remains company-configured."""
    try:
        value = int(os.getenv("WORKPLACE_OFFBOARDING_CONTINUITY_DAYS", "30"))
    except (TypeError, ValueError):
        value = 30
    return min(180, max(1, value))


def retention_decision(record_type: str, created_at: str | None, retention_days: int,
                       *, active_dependency: bool = False, now: datetime | None = None) -> str:
    """Return RETAIN/ANONYMIZE/DELETE based on configured retention and dependencies."""
    action = RETENTION_RECORD_TYPES.get(record_type, "RETAIN")
    if active_dependency or not created_at or action in {"RETAIN", "DELETE_WITH_CASE"}:
        return "RETAIN"
    try:
        cutoff = (now or _now()) - timedelta(days=max(1, int(retention_days or 365)))
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return "RETAIN"
    return action if created <= cutoff else "RETAIN"


def _event(conn, company_id: str, event: str, *, actor_id: str | None = None, at: str | None = None) -> None:
    conn.execute(
        "INSERT INTO workplace_audit_events (id,company_id,actor_user_id,event_type,occurred_at) VALUES (?,?,?,?,?)",
        (str(uuid.uuid4()), company_id, actor_id, event, at or _now().isoformat()),
    )


def schedule_offboarding(conn, company_id: str, effective_date: str, *, actor_id: str | None,
                         reason: str | None = None, reference: str | None = None,
                         now: datetime | None = None) -> dict:
    """Create/update a scheduled workflow without ending service early."""
    instant = now or _now()
    timestamp = instant.isoformat()
    existing = conn.execute("SELECT status,effective_date FROM workplace_offboarding WHERE company_id=?", (company_id,)).fetchone()
    if existing and existing["status"] in {"IN_PROGRESS", "RETENTION_PERIOD", "COMPLETED"}:
        return dict(conn.execute("SELECT * FROM workplace_offboarding WHERE company_id=?", (company_id,)).fetchone())
    conn.execute(
        "INSERT INTO workplace_offboarding (company_id,status,effective_date,initiated_by,initiated_at,reason_encrypted,reference_encrypted,updated_at) "
        "VALUES (?,'SCHEDULED',?,?,?,?,?,?) ON CONFLICT(company_id) DO UPDATE SET status='SCHEDULED',effective_date=excluded.effective_date,initiated_by=excluded.initiated_by,initiated_at=excluded.initiated_at,reason_encrypted=excluded.reason_encrypted,reference_encrypted=excluded.reference_encrypted,updated_at=excluded.updated_at",
        (company_id, effective_date, actor_id, timestamp, encrypt_pii(reason) if reason else None,
         encrypt_pii(reference) if reference else None, timestamp),
    )
    _event(conn, company_id, "WORKPLACE_OFFBOARDING_SCHEDULED", actor_id=actor_id, at=timestamp)
    return dict(conn.execute("SELECT * FROM workplace_offboarding WHERE company_id=?", (company_id,)).fetchone())


def sync_offboarding(conn, company_id: str, *, actor_id: str | None = None,
                     now: datetime | None = None) -> dict | None:
    """Synchronize commercial cancellation/termination into operational gates."""
    instant = now or _now()
    stamp = instant.isoformat()
    commercial = conn.execute("SELECT status,cancellation_effective_date FROM workplace_commercial_accounts WHERE company_id=?", (company_id,)).fetchone()
    if not commercial:
        return None
    status = str(commercial["status"] or "").upper()
    effective = commercial["cancellation_effective_date"]
    current = conn.execute("SELECT * FROM workplace_offboarding WHERE company_id=?", (company_id,)).fetchone()
    if status == "CANCELLED" and effective:
        current = schedule_offboarding(conn, company_id, effective[:10], actor_id=actor_id,
                                       now=instant) if not current or current["status"] == "NOT_STARTED" else dict(current)
    if status == "TERMINATED" and (not current or current["status"] in {"NOT_STARTED", "SCHEDULED"}):
        termination_date = (effective or stamp)[:10]
        settings = conn.execute("SELECT retention_days FROM workplace_settings WHERE company_id=?", (company_id,)).fetchone()
        keep_days = max(1, int(settings["retention_days"] or 365)) if settings else 365
        deadline = (instant + timedelta(days=keep_days)).isoformat()
        continuity_end = instant + timedelta(days=continuity_days())
        conn.execute(
            "INSERT INTO workplace_offboarding (company_id,status,effective_date,initiated_by,initiated_at,reason_encrypted,continuity_deadline,retention_deadline,updated_at) "
            "VALUES (?,'IN_PROGRESS',?,?,?,NULL,?,?,?) ON CONFLICT(company_id) DO UPDATE SET status='IN_PROGRESS',effective_date=excluded.effective_date,initiated_at=COALESCE(workplace_offboarding.initiated_at,excluded.initiated_at),continuity_deadline=excluded.continuity_deadline,retention_deadline=excluded.retention_deadline,updated_at=excluded.updated_at",
            (company_id, termination_date, actor_id, stamp, continuity_end.isoformat(), deadline, stamp),
        )
        conn.execute("UPDATE workplace_enrollment_links SET revoked_at=COALESCE(revoked_at,?) WHERE company_id=?", (stamp, company_id))
        conn.execute("UPDATE workplace_providers SET status='ending' WHERE company_id=? AND status='active'", (company_id,))
        conn.execute("UPDATE workplace_support_cases SET continuity_until=COALESCE(continuity_until,?) WHERE company_id=? AND status IN ('open','active') AND withdrawn_at IS NULL", (continuity_end.isoformat(), company_id))
        _event(conn, company_id, "WORKPLACE_OFFBOARDING_STARTED", actor_id=actor_id, at=stamp)
        _event(conn, company_id, "WORKPLACE_ENROLLMENT_DISABLED", actor_id=actor_id, at=stamp)
        _event(conn, company_id, "WORKPLACE_CONTINUITY_PERIOD_STARTED", actor_id=actor_id, at=stamp)
        current = conn.execute("SELECT * FROM workplace_offboarding WHERE company_id=?", (company_id,)).fetchone()
    if not current:
        return None
    if current["status"] == "IN_PROGRESS" and current["continuity_deadline"] and current["continuity_deadline"] <= stamp:
        active_cases = conn.execute("SELECT id FROM workplace_support_cases WHERE company_id=? AND status IN ('open','active') AND withdrawn_at IS NULL", (company_id,)).fetchall()
        for case in active_cases:
            conn.execute("UPDATE workplace_support_cases SET status='closed',closed_at=?,closed_by=NULL,updated_at=? WHERE id=?", (stamp, stamp, case["id"]))
        conn.execute("UPDATE workplace_providers SET status='ended',ended_at=COALESCE(ended_at,?) WHERE company_id=? AND status='ending'", (stamp, company_id))
        ended = conn.execute("UPDATE workplace_memberships SET status='ended',ended_at=COALESCE(ended_at,?),end_reason='company_offboarding',updated_at=? WHERE company_id=? AND status='active'", (stamp, stamp, company_id)).rowcount
        # Restore the personal-account role; retain the user and workplace records.
        conn.execute("UPDATE users SET role_type='student',user_category='adult',institution_id=NULL WHERE role_type='workplace_employee' AND institution_id=? AND id IN (SELECT user_id FROM workplace_memberships WHERE company_id=? AND status='ended')", (company_id, company_id))
        _event(conn, company_id, "WORKPLACE_MEMBERSHIPS_CLOSED", actor_id=actor_id, at=stamp)
        _event(conn, company_id, "WORKPLACE_PROVIDER_RELATIONSHIPS_ENDED", actor_id=actor_id, at=stamp)
        _event(conn, company_id, "WORKPLACE_CONTINUITY_PERIOD_ENDED", actor_id=actor_id, at=stamp)
        conn.execute("UPDATE workplace_offboarding SET status='RETENTION_PERIOD',updated_at=? WHERE company_id=?", (stamp, company_id))
        _event(conn, company_id, "WORKPLACE_RETENTION_PERIOD_ENTERED", actor_id=actor_id, at=stamp)
        current = conn.execute("SELECT * FROM workplace_offboarding WHERE company_id=?", (company_id,)).fetchone()
    return dict(current)


def complete_offboarding(conn, company_id: str, *, actor_id: str, now: datetime | None = None) -> dict:
    """Mark lifecycle complete only after retention deadline and case obligations."""
    instant = now or _now()
    row = conn.execute("SELECT * FROM workplace_offboarding WHERE company_id=?", (company_id,)).fetchone()
    if not row or row["status"] != "RETENTION_PERIOD":
        raise ValueError("Offboarding must be in its retention period before completion")
    if row["retention_deadline"] and row["retention_deadline"] > instant.isoformat():
        raise ValueError("Configured retention period has not ended")
    obligations = conn.execute("SELECT COUNT(*) FROM workplace_support_cases WHERE company_id=? AND status IN ('open','active')", (company_id,)).fetchone()[0]
    if obligations:
        raise ValueError("Active support-case obligations remain")
    stamp = instant.isoformat()
    conn.execute("UPDATE workplace_offboarding SET status='COMPLETED',completed_at=?,updated_at=? WHERE company_id=?", (stamp, stamp, company_id))
    _event(conn, company_id, "WORKPLACE_OFFBOARDING_COMPLETED", actor_id=actor_id, at=stamp)
    return dict(conn.execute("SELECT * FROM workplace_offboarding WHERE company_id=?", (company_id,)).fetchone())


def termination_effective(conn, company_id: str, *, now: datetime | None = None) -> bool:
    """Fail closed based on current commercial date, independent of maintenance timing."""
    instant = now or _now()
    row = conn.execute("SELECT status,cancellation_effective_date FROM workplace_commercial_accounts WHERE company_id=?", (company_id,)).fetchone()
    if not row:
        return False
    status = str(row["status"] or "").upper()
    return status == "TERMINATED" or (status == "CANCELLED" and row["cancellation_effective_date"] and row["cancellation_effective_date"][:10] <= instant.date().isoformat())
