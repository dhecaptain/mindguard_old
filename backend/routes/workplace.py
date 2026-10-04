"""Privacy-separated workplace wellbeing pilot APIs.

Company reporting is deliberately organization-wide and suppressed until at
least ten distinct employees have completed a check-in. There are no member
listing, filtering, or export endpoints for company administrators.
"""

import json
import html
import logging
import re
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from backend.auth import hash_password, require_auth
from backend.database import (
    consume_rate_limit,
    create_institution,
    create_user,
    get_db,
    set_user_invitation,
    write_audit,
)
from backend.services.crypto import decrypt_pii, encrypt_pii, hash_email, hash_token
from backend.services.email_sender import send_html_email
from backend.services.workplace_commercial import (
    CAPABILITIES as COMMERCIAL_CAPABILITIES,
    PLANS as WORKPLACE_PLANS,
    POPULATION_BANDS,
    STATUS_VALUES as COMMERCIAL_STATUSES,
    can_use as commercial_can_use,
    ensure_account as ensure_commercial_account,
    grace_period_days,
    plan_limit as commercial_plan_limit,
    record_event as record_commercial_event,
    resolve_account as resolve_commercial_account,
    summary as commercial_summary,
    transition as transition_commercial_account,
)
from backend.services.workplace_lifecycle import (
    complete_offboarding,
    retention_decision,
    schedule_offboarding,
    sync_offboarding,
    termination_effective,
)
from backend.services.workplace_analytics import AVAILABLE as ANALYTICS_AVAILABLE, get_workplace_insights

router = APIRouter(prefix="/api/v1/workplace", tags=["workplace"])
logger = logging.getLogger(__name__)
NOTICE_VERSION = "workplace-v1"
WORKPLACE_ADMIN_TERMS_VERSION = "workplace-admin-v1"
WORKPLACE_EMPLOYEE_TERMS_VERSION = "workplace-participant-v1"
PERSONAL_EMAIL_DOMAINS = {"gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.uk", "outlook.com", "hotmail.com", "live.com", "icloud.com", "aol.com"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _admin_invitation_state(row) -> str:
    status = str(row["status"] or "").lower()
    state = str(row["workplace_invitation_status"] or "").lower()
    if status == "revoked" or state == "revoked":
        return "revoked"
    if status in {"pending", "invited"}:
        expiry = row["invitation_expires_at"]
        if expiry and expiry <= _now():
            return "expired"
        return state if state in {"pending", "expired"} else "pending"
    return "accepted" if status in {"approved", "active"} else state or "pending"


def purge_expired_workplace_records() -> dict[str, int]:
    """Advance workplace lifecycle and execute configured, dependency-safe retention."""
    conn = get_db()
    now = datetime.now(timezone.utc)
    expired_credentials = conn.execute(
        "SELECT provider_id FROM workplace_provider_credentials WHERE status='verified' AND expires_at IS NOT NULL AND expires_at<?",
        (now.date().isoformat(),),
    ).fetchall()
    for credential in expired_credentials:
        _provider_credential_state(conn, credential["provider_id"], today=now.date())
    companies = conn.execute(
        "SELECT company_id,retention_days FROM workplace_settings"
    ).fetchall()
    for account in conn.execute("SELECT company_id FROM workplace_commercial_accounts").fetchall():
        resolve_commercial_account(conn, account["company_id"], at=now.date())
        sync_offboarding(conn, account["company_id"], now=now)
    purged_cases = 0
    purged_checkins = 0
    for company in companies:
        company_purged_cases = 0
        cutoff = (now - timedelta(days=max(1, int(company["retention_days"] or 365)))).isoformat()
        expired_cases = conn.execute(
            "SELECT id FROM workplace_support_cases WHERE company_id=? "
            "AND (status IN ('closed','withdrawn','expired') OR withdrawn_at IS NOT NULL) "
            "AND COALESCE(updated_at,created_at)<=?",
            (company["company_id"], cutoff),
        ).fetchall()
        for case in expired_cases:
            dependencies = conn.execute(
                "SELECT continuity_until FROM workplace_support_cases WHERE id=?", (case["id"],)
            ).fetchone()
            if dependencies and retention_decision(
                "closed_case", conn.execute("SELECT COALESCE(closed_at,updated_at,created_at) FROM workplace_support_cases WHERE id=?", (case["id"],)).fetchone()[0],
                int(company["retention_days"] or 365),
                active_dependency=bool(dependencies["continuity_until"] and dependencies["continuity_until"] > now.isoformat()), now=now,
            ) == "DELETE":
                # Case-owned notes, messages and appointments follow their parent
                # through the established case foreign keys.
                conn.execute("DELETE FROM workplace_support_cases WHERE id=?", (case["id"],))
                purged_cases += 1
                company_purged_cases += 1
        old_checkins = conn.execute(
            "SELECT id,created_at FROM workplace_checkins WHERE company_id=? AND created_at<=? "
            "AND NOT EXISTS (SELECT 1 FROM workplace_support_cases c WHERE c.shared_checkin_id=workplace_checkins.id)",
            (company["company_id"], cutoff),
        ).fetchall()
        deleted_checkins = 0
        for checkin in old_checkins:
            if retention_decision("checkin", checkin["created_at"], int(company["retention_days"] or 365), now=now) == "DELETE":
                conn.execute("DELETE FROM workplace_checkins WHERE id=?", (checkin["id"],))
                deleted_checkins += 1
        purged_checkins += max(0, deleted_checkins)
        if company_purged_cases or deleted_checkins:
            conn.execute(
                "INSERT INTO workplace_audit_events (id,company_id,actor_user_id,event_type,occurred_at) VALUES (?,?,NULL,'WORKPLACE_RETENTION_PURGED',?)",
                (str(uuid.uuid4()), company["company_id"], now.isoformat()),
            )
    conn.commit()
    conn.close()
    return {"cases": purged_cases, "checkins": purged_checkins}


def _audit(conn, company_id: str, actor_id: str | None, event: str) -> None:
    conn.execute(
        "INSERT INTO workplace_audit_events (id, company_id, actor_user_id, event_type, occurred_at) VALUES (?,?,?,?,?)",
        (str(uuid.uuid4()), company_id, actor_id, event, _now()),
    )


def _company_admin(user: dict, *, owner: bool = False, terms: bool = True) -> str:
    if user.get("role_type") != "company_admin" or not user.get("institution_id"):
        raise HTTPException(403, "Company administrator access required")
    conn = get_db()
    row = conn.execute(
        "SELECT type, status FROM institutions WHERE id = ?", (user["institution_id"],)
    ).fetchone()
    if not row or str(row["type"]).lower() != "company":
        conn.close()
        raise HTTPException(403, "This account is not assigned to a workplace tenant")
    if str(row["status"] or "").upper() != "ACTIVE":
        conn.close()
        raise HTTPException(403, "This workplace is not active")
    if termination_effective(conn, user["institution_id"]):
        conn.commit()
        conn.close()
        raise HTTPException(403, "Workplace operations have ended. Use the read-only offboarding status page.")
    conn.commit()
    conn.close()
    if str(user.get("status") or "approved").lower() not in {"approved", "active"}:
        raise HTTPException(403, "Your account is not active")
    if terms and user.get("workplace_terms_version") != WORKPLACE_ADMIN_TERMS_VERSION:
        raise HTTPException(403, "Accept the current workplace administrator terms before continuing")
    if owner and user.get("workplace_admin_role") != "owner":
        raise HTTPException(403, "Company owner access required")
    return user["institution_id"]


def _is_demo_company(conn, company_id: str) -> bool:
    row = conn.execute(
        "SELECT demo_mode FROM workplace_settings WHERE company_id=?", (company_id,)
    ).fetchone()
    return bool(row and row["demo_mode"])


def _assert_owner_in_transaction(conn, company_id: str, user_id: str) -> None:
    row = conn.execute(
        "SELECT u.workplace_admin_role,u.workplace_terms_version,u.status,i.status AS company_status "
        "FROM users u JOIN institutions i ON i.id=u.institution_id WHERE u.id=? AND u.institution_id=? "
        "AND u.role_type='company_admin' AND i.type='company'",
        (user_id, company_id),
    ).fetchone()
    if not row or row["workplace_admin_role"] != "owner" or row["workplace_terms_version"] != WORKPLACE_ADMIN_TERMS_VERSION or str(row["status"]).lower() not in {"approved", "active"} or str(row["company_status"]).upper() != "ACTIVE":
        # These checks run after BEGIN IMMEDIATE. Release the write lock on
        # authorization failure so a concurrent ownership transfer cannot
        # strand the SQLite connection/transaction.
        conn.rollback()
        conn.close()
        raise HTTPException(403, "Current active company owner access required")


def _normalize_domains(values: list[str]) -> list[str]:
    domains = sorted({str(value).strip().lower().lstrip("@") for value in values if str(value).strip()})
    if any(not re.fullmatch(r"(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", domain) for domain in domains):
        raise HTTPException(400, "Enter valid organization-owned email domains")
    if set(domains) & PERSONAL_EMAIL_DOMAINS:
        raise HTTPException(400, "Personal email-provider domains cannot be approved workplace domains")
    return domains


def _company_enrollment_is_ready(conn, company_id: str | None = None, *, token: str | None = None):
    params: list = []
    clauses = []
    if company_id:
        clauses.append("l.company_id=?")
        params.append(company_id)
    if token is not None:
        clauses.append("l.token_hash=? AND l.revoked_at IS NULL AND (l.expires_at IS NULL OR l.expires_at>?)")
        params.extend([hash_token(token), _now()])
    where = " AND ".join(clauses)
    if where:
        where = " AND " + where
    return conn.execute(
        "SELECT l.id,l.company_id,s.work_email_domains_json,s.privacy_notice_version,s.demo_mode "
        "FROM workplace_enrollment_links l JOIN workplace_settings s ON s.company_id=l.company_id "
        "JOIN institutions i ON i.id=l.company_id WHERE 1=1" + where + " "
        "AND i.type='company' AND i.status='ACTIVE' AND ((s.demo_mode=1 AND EXISTS (SELECT 1 FROM workplace_providers p "
        "JOIN workplace_provider_credentials c ON c.provider_id=p.provider_id "
        "JOIN users pu ON pu.id=p.provider_id LEFT JOIN workplace_provider_operations po ON po.provider_id=p.provider_id "
        "WHERE p.company_id=l.company_id AND p.status='active' AND c.status='verified' AND c.demo_only=1 "
        "AND COALESCE(po.access_status,'active')='active' AND pu.status IN ('approved','active'))) OR "
        "(s.demo_mode=0 AND s.legal_review_complete=1 AND s.policy_status='approved' AND EXISTS (SELECT 1 FROM workplace_providers p "
        "JOIN workplace_provider_credentials c ON c.provider_id=p.provider_id "
        "JOIN users pu ON pu.id=p.provider_id LEFT JOIN workplace_provider_operations po ON po.provider_id=p.provider_id "
        "WHERE p.company_id=l.company_id AND p.status='active' AND c.status='verified' AND c.demo_only=0 "
        "AND (c.valid_from IS NULL OR c.valid_from<=date('now')) AND (c.expires_at IS NULL OR c.expires_at>=date('now')) "
        "AND COALESCE(po.access_status,'active')='active' AND pu.status IN ('approved','active')))) LIMIT 1",
        params,
    ).fetchone()


def _mark_provider_cases_for_reassignment(conn, provider_id: str, reason: str, *, company_id: str | None = None) -> int:
    company_clause = " AND company_id=?" if company_id else ""
    params: tuple = (provider_id, company_id) if company_id else (provider_id,)
    rows = conn.execute(
        "SELECT id,company_id FROM workplace_support_cases WHERE provider_id=? "
        "AND status IN ('open','active') AND assignment_status='assigned' AND withdrawn_at IS NULL" + company_clause,
        params,
    ).fetchall()
    now = _now()
    for row in rows:
        conn.execute(
            "UPDATE workplace_support_cases SET assignment_status='reassignment_required',updated_at=? WHERE id=?",
            (now, row["id"]),
        )
        conn.execute(
            "INSERT INTO workplace_case_assignment_history (id,case_id,company_id,previous_provider_id,new_provider_id,event_type,occurred_at) VALUES (?,?,?,?,NULL,?,?)",
            (str(uuid.uuid4()), row["id"], row["company_id"], provider_id, f"provider_unavailable:{reason}", now),
        )
        _audit(conn, row["company_id"], None, "WORKPLACE_CASE_REASSIGNMENT_REQUIRED")
    return len(rows)


def _provider_credential_state(conn, provider_id: str, *, today: date | None = None) -> dict | None:
    """Resolve credential validity at request time and persist an observed expiry once."""
    row = conn.execute(
        "SELECT c.*,COALESCE(o.access_status,'active') AS access_status,"
        "COALESCE(o.availability,'available') AS availability "
        "FROM workplace_provider_credentials c LEFT JOIN workplace_provider_operations o ON o.provider_id=c.provider_id "
        "WHERE c.provider_id=?",
        (provider_id,),
    ).fetchone()
    if not row:
        return None
    current_day = today or datetime.now(timezone.utc).date()
    status = str(row["status"] or "").lower()
    expires = row["expires_at"] if "expires_at" in row.keys() else None
    valid_from = row["valid_from"] if "valid_from" in row.keys() else None
    if status == "verified" and expires and date.fromisoformat(str(expires)[:10]) < current_day:
        now = _now()
        changed = conn.execute(
            "UPDATE workplace_provider_credentials SET status='expired' WHERE provider_id=? AND status='verified'",
            (provider_id,),
        ).rowcount
        if changed:
            conn.execute(
                "INSERT INTO workplace_provider_credential_history (id,provider_id,professional_type_encrypted,title_encrypted,qualification_encrypted,registration_encrypted,verification_reference_encrypted,status,submitted_at,reviewed_by,reviewed_at,valid_from,expires_at) VALUES (?,?,?,?,?,? ,?,'expired',?,?,?, ?,?)",
                (str(uuid.uuid4()), provider_id, row["professional_type"], row["title_encrypted"], row["qualification_encrypted"], row["registration_encrypted"], row["verification_reference_encrypted"], now, row["reviewed_by"], now, valid_from, expires),
            )
            affected = conn.execute(
                "SELECT DISTINCT company_id FROM workplace_providers WHERE provider_id=?",
                (provider_id,),
            ).fetchall()
            for company in affected:
                conn.execute(
                    "INSERT INTO workplace_audit_events (id,company_id,actor_user_id,event_type,occurred_at) VALUES (?,?,NULL,'WORKPLACE_PROVIDER_CREDENTIAL_EXPIRED',?)",
                    (str(uuid.uuid4()), company["company_id"], now),
                )
            _mark_provider_cases_for_reassignment(conn, provider_id, "credential_expired")
            conn.commit()
            row = conn.execute(
                "SELECT c.*,COALESCE(o.access_status,'active') AS access_status,COALESCE(o.availability,'available') AS availability "
                "FROM workplace_provider_credentials c LEFT JOIN workplace_provider_operations o ON o.provider_id=c.provider_id WHERE c.provider_id=?",
                (provider_id,),
            ).fetchone()
            status = "expired"
    valid_start = not valid_from or date.fromisoformat(str(valid_from)[:10]) <= current_day
    valid_expiry = not expires or date.fromisoformat(str(expires)[:10]) >= current_day
    return {
        "status": status,
        "credential_valid": status == "verified" and valid_start and valid_expiry,
        "access_status": str(row["access_status"] or "active").lower(),
        "availability": str(row["availability"] or "available").lower(),
        "valid_from": valid_from,
        "expires_at": expires,
    }


def _validate_credential_period(valid_from: str | None, expires_at: str | None) -> None:
    try:
        starts = date.fromisoformat(valid_from) if valid_from else None
        expires = date.fromisoformat(expires_at) if expires_at else None
    except ValueError as exc:
        raise HTTPException(400, "Credential dates must be valid ISO dates") from exc
    if starts and expires and expires < starts:
        raise HTTPException(400, "Credential expiry must be on or after its valid-from date")


def _provider_can_receive_case(conn, provider_id: str, company_id: str) -> bool:
    provider = conn.execute(
        "SELECT u.id,u.status,u.role_type,p.status AS association_status FROM users u "
        "JOIN workplace_providers p ON p.provider_id=u.id AND p.company_id=? "
        "JOIN institutions i ON i.id=p.company_id WHERE u.id=? AND i.type='company' AND i.status='ACTIVE'",
        (company_id, provider_id),
    ).fetchone()
    state = _provider_credential_state(conn, provider_id)
    return bool(
        provider
        and provider["role_type"] == "workplace_provider"
        and str(provider["status"]).lower() in {"approved", "active"}
        and provider["association_status"] == "active"
        and state
        and state["credential_valid"]
        and state["access_status"] == "active"
        and state["availability"] == "available"
    )


def _provider_access(
    user: dict,
    *,
    case_id: str | None = None,
    writable: bool = False,
    require_association: bool = True,
):
    """One authorization path for active provider, valid credential and assigned case scope."""
    if user.get("role_type") != "workplace_provider":
        raise HTTPException(403, "Approved workplace provider access required")
    conn = get_db()
    if case_id:
        case_company = conn.execute("SELECT company_id FROM workplace_support_cases WHERE id=? AND provider_id=?", (case_id, user["id"])).fetchone()
        if case_company:
            sync_offboarding(conn, case_company["company_id"])
    live_user = conn.execute("SELECT role_type,status FROM users WHERE id=?", (user["id"],)).fetchone()
    if not live_user or live_user["role_type"] != "workplace_provider" or str(live_user["status"] or "").lower() not in {"approved", "active"}:
        conn.close()
        raise HTTPException(403, "Approved workplace provider access required")
    state = _provider_credential_state(conn, user["id"])
    if not state:
        conn.close()
        raise HTTPException(403, "Provider access is unavailable because no credential record was found")
    if not state["credential_valid"]:
        current_day = datetime.now(timezone.utc).date().isoformat()
        conn.close()
        if state["status"] == "verified" and state["valid_from"] and str(state["valid_from"])[:10] > current_day:
            raise HTTPException(403, f"Your license is verified but does not become effective until {str(state['valid_from'])[:10]}")
        if state["status"] == "verified" and state["expires_at"] and str(state["expires_at"])[:10] < current_day:
            raise HTTPException(403, f"Your verified license expired on {str(state['expires_at'])[:10]}")
        raise HTTPException(403, "Provider access is unavailable because the credential is not currently valid")
    if state["access_status"] != "active":
        conn.close()
        raise HTTPException(403, "Provider access is paused. Contact MindGuard Admin for help")
    valid_association = conn.execute(
        "SELECT 1 FROM workplace_providers p JOIN institutions i ON i.id=p.company_id "
        "WHERE p.provider_id=? AND i.type='company' AND i.status='ACTIVE' AND (p.status='active' OR "
        "(p.status='ending' AND EXISTS (SELECT 1 FROM workplace_support_cases c WHERE c.company_id=p.company_id "
        "AND c.provider_id=p.provider_id AND c.status IN ('open','active') AND c.withdrawn_at IS NULL AND c.continuity_until>?))) LIMIT 1",
        (user["id"], _now()),
    ).fetchone()
    if case_id:
        clauses = " AND c.id=? AND c.assignment_status='assigned'"
        if writable:
            clauses += " AND c.status IN ('open','active')"
        row = conn.execute(
            "SELECT c.id,c.company_id,c.user_id,c.provider_id,c.shared_checkin_id,c.status,c.withdrawn_at,c.assignment_status,c.continuity_until "
            "FROM workplace_support_cases c JOIN workplace_providers p ON p.company_id=c.company_id "
            "AND p.provider_id=c.provider_id AND (p.status='active' OR (p.status='ending' AND c.continuity_until>?)) "
            "JOIN institutions i ON i.id=c.company_id AND i.type='company' AND i.status='ACTIVE' "
            "WHERE c.provider_id=? AND c.withdrawn_at IS NULL" + clauses,
            (_now(), user["id"], case_id),
        ).fetchone()
        conn.close()
        if not row:
            raise HTTPException(404, "Active workplace support case not found")
        return dict(row)
    conn.close()
    if require_association and not valid_association:
        raise HTTPException(403, "No active workplace provider relationship")
    return None


def _employee(user: dict) -> dict:
    if user.get("role_type") != "workplace_employee":
        raise HTTPException(403, "Workplace employee access required")
    if str(user.get("status") or "").lower() not in {"approved", "active"}:
        raise HTTPException(403, "Your workplace account is not active")
    if user.get("workplace_terms_version") != WORKPLACE_EMPLOYEE_TERMS_VERSION:
        raise HTTPException(403, "Accept the current workplace participation terms before continuing")
    conn = get_db()
    row = conn.execute(
        "SELECT m.* FROM workplace_memberships m JOIN institutions i ON i.id=m.company_id "
        "WHERE m.user_id = ? AND m.status = 'active' AND m.withdrawn_at IS NULL "
        "AND i.type='company' AND i.status='ACTIVE'",
        (user["id"],),
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(403, "Workplace participation is not active")
    return dict(row)


@router.get("/member/context")
async def workplace_member_context(user: dict = Depends(require_auth)):
    """Return only the tenant name and demo marker for the worker workspace shell."""
    membership = _employee(user)
    conn = get_db()
    row = conn.execute(
        "SELECT i.name,s.demo_mode FROM institutions i JOIN workplace_settings s ON s.company_id=i.id WHERE i.id=?",
        (membership["company_id"],),
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Workplace details were not found")
    return {"company_name": row["name"], "demo_mode": bool(row["demo_mode"])}


class EnrollmentStart(BaseModel):
    token: str = Field(min_length=32, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)
    accepted_notice: bool
    accepted_workplace_terms: bool


class EnrollmentVerify(BaseModel):
    challenge_id: str
    code: str = Field(min_length=6, max_length=6, pattern=r"^[0-9]{6}$")


class ExistingEnrollmentStart(BaseModel):
    token: str = Field(min_length=32, max_length=200)
    accepted_notice: bool
    accepted_workplace_terms: bool


class ExistingEnrollmentVerify(BaseModel):
    challenge_id: str
    code: str = Field(min_length=6, max_length=6, pattern=r"^[0-9]{6}$")


class WorkplaceDomain(BaseModel):
    domain: str = Field(min_length=3, max_length=253)


class WorkplaceOwnershipTransfer(BaseModel):
    administrator_id: str = Field(min_length=1, max_length=80)


class CheckinCreate(BaseModel):
    mood: int = Field(ge=1, le=5)
    stress: int = Field(ge=1, le=5)
    support_access: int = Field(ge=1, le=5)


class SupportRequest(BaseModel):
    provider_id: str
    share_latest_checkin: bool


class ProviderAttach(BaseModel):
    provider_email: EmailStr


class ProviderCredentialCreate(BaseModel):
    provider_email: EmailStr
    professional_type: str | None = Field(default=None, max_length=160)
    professional_title: str = Field(min_length=2, max_length=160)
    qualification: str = Field(min_length=2, max_length=300)
    registration_number: str = Field(min_length=2, max_length=160)
    license_state: str = Field(min_length=2, max_length=80)
    verification_reference: str = Field(min_length=4, max_length=500)
    valid_from: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    expires_at: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class WorkplaceProviderAccountCreate(ProviderCredentialCreate):
    full_name: str = Field(min_length=2, max_length=200)


class ProviderCredentialSubmission(BaseModel):
    professional_type: str | None = Field(default=None, max_length=160)
    professional_title: str = Field(min_length=2, max_length=160)
    qualification: str = Field(min_length=2, max_length=300)
    registration_number: str = Field(min_length=2, max_length=160)
    license_state: str | None = Field(default=None, min_length=2, max_length=80)


class ProviderCredentialReview(BaseModel):
    review_id: str = Field(min_length=1, max_length=80)
    decision: str = Field(pattern=r"^(verify|reject)$")
    verification_reference: str | None = Field(default=None, min_length=4, max_length=500)
    valid_from: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    expires_at: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    reason: str | None = Field(default=None, max_length=500)


class ProviderAccessAction(BaseModel):
    action: str = Field(pattern=r"^(suspend|reactivate|revoke|deactivate)$")
    reason: str = Field(min_length=3, max_length=500)


class ProviderCredentialRevoke(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class ProviderAvailability(BaseModel):
    availability: str = Field(pattern=r"^(available|unavailable)$")


class WorkplaceCaseReassignment(BaseModel):
    provider_id: str = Field(min_length=1, max_length=80)
    confirm_shared_history: bool


class CompanyCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    admin_name: str | None = Field(default=None, max_length=200)
    admin_email: EmailStr
    work_email_domains: list[str] = Field(min_length=1, max_length=20)
    privacy_contact_email: EmailStr | None = None
    employee_population_range: str | None = Field(default=None, max_length=80)
    retention_days: int = Field(default=365, ge=30, le=3650)


class DemoWorkplaceCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    admin_name: str = Field(min_length=2, max_length=200)
    admin_email: EmailStr


class CompanyPolicyUpdate(BaseModel):
    privacy_contact_email: EmailStr
    employee_population_range: str = Field(min_length=1, max_length=80)
    retention_days: int = Field(ge=30, le=3650)
    privacy_notice_version: str = Field(min_length=3, max_length=80)
    confirm_aggregate_only: bool


class CompanyAdminInvite(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    email: EmailStr


class WorkplaceDemoConversion(BaseModel):
    company_name: str = Field(min_length=2, max_length=200)
    admin_name: str = Field(min_length=2, max_length=200)
    admin_email: EmailStr
    work_email_domains: list[str] = Field(min_length=1, max_length=20)
    privacy_contact_email: EmailStr
    population_range: str | None = Field(default=None, max_length=80)
    employee_population_range: str | None = Field(default=None, max_length=80)
    retention_days: int = Field(default=365, ge=30, le=3650)


class WorkplaceCaseNoteCreate(BaseModel):
    private_note: str = Field(min_length=1, max_length=10000)
    employee_update: str | None = Field(default=None, max_length=3000)


class WorkplaceAppointmentCreate(BaseModel):
    starts_at: str = Field(min_length=20, max_length=40)
    mode: str = Field(pattern=r"^(online|physical)$")
    location_or_link: str = Field(min_length=3, max_length=1000)


class WorkplaceMessageCreate(BaseModel):
    case_id: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=4000)


class WorkplaceMessageBody(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class WorkplaceAppointmentStatus(BaseModel):
    status: str = Field(pattern=r"^(cancelled|completed)$")


class LegalReviewRecord(BaseModel):
    reviewed: bool
    reference: str = Field(min_length=4, max_length=500)


class CompanyLifecycle(BaseModel):
    action: str = Field(pattern=r"^(activate|suspend|archive)$")
    reason: str = Field(min_length=3, max_length=500)


class WorkplaceCommercialUpdate(BaseModel):
    status: str | None = Field(default=None, pattern=r"^(PILOT|TRIAL|ACTIVE|GRACE_PERIOD|SUSPENDED|CANCELLED|TERMINATED)$")
    plan_key: str | None = Field(default=None, pattern=r"^(pilot|trial|team|enterprise|legacy_pilot)$")
    contract_start_date: date | None = None
    contract_end_date: date | None = None
    billing_cycle: str | None = Field(default=None, pattern=r"^(monthly|annual|one_time|custom)$")
    population_band: str | None = None
    renewal_date: date | None = None
    grace_period_end: date | None = None
    cancellation_effective_date: date | None = None
    cancellation_reason: str | None = Field(default=None, max_length=500)
    reason: str | None = Field(default=None, max_length=500)
    internal_reference: str | None = Field(default=None, max_length=500)
    internal_notes: str | None = Field(default=None, max_length=5000)
    enabled_capabilities: dict[str, bool] | None = None
    external_customer_reference: str | None = Field(default=None, max_length=200)
    external_subscription_reference: str | None = Field(default=None, max_length=200)
    billing_provider: str | None = Field(default=None, max_length=80)


class WorkplaceOffboardingAction(BaseModel):
    action: str = Field(pattern=r"^(complete)$")


@router.post("/enrollment/start", status_code=202)
async def start_enrollment(data: EnrollmentStart, request: Request):
    """Start a private opt-in. Email ownership is verified before account creation."""
    if not data.accepted_notice:
        raise HTTPException(400, "You must accept the voluntary participation notice")
    if not data.accepted_workplace_terms:
        raise HTTPException(400, "Accept the workplace participation terms before enrolling")
    email = str(data.email).strip().lower()
    domain = email.rsplit("@", 1)[-1]
    ip = request.client.host if request.client else "unknown"
    if not consume_rate_limit(
        f"workplace-enrollment-ip:{ip}", 20, 3600
    ) or not consume_rate_limit(
        f"workplace-enrollment-email:{hash_email(email)}", 3, 900
    ):
        raise HTTPException(
            429, "Too many enrollment attempts. Please wait before trying again."
        )
    conn = get_db()
    link = _company_enrollment_is_ready(conn, token=data.token)
    if not link:
        conn.close()
        raise HTTPException(400, "This enrollment link is invalid, expired, or revoked")
    if not commercial_can_use(conn, link["company_id"], "enrollment"):
        conn.commit(); conn.close()
        raise HTTPException(403, "New workplace enrollment is temporarily unavailable for this company")
    try:
        domains = json.loads(link["work_email_domains_json"])
    except (ValueError, TypeError):
        domains = []
    if not link["demo_mode"] and domain not in {str(d).lower().lstrip("@").strip() for d in domains}:
        conn.close()
        raise HTTPException(
            400, "Use an approved work email address for this enrollment"
        )
    if conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
        conn.close()
        raise HTTPException(
            409, "A MindGuard account already uses this email. Sign in and use the existing-account join option on this link."
        )
    if conn.execute(
        "SELECT 1 FROM workplace_enrollment_challenges WHERE email_hash = ? AND used_at IS NULL AND expires_at > ?",
        (hash_email(email), _now()),
    ).fetchone():
        conn.close()
        raise HTTPException(
            429,
            "A verification email was already sent. Check your inbox before requesting another.",
        )
    challenge_id = str(uuid.uuid4())
    code = f"{secrets.randbelow(1_000_000):06d}"
    expires = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
    conn.execute(
        "INSERT INTO workplace_enrollment_challenges (id, company_id, link_id, email_hash, email_encrypted, name_encrypted, code_hash, password_hash, expires_at, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            challenge_id,
            link["company_id"],
            link["id"],
            hash_email(email),
            encrypt_pii(email),
            encrypt_pii(data.name.strip()),
            hash_token(code),
            hash_password(data.password),
            expires,
            _now(),
        ),
    )
    conn.commit()
    conn.close()
    sent, _ = send_html_email(
        email,
        "Verify your MindGuard workplace enrollment",
        f"<p>Your verification code is <strong>{code}</strong>.</p><p>It expires in 15 minutes. Participation is voluntary. Your employer will not receive your identity or individual wellbeing information.</p>",
        related_type="workplace_enrollment",
        related_id=challenge_id,
    )
    if not sent:
        # Do not expose the code through the response/logs. User can retry after expiry.
        raise HTTPException(
            503, "We could not send the verification email. Please try again later."
        )
    return {
        "challenge_id": challenge_id,
        "expires_in_minutes": 15,
        "message": "Check your work email for a verification code.",
    }


@router.post("/enrollment/existing/start", status_code=202)
async def start_existing_account_enrollment(data: ExistingEnrollmentStart, request: Request, user: dict = Depends(require_auth)):
    """Verify the registered mailbox before attaching an existing adult account."""
    if not data.accepted_notice:
        raise HTTPException(400, "You must accept the voluntary participation notice")
    if not data.accepted_workplace_terms:
        raise HTTPException(400, "Accept the workplace participation terms before enrolling")
    if user.get("role_type") != "student" or user.get("user_category") != "adult" or user.get("institution_id"):
        raise HTTPException(403, "Only an independent adult MindGuard account can join this workplace")
    if str(user.get("status") or "").lower() not in {"approved", "active"}:
        raise HTTPException(403, "Your MindGuard account is not active")
    ip = request.client.host if request.client else "unknown"
    if not consume_rate_limit(f"workplace-existing-ip:{ip}", 20, 3600) or not consume_rate_limit(f"workplace-existing-user:{user['id']}", 3, 900):
        raise HTTPException(429, "Too many enrollment attempts. Please wait before trying again.")
    conn = get_db()
    link = _company_enrollment_is_ready(conn, token=data.token)
    if not link:
        conn.close()
        raise HTTPException(400, "This enrollment link is invalid, expired, revoked, or not ready")
    if not commercial_can_use(conn, link["company_id"], "enrollment"):
        conn.commit(); conn.close()
        raise HTTPException(403, "New workplace enrollment is temporarily unavailable for this company")
    account = conn.execute("SELECT email,role_type,user_category,institution_id,status FROM users WHERE id=?", (user["id"],)).fetchone()
    email = str(account["email"]).strip().lower()
    domains = {str(d).strip().lower().lstrip("@") for d in json.loads(link["work_email_domains_json"] or "[]")}
    if not link["demo_mode"] and email.rsplit("@", 1)[-1] not in domains:
        conn.close()
        raise HTTPException(400, "Your registered email does not match an approved workplace domain")
    existing = conn.execute("SELECT company_id,status FROM workplace_memberships WHERE user_id=?", (user["id"],)).fetchone()
    if existing:
        conn.close()
        if existing["company_id"] == link["company_id"] and existing["status"] == "active":
            raise HTTPException(409, "You have already joined this workplace")
        raise HTTPException(409, "This account is already associated with a workplace and cannot join another")
    if conn.execute("SELECT 1 FROM workplace_existing_enrollment_challenges WHERE user_id=? AND used_at IS NULL AND expires_at>?", (user["id"], _now())).fetchone():
        conn.close()
        raise HTTPException(429, "A verification email was already sent. Check your inbox before requesting another.")
    code = f"{secrets.randbelow(1_000_000):06d}"
    challenge_id = str(uuid.uuid4())
    expires = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
    conn.execute(
        "INSERT INTO workplace_existing_enrollment_challenges (id,company_id,link_id,user_id,code_hash,notice_version,expires_at,created_at) VALUES (?,?,?,?,?,?,?,?)",
        (challenge_id, link["company_id"], link["id"], user["id"], hash_token(code), link["privacy_notice_version"], expires, _now()),
    )
    conn.commit(); conn.close()
    sent, _error = send_html_email(email, "Verify your workplace enrollment", f"<p>Your verification code is <strong>{code}</strong>.</p><p>It expires in 15 minutes. Participation is voluntary. Your employer will not receive your identity or individual wellbeing information.</p>", related_type="workplace_enrollment_existing", related_id=challenge_id)
    if not sent:
        raise HTTPException(503, "We could not send the verification email. Please try again later.")
    return {"challenge_id": challenge_id, "expires_in_minutes": 15, "message": "Check your registered email for a verification code."}


@router.post("/enrollment/existing/verify")
async def verify_existing_account_enrollment(data: ExistingEnrollmentVerify, user: dict = Depends(require_auth)):
    if user.get("role_type") != "student" or user.get("user_category") != "adult" or user.get("institution_id"):
        raise HTTPException(403, "This account cannot complete workplace enrollment")
    conn = get_db()
    now = _now()
    conn.execute("BEGIN IMMEDIATE")
    row = conn.execute(
        "SELECT c.*,s.work_email_domains_json,s.demo_mode FROM workplace_existing_enrollment_challenges c "
        "JOIN workplace_settings s ON s.company_id=c.company_id JOIN workplace_enrollment_links l ON l.id=c.link_id "
        "JOIN institutions i ON i.id=c.company_id WHERE c.id=? AND c.user_id=? AND c.used_at IS NULL AND c.expires_at>? "
        "AND l.revoked_at IS NULL AND (l.expires_at IS NULL OR l.expires_at>?) AND i.type='company' AND i.status='ACTIVE' "
        "AND ((s.demo_mode=1 AND EXISTS (SELECT 1 FROM workplace_providers p "
        "JOIN workplace_provider_credentials pc ON pc.provider_id=p.provider_id JOIN users pu ON pu.id=p.provider_id "
        "LEFT JOIN workplace_provider_operations po ON po.provider_id=p.provider_id "
        "WHERE p.company_id=c.company_id AND p.status='active' AND pc.status='verified' AND pc.demo_only=1 "
        "AND COALESCE(po.access_status,'active')='active' AND pu.status IN ('approved','active'))) OR "
        "(s.demo_mode=0 AND s.legal_review_complete=1 AND s.policy_status='approved' AND EXISTS (SELECT 1 FROM workplace_providers p "
        "JOIN workplace_provider_credentials pc ON pc.provider_id=p.provider_id JOIN users pu ON pu.id=p.provider_id "
        "LEFT JOIN workplace_provider_operations po ON po.provider_id=p.provider_id "
        "WHERE p.company_id=c.company_id AND p.status='active' AND pc.status='verified' AND pc.demo_only=0 "
        "AND (pc.valid_from IS NULL OR pc.valid_from<=date('now')) AND (pc.expires_at IS NULL OR pc.expires_at>=date('now')) "
        "AND COALESCE(po.access_status,'active')='active' AND pu.status IN ('approved','active'))))",
        (data.challenge_id, user["id"], now, now),
    ).fetchone()
    if not row:
        conn.rollback(); conn.close()
        raise HTTPException(400, "The verification code is invalid or expired")
    if not commercial_can_use(conn, row["company_id"], "enrollment"):
        conn.rollback(); conn.close()
        raise HTTPException(403, "New workplace enrollment is temporarily unavailable for this company")
    if not secrets.compare_digest(row["code_hash"], hash_token(data.code)):
        attempts = row["attempts_count"] + 1
        conn.execute("UPDATE workplace_existing_enrollment_challenges SET attempts_count=?,used_at=CASE WHEN ?>=5 THEN ? ELSE used_at END WHERE id=?", (attempts, attempts, now, data.challenge_id))
        conn.commit(); conn.close()
        raise HTTPException(400, "The verification code is invalid or expired")
    account = conn.execute("SELECT email,role_type,user_category,institution_id,status FROM users WHERE id=?", (user["id"],)).fetchone()
    domains = {str(d).strip().lower().lstrip("@") for d in json.loads(row["work_email_domains_json"] or "[]")}
    if not account or account["role_type"] != "student" or account["user_category"] != "adult" or account["institution_id"] or str(account["status"]).lower() not in {"approved", "active"} or (not row["demo_mode"] and str(account["email"]).strip().lower().rsplit("@", 1)[-1] not in domains):
        conn.rollback(); conn.close()
        raise HTTPException(409, "Your account or approved work domain changed. Start enrollment again or contact support.")
    if conn.execute("SELECT 1 FROM workplace_memberships WHERE user_id=?", (user["id"],)).fetchone():
        conn.rollback(); conn.close()
        raise HTTPException(409, "This account is already associated with a workplace")
    try:
        conn.execute("UPDATE users SET role_type='workplace_employee',user_category='workplace_employee',institution_id=?,status='approved',onboarding_completed_at=?,terms_accepted_at=?,workplace_terms_version=? WHERE id=?", (row["company_id"], now, now, WORKPLACE_EMPLOYEE_TERMS_VERSION, user["id"]))
        conn.execute("INSERT INTO workplace_memberships (id,company_id,user_id,status,notice_version,consented_at,created_at,updated_at) VALUES (?,?,?,'active',?,?,?,?)", (str(uuid.uuid4()), row["company_id"], user["id"], row["notice_version"], now, now, now))
        conn.execute("UPDATE workplace_existing_enrollment_challenges SET used_at=? WHERE id=?", (now, data.challenge_id))
        _audit(conn, row["company_id"], user["id"], "EMPLOYEE_OPTED_IN")
        _audit(conn, row["company_id"], user["id"], "WORKPLACE_EMPLOYEE_TERMS_ACCEPTED")
        conn.commit()
    except Exception:
        conn.rollback(); conn.close()
        raise HTTPException(409, "This account could not be attached to the workplace")
    conn.close()
    from backend.auth import create_access_token
    return {"access_token": create_access_token(user["id"], "workplace_employee"), "token_type": "bearer", "user": {"id": user["id"], "email": account["email"], "name": user.get("name"), "role_type": "workplace_employee", "user_category": "workplace_employee"}}


@router.post("/admin/companies", status_code=201)
async def create_workplace_company(
    data: CompanyCreate, actor: dict = Depends(require_auth)
):
    """Global-admin setup; named employee roster and participation list are not created."""
    if actor.get("role_type") != "admin":
        raise HTTPException(403, "Global administrator access required")
    domains = _normalize_domains(data.work_email_domains)
    admin_email = str(data.admin_email).lower()
    if admin_email.rsplit("@", 1)[-1] not in domains:
        raise HTTPException(400, "The company administrator must use an approved work email domain")
    conn = get_db()
    admin = conn.execute(
        "SELECT * FROM users WHERE email = ?", (str(data.admin_email).lower(),)
    ).fetchone()
    conn.close()
    if admin and (
        admin["role_type"] != "student"
        or dict(admin).get("institution_id")
        or dict(admin).get("user_category") != "adult"
        or dict(admin).get("status") not in {"approved", "active"}
    ):
        raise HTTPException(
            400,
            "The designated administrator email already belongs to an incompatible account",
        )
    company = create_institution(data.name.strip(), "company", actor["id"])
    now = _now()
    invite_token: str | None = None
    if not admin:
        admin = create_user(
            admin_email,
            (data.admin_name or admin_email.split("@", 1)[0]).strip(),
            hash_password(secrets.token_urlsafe(32)),
            role_type="company_admin",
            institution_id=company["id"],
        )
        invite_token = secrets.token_urlsafe(32)
        set_user_invitation(admin["id"], hash_token(invite_token), (datetime.now(timezone.utc) + timedelta(days=7)).isoformat())
    conn = get_db()
    try:
        conn.execute(
            "UPDATE institutions SET status = 'ACTIVE' WHERE id = ?", (company["id"],)
        )
        conn.execute(
            "INSERT INTO workplace_settings (company_id, work_email_domains_json, privacy_notice_version, provider_service_enabled, privacy_contact_encrypted, employee_population_range, retention_days, policy_status, created_at, updated_at) VALUES (?,?,?,0,?,?,?,'draft',?,?)",
            (company["id"], json.dumps(domains), NOTICE_VERSION, encrypt_pii(str(data.privacy_contact_email or admin_email)), data.employee_population_range, data.retention_days, now, now),
        )
        ensure_commercial_account(conn, company["id"], population_range=data.employee_population_range, starts_on=now[:10], plan_key="pilot")
        record_commercial_event(conn, company["id"], actor["id"], "ACCOUNT_CREATED", None, "PILOT", "Initial workplace pilot account created", at=now)
        if invite_token:
            conn.execute("UPDATE users SET user_category='company_staff', status='pending', terms_accepted_at=NULL, workplace_admin_role='owner', workplace_invitation_status='pending', workplace_terms_version=NULL WHERE id=?", (admin["id"],))
        else:
            conn.execute("UPDATE users SET role_type='company_admin', user_category='company_staff', institution_id=?, terms_accepted_at=NULL, workplace_admin_role='owner', workplace_invitation_status='accepted', workplace_terms_version=NULL WHERE id=?", (company["id"], admin["id"]))
        _audit(conn, company["id"], actor["id"], "WORKPLACE_COMPANY_CREATED")
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise HTTPException(500, "Unable to configure the workplace tenant")
    conn.close()
    invitation_sent = False
    invitation_error = ""
    if invite_token:
        base = __import__("os").getenv("APP_BASE_URL", "https://app.mindguardai.me").rstrip("/")
        invitation_sent, invitation_error = send_html_email(
            admin_email,
            f"Join {data.name.strip()} on MindGuard",
            f"<p>Hello {data.admin_name or 'there'},</p><p>You have been invited to manage the private workplace wellbeing programme for <strong>{data.name.strip()}</strong>.</p><p><a href=\"{base}/invite?token={invite_token}\">Accept invitation</a></p><p>This single-use link expires in 7 days.</p>",
            related_type="workplace_admin_invitation",
            related_id=admin["id"],
        )
    return {
        "id": company["id"],
        "name": company["name"],
        "status": "ACTIVE",
        "admin_email": str(data.admin_email).lower(),
        "approved_work_email_domains": domains,
        "readiness": "legal_privacy_review_required",
        "legal_review_complete": False,
        "administrator_invitation_status": "invited" if invite_token else "active",
        "invitation_sent": invitation_sent,
        "invitation_error": invitation_error or None,
    }


@router.post("/admin/demo-workplaces", status_code=201)
async def create_demo_workplace(data: DemoWorkplaceCreate, actor: dict = Depends(require_auth)):
    """Create a visibly marked demo tenant with synthetic support capacity."""
    if actor.get("role_type") != "admin":
        raise HTTPException(403, "Global administrator access required")

    from backend.database import _make_referral_code

    company_id = str(uuid.uuid4())
    admin_id = str(uuid.uuid4())
    provider_id = str(uuid.uuid4())
    admin_email = str(data.admin_email).strip().lower()
    name = data.name.strip()
    now = _now()
    invite_token = secrets.token_urlsafe(32)
    invite_expires = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    provider_email = f"sample-counsellor+{provider_id}@demo.mindguard.invalid"
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM users WHERE lower(email)=?", (admin_email,)).fetchone():
            raise HTTPException(409, "Use a new email address for the demo administrator invitation")

        admin_referral = _make_referral_code()
        while conn.execute("SELECT 1 FROM users WHERE referral_code=?", (admin_referral,)).fetchone():
            admin_referral = _make_referral_code()
        provider_referral = _make_referral_code()
        while conn.execute("SELECT 1 FROM users WHERE referral_code=?", (provider_referral,)).fetchone():
            provider_referral = _make_referral_code()

        conn.execute(
            "INSERT INTO institutions (id,name,type,status,created_by,created_at,updated_at) VALUES (?,?, 'company','ACTIVE',?,?,?)",
            (company_id, name, actor["id"], now, now),
        )
        conn.execute(
            "INSERT INTO users (id,email,name,role_type,password_hash,status,created_at,referral_code,institution_id,user_category,terms_accepted_at,invitation_token_hash,invitation_expires_at,invited_at,workplace_admin_role,workplace_invitation_status,workplace_terms_version) "
            "VALUES (?,?,?,'company_admin',?,'pending',?,?,?,'company_staff',NULL,?,?,?,'owner','pending',NULL)",
            (admin_id, admin_email, data.admin_name.strip(), hash_password(secrets.token_urlsafe(32)), now, admin_referral, company_id, hash_token(invite_token), invite_expires, now),
        )
        conn.execute(
            "INSERT INTO users (id,email,name,role_type,password_hash,status,created_at,referral_code,institution_id,user_category,onboarding_completed_at) "
            "VALUES (?,?,?,'workplace_provider',?,'active',?,?,NULL,'workplace_provider',?)",
            (provider_id, provider_email, "Sample counsellor (demo)", hash_password(secrets.token_urlsafe(32)), now, provider_referral, now),
        )
        conn.execute(
            "INSERT INTO workplace_settings (company_id,work_email_domains_json,privacy_notice_version,provider_service_enabled,legal_review_complete,privacy_contact_encrypted,employee_population_range,retention_days,policy_status,created_at,updated_at,demo_mode) "
            "VALUES (?,'[]','workplace-demo-v1',1,0,?,'Demo workspace',30,'approved',?,?,1)",
            (company_id, encrypt_pii(admin_email), now, now),
        )
        conn.execute(
            "INSERT INTO workplace_provider_credentials (provider_id,professional_type,title_encrypted,qualification_encrypted,registration_encrypted,verification_reference_encrypted,status,reviewed_by,reviewed_at,valid_from,expires_at,demo_only,license_state_encrypted) "
            "VALUES (?,?,?,?,?,?,'verified',?,?,NULL,NULL,1,?)",
            (provider_id, encrypt_pii("Sample provider"), encrypt_pii("Sample counsellor (demo)"), encrypt_pii("Synthetic demo profile"), encrypt_pii("DEMO-NOT-A-LICENSE"), encrypt_pii("Synthetic sample only; not credential-verified"), actor["id"], now, encrypt_pii("Demo only")),
        )
        conn.execute("UPDATE users SET professional_title=? WHERE id=?", (encrypt_pii("Sample counsellor (demo)"), provider_id))
        conn.execute(
            "INSERT INTO workplace_provider_operations (provider_id,access_status,availability,changed_by,changed_at) VALUES (?,'active','available',?,?)",
            (provider_id, actor["id"], now),
        )
        conn.execute(
            "INSERT INTO workplace_providers (company_id,provider_id,status,created_at) VALUES (?,?,'active',?)",
            (company_id, provider_id, now),
        )
        ensure_commercial_account(conn, company_id, population_range="Demo workspace", starts_on=now[:10], plan_key="pilot")
        record_commercial_event(conn, company_id, actor["id"], "ACCOUNT_CREATED", None, "PILOT", "Demo workplace created", at=now)
        _audit(conn, company_id, actor["id"], "WORKPLACE_DEMO_CREATED")
        _audit(conn, company_id, actor["id"], "WORKPLACE_DEMO_PROVIDER_SEEDED")
        _audit(conn, company_id, actor["id"], "WORKPLACE_ADMIN_INVITATION_CREATED")
        conn.commit()
    except HTTPException:
        conn.rollback()
        conn.close()
        raise
    except Exception as exc:
        conn.rollback()
        conn.close()
        raise HTTPException(500, "Unable to create demo workplace") from exc
    conn.close()

    base = __import__("os").getenv("APP_BASE_URL", "https://app.mindguardai.me").rstrip("/")
    sent, error = send_html_email(
        admin_email,
        f"Try the MindGuard workplace demo for {name}",
        f"<p>Hello {data.admin_name.strip()},</p><p>You have been invited to explore a clearly marked MindGuard demo workplace for <strong>{name}</strong>.</p><p>This demo uses synthetic provider information. Do not enter real employee wellbeing details.</p><p><a href=\"{base}/invite?token={invite_token}\">Accept demo administrator invitation</a></p><p>This single-use link expires in 7 days.</p>",
        related_type="workplace_demo_admin_invitation",
        related_id=admin_id,
        metadata={"company_id": company_id},
    )
    conn = get_db()
    _audit(conn, company_id, actor["id"], "WORKPLACE_ADMIN_INVITATION_QUEUED" if sent else "WORKPLACE_ADMIN_INVITATION_DELIVERY_FAILED")
    conn.commit()
    conn.close()
    return {
        "id": company_id,
        "name": name,
        "demo_mode": True,
        "administrator_invitation_status": "pending",
        "invitation_sent": sent,
        "invitation_error": error or None,
    }


@router.post("/admin/demo-requests/{demo_request_id}/convert", status_code=201)
async def convert_workplace_demo_request(demo_request_id: str, data: WorkplaceDemoConversion, request: Request, actor: dict = Depends(require_auth)):
    """Convert a qualified company lead into a separately governed workplace tenant."""
    if actor.get("role_type") != "admin":
        raise HTTPException(403, "Global administrator access required")
    from backend.database import _make_referral_code
    domains = _normalize_domains(data.work_email_domains)
    admin_email = str(data.admin_email).strip().lower()
    if admin_email.rsplit("@", 1)[-1] not in domains:
        raise HTTPException(400, "The company administrator must use one of the approved work email domains")
    company_name = data.company_name.strip()
    token = secrets.token_urlsafe(32)
    now = _now()
    expires_at = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    company_id, admin_id = str(uuid.uuid4()), str(uuid.uuid4())
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        demo_row = conn.execute("SELECT * FROM demo_requests WHERE id=?", (demo_request_id,)).fetchone()
        if not demo_row:
            raise HTTPException(404, "Demo request not found")
        demo = dict(demo_row)
        if str(demo.get("organisation_type") or "").lower() != "company":
            raise HTTPException(400, "Only company demo requests can use workplace conversion")
        if demo.get("institution_id"):
            raise HTTPException(409, "This demo request has already been converted")
        if str(demo.get("status") or "").lower() not in {"qualified", "demo_scheduled", "closed_won"}:
            raise HTTPException(409, "Qualify or schedule the company demo before converting it")
        existing = conn.execute("SELECT 1 FROM users WHERE lower(email)=?", (admin_email,)).fetchone()
        if existing:
            raise HTTPException(409, "This email already belongs to a MindGuard account; choose an unregistered administrator email for invitation")
        referral_code = _make_referral_code()
        for _ in range(10):
            if not conn.execute("SELECT 1 FROM users WHERE referral_code=?", (referral_code,)).fetchone():
                break
            referral_code = _make_referral_code()
        for _ in range(10):
            if not conn.execute("SELECT 1 FROM users WHERE referral_code=?", (referral_code,)).fetchone():
                break
            referral_code = _make_referral_code()
        conn.execute("INSERT INTO institutions (id,name,type,status,created_by,created_at,updated_at) VALUES (?,?, 'company','ACTIVE',?,?,?)", (company_id,company_name,actor["id"],now,now))
        conn.execute("INSERT INTO users (id,email,name,role_type,password_hash,status,created_at,referral_code,institution_id,user_category,terms_accepted_at,invitation_token_hash,invitation_expires_at,invited_at,workplace_admin_role,workplace_invitation_status,workplace_terms_version) VALUES (?,?,?,'company_admin',?,'pending',?,?,?, 'company_staff',NULL,?,?,?,'owner','pending',NULL)", (admin_id,admin_email,data.admin_name.strip(),hash_password(secrets.token_urlsafe(32)),now,referral_code,company_id,hash_token(token),expires_at,now))
        population = data.population_range if data.population_range is not None else (data.employee_population_range or demo.get("population_range") or demo.get("employee_population_range"))
        conn.execute("INSERT INTO workplace_settings (company_id,work_email_domains_json,privacy_notice_version,provider_service_enabled,legal_review_complete,privacy_contact_encrypted,employee_population_range,retention_days,policy_status,created_at,updated_at) VALUES (?,?,?,0,0,?,?,?,'draft',?,?)", (company_id,json.dumps(domains),NOTICE_VERSION,encrypt_pii(str(data.privacy_contact_email).lower()),population,data.retention_days,now,now))
        ensure_commercial_account(conn, company_id, population_range=population, starts_on=now[:10], plan_key="pilot")
        record_commercial_event(conn, company_id, actor["id"], "ACCOUNT_CREATED", None, "PILOT", "Initial workplace pilot account created from company demo", at=now)
        conn.execute("UPDATE demo_requests SET status='institution_provisioning',institution_id=?,converted_by=?,converted_at=?,updated_at=? WHERE id=? AND institution_id IS NULL", (company_id,actor["id"],now,now,demo_request_id))
        if conn.execute("SELECT changes()").fetchone()[0] != 1:
            raise HTTPException(409, "This demo request has already been converted")
        _audit(conn, company_id, actor["id"], "WORKPLACE_COMPANY_CREATED_FROM_DEMO")
        _audit(conn, company_id, actor["id"], "WORKPLACE_ADMIN_INVITATION_CREATED")
        conn.commit()
    except HTTPException:
        conn.rollback(); conn.close(); raise
    except Exception:
        conn.rollback(); conn.close()
        raise HTTPException(500, "Unable to configure the workplace company")
    conn.close()
    base = __import__("os").getenv("APP_BASE_URL", "https://app.mindguardai.me").rstrip("/")
    invite_url = f"{base}/invite?token={token}"
    sent, error = send_html_email(admin_email, f"Join {company_name} on MindGuard", f"<p>Hello {data.admin_name},</p><p>You are invited to set up the private workplace wellbeing programme for <strong>{company_name}</strong>.</p><p><a href=\"{invite_url}\">Accept company administrator invitation</a></p><p>This single-use link expires in 7 days.</p>", related_type="workplace_admin_invitation", related_id=admin_id, metadata={"company_id":company_id,"demo_request_id":demo_request_id})
    conn = get_db()
    _audit(conn, company_id, actor["id"], "WORKPLACE_ADMIN_INVITATION_QUEUED" if sent else "WORKPLACE_ADMIN_INVITATION_DELIVERY_FAILED")
    conn.commit(); conn.close()
    write_audit(actor["id"],actor["role_type"],"WORKPLACE_DEMO_CONVERTED","demo_request",demo_request_id,{"company_id":company_id,"admin_id":admin_id,"email_sent":sent},ip=request.client.host if request.client else None)
    from backend.database import get_demo_request
    return {"company":{"id":company_id,"name":company_name,"status":"ACTIVE","readiness":"awaiting_administrator"},"administrator":{"id":admin_id,"name":data.admin_name.strip(),"email":admin_email,"status":"pending"},"demo_request":get_demo_request(demo_request_id),"invitation_sent":sent,"invitation_error":error or None}


@router.get("/admin/companies")
async def list_workplace_companies(actor: dict = Depends(require_auth)):
    if actor.get("role_type") != "admin":
        raise HTTPException(403, "Global administrator access required")
    conn = get_db()
    rows = conn.execute(
        "SELECT i.id, i.name, i.status, s.demo_mode, s.work_email_domains_json, s.legal_review_complete, s.legal_review_reference, s.legal_reviewed_at, s.employee_population_range, s.retention_days, s.policy_status FROM institutions i JOIN workplace_settings s ON s.company_id = i.id WHERE i.type = 'company' ORDER BY i.name COLLATE NOCASE"
    ).fetchall()
    result = []
    for row in rows:
        resolve_commercial_account(conn, row["id"])
        offboarding = sync_offboarding(conn, row["id"])
        active_obligations = conn.execute("SELECT COUNT(*) FROM workplace_support_cases WHERE company_id=? AND status IN ('open','active') AND withdrawn_at IS NULL", (row["id"],)).fetchone()[0]
        ending_providers = conn.execute("SELECT COUNT(*) FROM workplace_providers WHERE company_id=? AND status IN ('ending','ended')", (row["id"],)).fetchone()[0]
        admins = conn.execute("SELECT id,name,email,status FROM users WHERE institution_id=? AND role_type='company_admin' ORDER BY created_at LIMIT 10", (row["id"],)).fetchall()
        result.append({
            "id": row["id"], "name": row["name"], "status": row["status"], "demo_mode": bool(row["demo_mode"]),
            "approved_work_email_domains": json.loads(row["work_email_domains_json"]),
            "legal_review_complete": bool(row["legal_review_complete"]),
            "legal_review_reference": row["legal_review_reference"],
            "legal_reviewed_at": row["legal_reviewed_at"],
            "employee_population_range": row["employee_population_range"],
            "retention_days": row["retention_days"], "policy_status": row["policy_status"],
            "administrators": [dict(admin) for admin in admins],
            "commercial": commercial_summary(conn, row["id"], internal=True),
            "offboarding": ({"status": offboarding["status"], "effective_date": offboarding["effective_date"],
                             "retention_deadline": offboarding["retention_deadline"],
                             "continuity_deadline": offboarding["continuity_deadline"],
                             "active_support_obligations": active_obligations,
                             "provider_relationships_ending_or_ended": ending_providers,
                             "completion_ready": bool(offboarding["status"] == "RETENTION_PERIOD" and not active_obligations and offboarding["retention_deadline"] and offboarding["retention_deadline"] <= _now())} if offboarding else {"status": "NOT_STARTED", "active_support_obligations": active_obligations, "provider_relationships_ending_or_ended": ending_providers, "completion_ready": False}),
        })
    conn.commit()
    conn.close()
    return result


@router.post("/admin/companies/{company_id}/offboarding")
async def advance_workplace_offboarding(company_id: str, data: WorkplaceOffboardingAction, actor: dict = Depends(require_auth)):
    if actor.get("role_type") != "admin":
        raise HTTPException(403, "Global administrator access required")
    conn = get_db()
    conn.execute("BEGIN IMMEDIATE")
    if not conn.execute("SELECT 1 FROM institutions WHERE id=? AND type='company'", (company_id,)).fetchone():
        conn.rollback(); conn.close()
        raise HTTPException(404, "Workplace company not found")
    resolve_commercial_account(conn, company_id)
    state = sync_offboarding(conn, company_id, actor_id=actor["id"])
    if data.action != "complete" or not state:
        conn.rollback(); conn.close()
        raise HTTPException(409, "Schedule cancellation through the commercial lifecycle before progressing offboarding")
    try:
        result = complete_offboarding(conn, company_id, actor_id=actor["id"])
        conn.commit()
    except ValueError as exc:
        conn.rollback(); conn.close()
        raise HTTPException(409, str(exc)) from exc
    conn.close()
    return {"status": result["status"], "completed_at": result["completed_at"]}


@router.get("/admin/commercial")
async def company_commercial_view(user: dict = Depends(require_auth)):
    """Company-scoped, read-only commercial status; internal notes are never returned."""
    company_id = _company_admin(user)
    conn = get_db()
    result = commercial_summary(conn, company_id)
    conn.commit()
    conn.close()
    if not result:
        raise HTTPException(404, "Workplace commercial account not found")
    return result


@router.get("/admin/offboarding-status")
async def company_offboarding_status(user: dict = Depends(require_auth)):
    """Temporary, read-only offboarding status; never returns worker or case data."""
    if user.get("role_type") != "company_admin" or not user.get("institution_id"):
        raise HTTPException(403, "Company administrator access required")
    conn = get_db()
    company = conn.execute("SELECT type,status FROM institutions WHERE id=?", (user["institution_id"],)).fetchone()
    if not company or str(company["type"]).lower() != "company" or str(company["status"]).upper() != "ACTIVE":
        conn.close()
        raise HTTPException(403, "This workplace is unavailable")
    if str(user.get("status") or "").lower() not in {"approved", "active"} or user.get("workplace_terms_version") != WORKPLACE_ADMIN_TERMS_VERSION:
        conn.close()
        raise HTTPException(403, "Active company administrator access is required")
    resolve_commercial_account(conn, user["institution_id"])
    state = sync_offboarding(conn, user["institution_id"])
    commercial = commercial_summary(conn, user["institution_id"])
    conn.commit()
    conn.close()
    if not state:
        return {"status": "NOT_STARTED", "commercial_status": commercial["status"] if commercial else None}
    if state["status"] == "COMPLETED" or (state["retention_deadline"] and state["retention_deadline"] <= _now()):
        raise HTTPException(403, "The workplace read-only access period has ended")
    return {
        "status": state["status"],
        "effective_date": state["effective_date"],
        "retention_deadline": state["retention_deadline"],
        "message": "Your workplace service is scheduled to end. Participation and wellbeing records remain private.",
        "commercial_status": commercial["status"] if commercial else None,
    }


@router.put("/admin/companies/{company_id}/commercial")
async def update_workplace_commercial(company_id: str, data: WorkplaceCommercialUpdate, actor: dict = Depends(require_auth)):
    """MindGuard-only commercial setup and transition endpoint."""
    if actor.get("role_type") != "admin":
        raise HTTPException(403, "Global administrator access required")
    values = data.model_dump(exclude_unset=True)
    if "population_band" in values and values["population_band"] not in POPULATION_BANDS:
        raise HTTPException(400, "Choose a supported workforce population band")
    if "plan_key" in values and values["plan_key"] not in WORKPLACE_PLANS:
        raise HTTPException(400, "Choose a supported workplace plan")
    if "enabled_capabilities" in values:
        caps = values["enabled_capabilities"] or {}
        if set(caps) - COMMERCIAL_CAPABILITIES:
            raise HTTPException(400, "One or more workplace capabilities are not supported")
        if caps.get("voice_support"):
            raise HTTPException(403, "Voice support is not commercially available until separately launch-approved")
    date_fields = ("contract_start_date", "contract_end_date", "renewal_date", "grace_period_end", "cancellation_effective_date")
    for field in date_fields:
        if field in values and values[field] is not None:
            values[field] = values[field].isoformat()
    start_date = values.get("contract_start_date")
    end_date = values.get("contract_end_date")
    if start_date and end_date and date.fromisoformat(end_date) < date.fromisoformat(start_date):
        raise HTTPException(400, "Contract end date must be on or after its start date")
    if "status" in values and values["status"] == "CANCELLED":
        if not values.get("cancellation_effective_date") or not str(values.get("cancellation_reason") or "").strip():
            raise HTTPException(400, "Scheduling cancellation requires an effective date and reason")
    now = _now()
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        company = conn.execute("SELECT i.id,s.demo_mode FROM institutions i JOIN workplace_settings s ON s.company_id=i.id WHERE i.id=? AND lower(i.type)='company'", (company_id,)).fetchone()
        if not company:
            raise HTTPException(404, "Workplace company not found")
        if company["demo_mode"]:
            raise HTTPException(409, "Demo workplaces cannot be converted into or billed as customer tenants")
        ensure_commercial_account(conn, company_id)
        current = resolve_commercial_account(conn, company_id)
        if not current:
            raise HTTPException(404, "Workplace commercial account not found")
        old_status = str(current["status"]).upper()
        new_status = values.get("status")
        reason = str(values.get("reason") or values.get("cancellation_reason") or "").strip() or None
        reference = values.get("internal_reference", None)
        effective_start = values.get("contract_start_date", current.get("contract_start_date"))
        effective_end = values.get("contract_end_date", current.get("contract_end_date"))
        if effective_start and effective_end and date.fromisoformat(str(effective_end)[:10]) < date.fromisoformat(str(effective_start)[:10]):
            raise HTTPException(400, "Contract end date must be on or after its start date")
        if new_status and new_status != old_status and (not reason or len(reason) < 3):
            raise HTTPException(400, "Enter a reason of at least 3 characters for the commercial status transition")
        today = datetime.now(timezone.utc).date()
        period_end = date.fromisoformat(str(effective_end)[:10]) if effective_end else None
        stored_period_end = date.fromisoformat(current["contract_end_date"][:10]) if current.get("contract_end_date") else None
        stored_grace_end = date.fromisoformat(current["grace_period_end"][:10]) if current.get("grace_period_end") else None
        commercially_expired = bool(
            (old_status in {"PILOT", "TRIAL", "ACTIVE"} and stored_period_end and stored_period_end < today)
            or (old_status == "SUSPENDED" and ((stored_period_end and stored_period_end < today) or (stored_grace_end and stored_grace_end < today)))
        )
        if new_status == "ACTIVE" and (old_status == "GRACE_PERIOD" or commercially_expired) and (not period_end or period_end < today):
            raise HTTPException(400, "Reactivation after commercial expiry requires a renewed contract end date")
        # A cancellation can only be reversed before its scheduled effective date.
        if old_status == "CANCELLED" and new_status == "ACTIVE":
            effective = values.get("cancellation_effective_date", current.get("cancellation_effective_date"))
            if effective and date.fromisoformat(str(effective)[:10]) <= datetime.now(timezone.utc).date():
                raise HTTPException(409, "An effective cancellation cannot be reversed; contact MindGuard to review the account")
        if new_status and new_status != old_status:
            transition_commercial_account(conn, company_id, new_status, actor_id=actor["id"], reason=reason, reference=reference, occurred_at=now)

        updates: dict[str, object] = {}
        direct_fields = {
            "plan_key": "plan_key", "contract_start_date": "contract_start_date", "contract_end_date": "contract_end_date",
            "billing_cycle": "billing_cycle", "population_band": "population_band", "renewal_date": "renewal_date",
            "grace_period_end": "grace_period_end", "external_customer_reference": "external_customer_reference",
            "external_subscription_reference": "external_subscription_reference", "billing_provider": "billing_provider",
        }
        for source, target in direct_fields.items():
            if source in values:
                updates[target] = values[source]
        if "enabled_capabilities" in values:
            updates["capabilities_json"] = json.dumps(values["enabled_capabilities"] or {}, sort_keys=True)
        if "internal_reference" in values:
            updates["internal_reference_encrypted"] = encrypt_pii(values["internal_reference"]) if values["internal_reference"] else None
        if "internal_notes" in values:
            updates["internal_notes_encrypted"] = encrypt_pii(values["internal_notes"]) if values["internal_notes"] else None
        if "cancellation_effective_date" in values:
            updates["cancellation_effective_date"] = values["cancellation_effective_date"]
        if "cancellation_reason" in values:
            updates["cancellation_reason_encrypted"] = encrypt_pii(values["cancellation_reason"]) if values["cancellation_reason"] else None
        if new_status == "ACTIVE":
            updates.update({"cancellation_effective_date": None, "cancellation_reason_encrypted": None, "grace_period_end": None})
        if new_status == "TERMINATED":
            updates["terminated_at"] = now
        if new_status == "GRACE_PERIOD" and "grace_period_end" not in updates:
            updates["grace_period_end"] = (datetime.now(timezone.utc).date() + timedelta(days=grace_period_days())).isoformat()
        if updates:
            updates["updated_at"] = now
            assignment_sql = ",".join(f"{column}=?" for column in updates)
            conn.execute(f"UPDATE workplace_commercial_accounts SET {assignment_sql} WHERE company_id=?", (*updates.values(), company_id))

        if new_status == "CANCELLED":
            effective = values.get("cancellation_effective_date", current.get("cancellation_effective_date"))
            if effective:
                schedule_offboarding(conn, company_id, str(effective)[:10], actor_id=actor["id"], reason=reason, reference=reference,
                                     now=datetime.fromisoformat(now))
        elif old_status == "CANCELLED" and new_status == "ACTIVE":
            scheduled = conn.execute("SELECT status FROM workplace_offboarding WHERE company_id=?", (company_id,)).fetchone()
            if scheduled and scheduled["status"] == "SCHEDULED":
                conn.execute("UPDATE workplace_offboarding SET status='NOT_STARTED',effective_date=NULL,updated_at=? WHERE company_id=?", (now, company_id))
                _audit(conn, company_id, actor["id"], "WORKPLACE_OFFBOARDING_CANCELLATION_REVERSED")

        for field, event_type in (("plan_key", "PLAN_CHANGED"), ("renewal_date", "RENEWAL_RECORDED"), ("population_band", "POPULATION_BAND_CHANGED"), ("capabilities_json", "ENTITLEMENTS_CHANGED")):
            if field in updates and updates[field] != current.get(field):
                record_commercial_event(conn, company_id, actor["id"], event_type, old_status, new_status or old_status, reason, reference, now)
        if ("contract_start_date" in updates and updates["contract_start_date"] != current.get("contract_start_date")) or ("contract_end_date" in updates and updates["contract_end_date"] != current.get("contract_end_date")):
            event_type = "PILOT_EXTENDED" if old_status == "PILOT" and current.get("contract_end_date") and updates.get("contract_end_date", current.get("contract_end_date")) != current.get("contract_end_date") else "PILOT_CONFIGURED" if new_status == "PILOT" or old_status == "PILOT" else "CONTRACT_PERIOD_UPDATED"
            record_commercial_event(conn, company_id, actor["id"], event_type, old_status, new_status or old_status, reason, reference, now)
        conn.commit()
    except HTTPException:
        conn.rollback()
        conn.close()
        raise
    except ValueError as exc:
        conn.rollback()
        conn.close()
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:
        conn.rollback()
        conn.close()
        raise HTTPException(409, "Unable to update the workplace commercial account") from exc
    result = commercial_summary(conn, company_id, internal=True)
    conn.commit()
    conn.close()
    return result


@router.post("/admin/companies/{company_id}/administrators/{admin_id}/resend")
async def resend_company_admin_invitation(company_id: str, admin_id: str, actor: dict = Depends(require_auth)):
    if actor.get("role_type") != "admin":
        raise HTTPException(403, "Global administrator access required")
    conn = get_db()
    admin = conn.execute("SELECT id,name,email,status,workplace_invitation_status FROM users WHERE id=? AND institution_id=? AND role_type='company_admin'", (admin_id, company_id)).fetchone()
    if not admin or not conn.execute("SELECT 1 FROM institutions WHERE id=? AND type='company'", (company_id,)).fetchone():
        conn.close(); raise HTTPException(404, "Company administrator not found")
    if str(admin["status"]).lower() in {"approved", "active", "revoked"} or admin["workplace_invitation_status"] == "revoked":
        conn.close(); raise HTTPException(409, "This company administrator has already activated the account")
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    conn.execute("UPDATE users SET invitation_token_hash=?,invitation_expires_at=?,invited_at=?,workplace_invitation_status='pending' WHERE id=?", (hash_token(token),expires,_now(),admin_id))
    now = _now(); _audit(conn, company_id, actor["id"], "WORKPLACE_ADMIN_INVITATION_RESENT"); conn.commit(); conn.close()
    base = __import__("os").getenv("APP_BASE_URL", "https://app.mindguardai.me").rstrip("/")
    sent, error = send_html_email(admin["email"], "Your MindGuard workplace administrator invitation", f"<p>Hello {admin['name']},</p><p>Use this single-use link to activate your company administrator account:</p><p><a href=\"{base}/invite?token={token}\">Accept invitation</a></p><p>The link expires in 7 days.</p>", related_type="workplace_admin_invitation", related_id=admin_id, metadata={"company_id":company_id})
    conn = get_db(); _audit(conn, company_id, actor["id"], "WORKPLACE_ADMIN_INVITATION_QUEUED" if sent else "WORKPLACE_ADMIN_INVITATION_DELIVERY_FAILED"); conn.commit(); conn.close()
    return {"id": admin_id, "status": "pending", "email_sent": sent, "email_error": error or None, "resent_at": now}


@router.post("/admin/companies/{company_id}/legal-review")
async def record_legal_review(
    company_id: str, data: LegalReviewRecord, actor: dict = Depends(require_auth)
):
    if actor.get("role_type") != "admin":
        raise HTTPException(403, "Global administrator access required")
    if not data.reviewed:
        raise HTTPException(
            400,
            "Employee enrollment remains disabled until legal/privacy review is completed",
        )
    conn = get_db()
    company = conn.execute(
        "SELECT i.id,s.demo_mode FROM institutions i JOIN workplace_settings s ON s.company_id=i.id WHERE i.id = ? AND i.type = 'company'", (company_id,)
    ).fetchone()
    if not company:
        conn.close()
        raise HTTPException(404, "Workplace company not found")
    if company["demo_mode"]:
        conn.close()
        raise HTTPException(409, "Demo workplaces cannot record or claim a real privacy review")
    now = _now()
    conn.execute(
        "UPDATE workplace_settings SET legal_review_complete = 1, legal_review_reference = ?, legal_reviewed_by = ?, legal_reviewed_at = ?, updated_at = ? WHERE company_id = ?",
        (data.reference.strip(), actor["id"], now, now, company_id),
    )
    _audit(conn, company_id, actor["id"], "LEGAL_PRIVACY_REVIEW_RECORDED")
    conn.commit()
    conn.close()
    return {"review_recorded": True, "enrollment_enabled": False, "next_required": ["company_privacy_policy", "approved_independent_provider"]}


@router.post("/admin/companies/{company_id}/lifecycle")
async def update_company_lifecycle(company_id: str, data: CompanyLifecycle, actor: dict = Depends(require_auth)):
    if actor.get("role_type") != "admin":
        raise HTTPException(403, "Global administrator access required")
    statuses = {"activate": "ACTIVE", "suspend": "SUSPENDED", "archive": "ARCHIVED"}
    conn = get_db()
    row = conn.execute("SELECT id,status FROM institutions WHERE id=? AND type='company'", (company_id,)).fetchone()
    if not row:
        conn.close(); raise HTTPException(404, "Workplace company not found")
    if str(row["status"]).upper() == "ARCHIVED" and data.action != "archive":
        conn.close(); raise HTTPException(409, "Archived workplace companies cannot be reactivated")
    now = _now()
    conn.execute("UPDATE institutions SET status=? WHERE id=?", (statuses[data.action], company_id))
    if data.action == "archive":
        conn.execute("UPDATE workplace_settings SET archived_at=?, updated_at=? WHERE company_id=?", (now, now, company_id))
        conn.execute("UPDATE workplace_enrollment_links SET revoked_at=COALESCE(revoked_at,?) WHERE company_id=?", (now, company_id))
        conn.execute("UPDATE workplace_providers SET status='inactive' WHERE company_id=?", (company_id,))
    _audit(conn, company_id, actor["id"], f"WORKPLACE_{data.action.upper()}")
    conn.commit(); conn.close()
    write_audit(actor["id"], "admin", f"WORKPLACE_{data.action.upper()}", "institution", company_id, {"reason": data.reason})
    return {"id": company_id, "status": statuses[data.action]}


@router.get("/admin/setup")
async def workplace_setup(user: dict = Depends(require_auth)):
    company_id = _company_admin(user)
    conn = get_db()
    company = conn.execute("SELECT i.name,i.status,s.* FROM institutions i JOIN workplace_settings s ON s.company_id=i.id WHERE i.id=?", (company_id,)).fetchone()
    admins = conn.execute("SELECT id,name,email,status,workplace_admin_role,workplace_invitation_status,invitation_expires_at FROM users WHERE institution_id=? AND role_type='company_admin' ORDER BY CASE WHEN workplace_admin_role='owner' THEN 0 ELSE 1 END,name", (company_id,)).fetchall()
    providers = conn.execute("SELECT COUNT(*) AS n FROM workplace_providers p JOIN workplace_provider_credentials c ON c.provider_id=p.provider_id AND c.status='verified' JOIN users u ON u.id=p.provider_id LEFT JOIN workplace_provider_operations po ON po.provider_id=p.provider_id WHERE p.company_id=? AND p.status='active' AND u.status IN ('approved','active') AND COALESCE(po.access_status,'active')='active' AND (c.valid_from IS NULL OR c.valid_from<=date('now')) AND (c.expires_at IS NULL OR c.expires_at>=date('now'))", (company_id,)).fetchone()["n"]
    links = conn.execute("SELECT COUNT(*) AS n FROM workplace_enrollment_links WHERE company_id=? AND revoked_at IS NULL AND (expires_at IS NULL OR expires_at>?)", (company_id, _now())).fetchone()["n"]
    commercial = commercial_summary(conn, company_id)
    conn.commit()
    conn.close()
    active_admins = sum(1 for row in admins if str(row["status"]).lower() in {"approved", "active"})
    checks = {
        "administrator": active_admins > 0,
        "workplace_terms": user.get("workplace_terms_version") == WORKPLACE_ADMIN_TERMS_VERSION,
        "company_profile": bool(company["name"]),
        "domains": bool(json.loads(company["work_email_domains_json"] or "[]")),
        "privacy_contact": bool(company["privacy_contact_encrypted"]),
        "privacy_review": bool(company["legal_review_complete"]),
        "policy": company["policy_status"] == "approved",
        "provider": providers > 0,
        "enrollment_link": links > 0,
    }
    if company["status"] == "SUSPENDED": readiness = "suspended"
    elif company["status"] == "ARCHIVED": readiness = "archived"
    elif company["demo_mode"]: readiness = "demo_ready" if links else "demo_enrollment"
    elif not checks["administrator"]: readiness = "awaiting_administrator"
    elif not checks["privacy_review"]: readiness = "privacy_review_required"
    elif not checks["policy"] or not checks["provider"]: readiness = "provider_setup"
    elif not checks["enrollment_link"]: readiness = "enrollment_setup"
    else: readiness = "ready"
    return {
        "company": {"id": company_id, "name": company["name"], "status": company["status"], "demo_mode": bool(company["demo_mode"])},
        "demo_mode": bool(company["demo_mode"]),
        "commercial": commercial,
        "readiness": readiness,
        "checklist": checks,
        "current_admin_role": user.get("workplace_admin_role") or "admin",
        "workplace_terms_version": WORKPLACE_ADMIN_TERMS_VERSION,
        "administrators": [{**dict(row), "invitation_state": _admin_invitation_state(row)} for row in admins],
        "approved_domains": json.loads(company["work_email_domains_json"] or "[]"),
        "operational_provider_count": providers,
        "active_enrollment_link_count": links,
        "policy": {"privacy_notice_version": company["privacy_notice_version"], "privacy_contact_email": decrypt_pii(company["privacy_contact_encrypted"]) if company["privacy_contact_encrypted"] else "", "employee_population_range": company["employee_population_range"], "retention_days": company["retention_days"], "status": company["policy_status"]},
    }


@router.get("/admin/domains")
async def get_workplace_domains(user: dict = Depends(require_auth)):
    company_id = _company_admin(user)
    conn = get_db()
    row = conn.execute("SELECT work_email_domains_json FROM workplace_settings WHERE company_id=?", (company_id,)).fetchone()
    conn.close()
    return {"domains": json.loads(row["work_email_domains_json"] or "[]") if row else []}


@router.post("/admin/domains", status_code=201)
async def add_workplace_domain(data: WorkplaceDomain, user: dict = Depends(require_auth)):
    company_id = _company_admin(user, owner=True)
    domain = _normalize_domains([data.domain])[0]
    conn = get_db(); conn.execute("BEGIN IMMEDIATE")
    _assert_owner_in_transaction(conn, company_id, user["id"])
    if _is_demo_company(conn, company_id):
        conn.rollback(); conn.close()
        raise HTTPException(409, "Demo workplaces do not require company email domains")
    row = conn.execute("SELECT work_email_domains_json FROM workplace_settings WHERE company_id=?", (company_id,)).fetchone()
    domains = sorted({str(d).lower().lstrip("@") for d in json.loads(row["work_email_domains_json"] or "[]")})
    if domain in domains:
        conn.rollback(); conn.close()
        raise HTTPException(409, "This domain is already approved")
    domains.append(domain); domains.sort()
    conn.execute("UPDATE workplace_settings SET work_email_domains_json=?,updated_at=? WHERE company_id=?", (json.dumps(domains), _now(), company_id))
    _audit(conn, company_id, user["id"], "WORKPLACE_DOMAIN_ADDED")
    conn.commit(); conn.close()
    return {"domains": domains}


@router.delete("/admin/domains")
async def remove_workplace_domain(data: WorkplaceDomain, user: dict = Depends(require_auth)):
    company_id = _company_admin(user, owner=True)
    domain = _normalize_domains([data.domain])[0]
    conn = get_db(); conn.execute("BEGIN IMMEDIATE")
    _assert_owner_in_transaction(conn, company_id, user["id"])
    if _is_demo_company(conn, company_id):
        conn.rollback(); conn.close()
        raise HTTPException(409, "Demo workplaces do not use company email domains")
    row = conn.execute("SELECT work_email_domains_json FROM workplace_settings WHERE company_id=?", (company_id,)).fetchone()
    domains = sorted({str(d).lower().lstrip("@") for d in json.loads(row["work_email_domains_json"] or "[]")})
    if domain not in domains:
        conn.rollback(); conn.close()
        raise HTTPException(404, "Approved domain not found")
    if len(domains) == 1:
        conn.rollback(); conn.close()
        raise HTTPException(409, "At least one approved domain must remain for future enrollment")
    domains.remove(domain)
    conn.execute("UPDATE workplace_settings SET work_email_domains_json=?,updated_at=? WHERE company_id=?", (json.dumps(domains), _now(), company_id))
    _audit(conn, company_id, user["id"], "WORKPLACE_DOMAIN_REMOVED")
    conn.commit(); conn.close()
    return {"domains": domains, "future_enrollment_only": True}


@router.put("/admin/policy")
async def update_company_policy(data: CompanyPolicyUpdate, user: dict = Depends(require_auth)):
    company_id = _company_admin(user)
    conn = get_db()
    if _is_demo_company(conn, company_id):
        conn.close()
        raise HTTPException(409, "Demo workplace settings are synthetic and cannot be approved as a customer policy")
    conn.close()
    if not data.confirm_aggregate_only:
        raise HTTPException(400, "Confirm that employer reporting remains aggregate-only")
    conn = get_db(); now = _now()
    conn.execute("UPDATE workplace_settings SET privacy_contact_encrypted=?,employee_population_range=?,retention_days=?,privacy_notice_version=?,policy_status='approved',updated_at=? WHERE company_id=?", (encrypt_pii(str(data.privacy_contact_email).lower()), data.employee_population_range, data.retention_days, data.privacy_notice_version, now, company_id))
    _audit(conn, company_id, user["id"], "WORKPLACE_POLICY_APPROVED")
    conn.commit(); conn.close()
    return {"ok": True, "status": "approved"}


@router.post("/admin/administrators", status_code=201)
async def invite_company_administrator(data: CompanyAdminInvite, user: dict = Depends(require_auth)):
    company_id = _company_admin(user)
    email = str(data.email).lower()
    conn = get_db()
    if not commercial_can_use(conn, company_id, "administrator_management"):
        conn.commit(); conn.close()
        raise HTTPException(403, "Administrator changes are unavailable for this workplace commercial status")
    account = resolve_commercial_account(conn, company_id)
    administrator_limit = commercial_plan_limit(account, "administrator_limit") if account else 0
    active_administrator_count = conn.execute("SELECT COUNT(*) AS n FROM users WHERE institution_id=? AND role_type='company_admin' AND status IN ('approved','active','pending','invited')", (company_id,)).fetchone()["n"]
    if administrator_limit is not None and active_administrator_count >= administrator_limit:
        conn.close()
        raise HTTPException(409, "This workplace plan has reached its administrator limit")
    settings = conn.execute("SELECT work_email_domains_json FROM workplace_settings WHERE company_id=?", (company_id,)).fetchone()
    existing = conn.execute("SELECT id FROM users WHERE lower(email)=?", (email,)).fetchone()
    conn.close()
    domains = json.loads(settings["work_email_domains_json"])
    if email.rsplit("@", 1)[-1] not in domains:
        raise HTTPException(400, "Administrator must use an approved company email domain")
    if existing:
        raise HTTPException(409, "An account already exists for this email")
    token = secrets.token_urlsafe(32)
    now = _now(); expires = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    from backend.database import _make_referral_code
    staff_id = str(uuid.uuid4())
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        if not commercial_can_use(conn, company_id, "administrator_management"):
            raise HTTPException(403, "Administrator changes are unavailable for this workplace commercial status")
        current_account = resolve_commercial_account(conn, company_id)
        current_limit = commercial_plan_limit(current_account, "administrator_limit") if current_account else 0
        current_count = conn.execute("SELECT COUNT(*) AS n FROM users WHERE institution_id=? AND role_type='company_admin' AND status IN ('approved','active','pending','invited')", (company_id,)).fetchone()["n"]
        if current_limit is not None and current_count >= current_limit:
            raise HTTPException(409, "This workplace plan has reached its administrator limit")
        if conn.execute("SELECT 1 FROM users WHERE lower(email)=?", (email,)).fetchone():
            raise HTTPException(409, "An account already exists for this email")
        referral_code = _make_referral_code()
        conn.execute("INSERT INTO users (id,email,name,role_type,password_hash,status,created_at,referral_code,institution_id,user_category,invitation_token_hash,invitation_expires_at,invited_at,workplace_admin_role,workplace_invitation_status) VALUES (?,?,?,'company_admin',?,'pending',?,?,?,?,?,?,?,?,?)", (staff_id,email,data.name.strip(),hash_password(secrets.token_urlsafe(32)),now,referral_code,company_id,'company_staff',hash_token(token),expires,now,'admin','pending'))
        _audit(conn, company_id, user["id"], "WORKPLACE_ADMIN_INVITED")
        conn.commit()
    except HTTPException:
        conn.rollback(); conn.close(); raise
    except Exception:
        conn.rollback(); conn.close(); raise HTTPException(409, "Unable to create this administrator invitation")
    conn.close()
    base = __import__("os").getenv("APP_BASE_URL", "https://app.mindguardai.me").rstrip("/")
    sent, error = send_html_email(email, "Join your MindGuard workplace programme", f"<p>Hello {data.name},</p><p>You have been invited as a company administrator.</p><p><a href=\"{base}/invite?token={token}\">Accept invitation</a></p><p>The link expires in 7 days.</p>", related_type="workplace_admin_invitation", related_id=staff_id, metadata={"company_id":company_id})
    conn = get_db(); _audit(conn, company_id, user["id"], "WORKPLACE_ADMIN_INVITATION_QUEUED" if sent else "WORKPLACE_ADMIN_INVITATION_DELIVERY_FAILED"); conn.commit(); conn.close()
    return {"id": staff_id, "name": data.name, "email": email, "status": "pending", "invitation_state": "pending", "email_sent": sent, "email_error": error or None}


@router.post("/admin/administrators/{admin_id}/resend")
async def resend_workplace_admin_invitation(admin_id: str, user: dict = Depends(require_auth)):
    company_id = _company_admin(user)
    conn = get_db(); conn.execute("BEGIN IMMEDIATE")
    admin = conn.execute("SELECT id,name,email,status FROM users WHERE id=? AND institution_id=? AND role_type='company_admin'", (admin_id, company_id)).fetchone()
    if not admin or str(admin["status"]).lower() not in {"pending", "invited"}:
        conn.rollback(); conn.close()
        raise HTTPException(404, "Pending administrator invitation not found")
    token = secrets.token_urlsafe(32); now = _now(); expires = (datetime.now(timezone.utc)+timedelta(days=7)).isoformat()
    conn.execute("UPDATE users SET invitation_token_hash=?,invitation_expires_at=?,invited_at=?,workplace_invitation_status='pending' WHERE id=?", (hash_token(token),expires,now,admin_id))
    _audit(conn, company_id, user["id"], "WORKPLACE_ADMIN_INVITATION_RESENT")
    conn.commit(); conn.close()
    base = __import__("os").getenv("APP_BASE_URL", "https://app.mindguardai.me").rstrip("/")
    sent,error = send_html_email(admin["email"], "Your MindGuard workplace administrator invitation", f"<p>Hello {admin['name']},</p><p>Use this single-use link to activate your company administrator account:</p><p><a href=\"{base}/invite?token={token}\">Accept invitation</a></p><p>The link expires in 7 days.</p>", related_type="workplace_admin_invitation", related_id=admin_id, metadata={"company_id":company_id})
    conn = get_db(); _audit(conn, company_id, user["id"], "WORKPLACE_ADMIN_INVITATION_QUEUED" if sent else "WORKPLACE_ADMIN_INVITATION_DELIVERY_FAILED"); conn.commit(); conn.close()
    return {"id":admin_id,"status":"pending","invitation_state":"pending","email_sent":sent,"email_error":error or None}


@router.delete("/admin/administrators/{admin_id}")
async def revoke_or_remove_workplace_admin(admin_id: str, user: dict = Depends(require_auth)):
    company_id = _company_admin(user, owner=True)
    if admin_id == user["id"]:
        raise HTTPException(409, "Transfer ownership before leaving the company administrator role")
    conn = get_db(); conn.execute("BEGIN IMMEDIATE")
    _assert_owner_in_transaction(conn, company_id, user["id"])
    target = conn.execute("SELECT id,status,workplace_admin_role FROM users WHERE id=? AND institution_id=? AND role_type='company_admin'", (admin_id, company_id)).fetchone()
    if not target:
        conn.rollback(); conn.close(); raise HTTPException(404, "Company administrator not found")
    if target["workplace_admin_role"] == "owner":
        conn.rollback(); conn.close(); raise HTTPException(409, "Transfer ownership before removing the owner")
    pending = str(target["status"]).lower() in {"pending", "invited"}
    conn.execute("UPDATE users SET status='revoked',workplace_invitation_status='revoked',invitation_token_hash=NULL,invitation_expires_at=NULL,workplace_admin_role='admin' WHERE id=?", (admin_id,))
    _audit(conn, company_id, user["id"], "WORKPLACE_ADMIN_INVITATION_REVOKED" if pending else "WORKPLACE_ADMIN_REMOVED")
    conn.commit(); conn.close()
    return {"removed":not pending,"invitation_revoked":pending}


@router.post("/admin/ownership/transfer")
async def transfer_workplace_ownership(data: WorkplaceOwnershipTransfer, user: dict = Depends(require_auth)):
    company_id = _company_admin(user, owner=True)
    conn = get_db(); conn.execute("BEGIN IMMEDIATE")
    _assert_owner_in_transaction(conn, company_id, user["id"])
    target = conn.execute("SELECT id,status FROM users WHERE id=? AND institution_id=? AND role_type='company_admin'", (data.administrator_id, company_id)).fetchone()
    if not target or str(target["status"]).lower() not in {"approved","active"}:
        conn.rollback(); conn.close(); raise HTTPException(404, "Active company administrator not found")
    if target["id"] == user["id"]:
        conn.rollback(); conn.close(); raise HTTPException(400, "You are already the company owner")
    conn.execute("UPDATE users SET workplace_admin_role='admin' WHERE id=? AND institution_id=? AND workplace_admin_role='owner'", (user["id"], company_id))
    conn.execute("UPDATE users SET workplace_admin_role='owner' WHERE id=?", (target["id"],))
    _audit(conn, company_id, user["id"], "WORKPLACE_OWNERSHIP_TRANSFERRED")
    conn.commit(); conn.close()
    return {"owner_id":target["id"]}


@router.get("/admin/audit")
async def workplace_audit(user: dict = Depends(require_auth)):
    company_id = _company_admin(user)
    # Employee and provider actions must not be enumerable by the employer:
    # even actor IDs or event counts could reveal who opted in or requested care.
    administrative_events = (
        "WORKPLACE_COMPANY_CREATED",
        "WORKPLACE_COMPANY_CREATED_FROM_DEMO",
        "WORKPLACE_ADMIN_INVITATION_CREATED",
        "WORKPLACE_ADMIN_INVITATION_QUEUED",
        "WORKPLACE_ADMIN_INVITATION_DELIVERY_FAILED",
        "WORKPLACE_ADMIN_INVITATION_RESENT",
        "WORKPLACE_ADMIN_INVITATION_REVOKED",
        "WORKPLACE_ADMIN_ACTIVATED",
        "WORKPLACE_ADMIN_REMOVED",
        "WORKPLACE_OWNERSHIP_TRANSFERRED",
        "WORKPLACE_ADMIN_TERMS_ACCEPTED",
        "WORKPLACE_DOMAIN_ADDED",
        "WORKPLACE_DOMAIN_REMOVED",
        "LEGAL_PRIVACY_REVIEW_RECORDED",
        "WORKPLACE_ACTIVATE",
        "WORKPLACE_SUSPEND",
        "WORKPLACE_ARCHIVE",
        "WORKPLACE_POLICY_APPROVED",
        "WORKPLACE_ADMIN_INVITED",
        "ENROLLMENT_LINK_CREATED",
        "ENROLLMENT_LINK_REVOKED",
        "WORKPLACE_PROVIDER_ATTACHED",
        "WORKPLACE_PROVIDER_DEACTIVATED",
    )
    conn = get_db()
    placeholders = ",".join("?" for _ in administrative_events)
    rows = conn.execute(
        f"SELECT event_type, occurred_at FROM workplace_audit_events "
        f"WHERE company_id=? AND event_type IN ({placeholders}) "
        "ORDER BY occurred_at DESC LIMIT 200",
        (company_id, *administrative_events),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


@router.post("/admin/provider-credentials", status_code=201)
async def provision_workplace_provider(
    data: ProviderCredentialCreate, actor: dict = Depends(require_auth)
):
    """Record a human-verified professional credential before enabling provider access."""
    if actor.get("role_type") != "admin":
        raise HTTPException(403, "Global administrator access required")
    _validate_credential_period(data.valid_from, data.expires_at)
    conn = get_db()
    provider = conn.execute(
        "SELECT * FROM users WHERE email = ? AND role_type = 'student' AND user_category = 'adult' AND institution_id IS NULL AND status IN ('approved','active')",
        (str(data.provider_email).lower(),),
    ).fetchone()
    if not provider:
        conn.close()
        raise HTTPException(
            400,
            "Provider must have an existing active independent adult account and no school/staff assignment",
        )
    now = _now()
    try:
        conn.execute(
            "INSERT INTO workplace_provider_credentials (provider_id, professional_type, title_encrypted, qualification_encrypted, registration_encrypted, verification_reference_encrypted, status, reviewed_by, reviewed_at, valid_from, expires_at, license_state_encrypted, demo_only) VALUES (?,?,?,?,?,?,'verified',?,?,?,?,?,0)",
            (
                provider["id"],
                encrypt_pii(data.professional_type.strip()) if data.professional_type else None,
                encrypt_pii(data.professional_title.strip()),
                encrypt_pii(data.qualification.strip()),
                encrypt_pii(data.registration_number.strip()),
                encrypt_pii(data.verification_reference.strip()),
                actor["id"],
                now,
                data.valid_from,
                data.expires_at,
                encrypt_pii(data.license_state.strip()),
            ),
        )
        conn.execute(
            "INSERT INTO workplace_provider_operations (provider_id,access_status,availability,changed_by,changed_at) VALUES (?,'active','available',?,?)",
            (provider["id"], actor["id"], now),
        )
        conn.execute(
            "INSERT INTO workplace_provider_credential_history (id,provider_id,professional_type_encrypted,title_encrypted,qualification_encrypted,registration_encrypted,verification_reference_encrypted,status,submitted_at,reviewed_by,reviewed_at,valid_from,expires_at,license_state_encrypted) VALUES (?,?,?,?,?,?,?,'verified',?,?,?,?,?,?)",
            (str(uuid.uuid4()), provider["id"], encrypt_pii(data.professional_type.strip()) if data.professional_type else None, encrypt_pii(data.professional_title.strip()), encrypt_pii(data.qualification.strip()), encrypt_pii(data.registration_number.strip()), encrypt_pii(data.verification_reference.strip()), now, actor["id"], now, data.valid_from, data.expires_at, encrypt_pii(data.license_state.strip())),
        )
        conn.execute(
            "UPDATE users SET role_type = 'workplace_provider', user_category = 'workplace_provider', professional_title = ?, terms_accepted_at = NULL WHERE id = ?",
            (encrypt_pii(data.professional_title.strip()), provider["id"]),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise HTTPException(
            409,
            "A provider credential record already exists; use the credential review process",
        )
    conn.close()
    write_audit(
        actor["id"],
        "admin",
        "WORKPLACE_PROVIDER_CREDENTIAL_VERIFIED",
        "user",
        provider["id"],
        {"registration_reference_recorded": True},
    )
    return {
        "provider_enabled": True,
        "credential_status": "verified",
        "expires_at": data.expires_at,
        "email": str(data.provider_email).lower(),
        "credential_reviewed_by": actor["id"],
        "reviewed_at": now,
            "note": "The entered reference records a human review; this endpoint does not validate a state licensing board automatically.",
    }


@router.post("/admin/provider-accounts", status_code=201)
async def create_workplace_provider_account(
    data: WorkplaceProviderAccountCreate, actor: dict = Depends(require_auth)
):
    """Create a new independent workplace-provider account and invite its owner."""
    if actor.get("role_type") != "admin":
        raise HTTPException(403, "Global administrator access required")
    _validate_credential_period(data.valid_from, data.expires_at)
    from backend.database import _make_referral_code

    provider_id = str(uuid.uuid4())
    email = str(data.provider_email).strip().lower()
    now = _now()
    invite_token = secrets.token_urlsafe(32)
    invite_expires = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM users WHERE lower(email)=?", (email,)).fetchone():
            raise HTTPException(
                409,
                "This email already has a MindGuard account. Existing accounts are not converted; use an unused email for a new independent provider.",
            )
        referral_code = _make_referral_code()
        while conn.execute("SELECT 1 FROM users WHERE referral_code=?", (referral_code,)).fetchone():
            referral_code = _make_referral_code()
        conn.execute(
            "INSERT INTO users (id,email,name,role_type,password_hash,status,created_at,referral_code,institution_id,user_category,onboarding_completed_at,professional_title,invitation_token_hash,invitation_expires_at,invited_at,workplace_invitation_status,terms_accepted_at) "
            "VALUES (?,?,?,'workplace_provider',?,'pending',?,?,NULL,'workplace_provider',NULL,?,?,?,?,'pending',NULL)",
            (
                provider_id,
                email,
                data.full_name.strip(),
                hash_password(secrets.token_urlsafe(32)),
                now,
                referral_code,
                encrypt_pii(data.professional_title.strip()),
                hash_token(invite_token),
                invite_expires,
                now,
            ),
        )
        conn.execute(
            "INSERT INTO workplace_provider_credentials (provider_id,professional_type,title_encrypted,qualification_encrypted,registration_encrypted,verification_reference_encrypted,status,reviewed_by,reviewed_at,valid_from,expires_at,license_state_encrypted,demo_only) "
            "VALUES (?,?,?,?,?,?,'verified',?,?,?,?,?,0)",
            (
                provider_id,
                encrypt_pii(data.professional_type.strip()) if data.professional_type else None,
                encrypt_pii(data.professional_title.strip()),
                encrypt_pii(data.qualification.strip()),
                encrypt_pii(data.registration_number.strip()),
                encrypt_pii(data.verification_reference.strip()),
                actor["id"],
                now,
                data.valid_from,
                data.expires_at,
                encrypt_pii(data.license_state.strip()),
            ),
        )
        conn.execute(
            "INSERT INTO workplace_provider_operations (provider_id,access_status,availability,changed_by,changed_at) VALUES (?,'active','available',?,?)",
            (provider_id, actor["id"], now),
        )
        conn.execute(
            "INSERT INTO workplace_provider_credential_history (id,provider_id,professional_type_encrypted,title_encrypted,qualification_encrypted,registration_encrypted,verification_reference_encrypted,status,submitted_at,reviewed_by,reviewed_at,valid_from,expires_at,license_state_encrypted) "
            "VALUES (?,?,?,?,?,?,?,'verified',?,?,?,?,?,?)",
            (
                str(uuid.uuid4()),
                provider_id,
                encrypt_pii(data.professional_type.strip()) if data.professional_type else None,
                encrypt_pii(data.professional_title.strip()),
                encrypt_pii(data.qualification.strip()),
                encrypt_pii(data.registration_number.strip()),
                encrypt_pii(data.verification_reference.strip()),
                now,
                actor["id"],
                now,
                data.valid_from,
                data.expires_at,
                encrypt_pii(data.license_state.strip()),
            ),
        )
        conn.commit()
    except HTTPException:
        conn.rollback()
        conn.close()
        raise
    except Exception as exc:
        conn.rollback()
        conn.close()
        logger.exception(
            "Unable to create independent workplace provider account (provider_id=%s)",
            provider_id,
        )
        raise HTTPException(500, "Unable to create independent provider account. Please try again or contact MindGuard support.") from exc
    conn.close()

    base = __import__("os").getenv("APP_BASE_URL", "https://app.mindguardai.me").rstrip("/")
    safe_name = html.escape(data.full_name.strip())
    sent, error = send_html_email(
        email,
        "Your MindGuard independent provider account",
        f"<p>Hello {safe_name},</p><p>A MindGuard operations administrator created an independent provider account for you after recording a human review of your professional license.</p><p>Accept the invitation and set your password to access the workplace provider workspace:</p><p><a href=\"{base}/invite?token={invite_token}\">Accept provider invitation</a></p><p>This single-use link expires in 7 days. You can only see workplace cases that an employee explicitly shares with you.</p>",
        related_type="workplace_provider_invitation",
        related_id=provider_id,
        metadata={"provider_id": provider_id, "credential_reviewed": True},
    )
    write_audit(
        actor["id"],
        "admin",
        "WORKPLACE_PROVIDER_ACCOUNT_CREATED",
        "user",
        provider_id,
        {"credential_reviewed": True, "invitation_sent": bool(sent)},
    )
    return {
        "id": provider_id,
        "email": email,
        "account_status": "pending",
        "credential_status": "verified",
        "invitation_pending": True,
        "invitation_sent": sent,
        "invitation_error": error or None,
    }


@router.post("/admin/provider-accounts/{provider_id}/resend")
async def resend_workplace_provider_invitation(
    provider_id: str, actor: dict = Depends(require_auth)
):
    if actor.get("role_type") != "admin":
        raise HTTPException(403, "Global administrator access required")
    conn = get_db()
    provider = conn.execute(
        "SELECT id,name,email,status FROM users WHERE id=? AND role_type='workplace_provider' AND EXISTS (SELECT 1 FROM workplace_provider_credentials WHERE provider_id=users.id AND demo_only=0)",
        (provider_id,),
    ).fetchone()
    if not provider:
        conn.close()
        raise HTTPException(404, "Independent workplace provider not found")
    if str(provider["status"]).lower() not in {"pending", "invited"}:
        conn.close()
        raise HTTPException(409, "This provider has already accepted the invitation")
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    now = _now()
    conn.execute(
        "UPDATE users SET invitation_token_hash=?,invitation_expires_at=?,invited_at=?,workplace_invitation_status='pending' WHERE id=?",
        (hash_token(token), expires, now, provider_id),
    )
    conn.commit()
    conn.close()
    base = __import__("os").getenv("APP_BASE_URL", "https://app.mindguardai.me").rstrip("/")
    safe_name = html.escape(provider["name"])
    sent, error = send_html_email(
        provider["email"],
        "Your MindGuard independent provider invitation",
        f"<p>Hello {safe_name},</p><p>Use this single-use link to activate your independent provider account:</p><p><a href=\"{base}/invite?token={token}\">Accept provider invitation</a></p><p>The link expires in 7 days.</p>",
        related_type="workplace_provider_invitation",
        related_id=provider_id,
        metadata={"provider_id": provider_id},
    )
    write_audit(
        actor["id"],
        "admin",
        "WORKPLACE_PROVIDER_INVITATION_RESENT" if sent else "WORKPLACE_PROVIDER_INVITATION_DELIVERY_FAILED",
        "user",
        provider_id,
        {"invitation_sent": bool(sent)},
    )
    return {"id": provider_id, "invitation_pending": True, "invitation_sent": sent, "invitation_error": error or None}


@router.get("/provider/status")
async def workplace_provider_status(user: dict = Depends(require_auth)):
    if user.get("role_type") != "workplace_provider":
        raise HTTPException(403, "Workplace provider access required")
    conn = get_db()
    live_user = conn.execute("SELECT status FROM users WHERE id=? AND role_type='workplace_provider'", (user["id"],)).fetchone()
    credential = _provider_credential_state(conn, user["id"])
    if not credential:
        conn.close()
        raise HTTPException(404, "Provider credential record not found")
    conn.execute(
        "INSERT OR IGNORE INTO workplace_provider_operations (provider_id,access_status,availability,changed_at) VALUES (?,'active','available',?)",
        (user["id"], _now()),
    )
    counts = conn.execute(
        "SELECT SUM(CASE WHEN status IN ('open','active') AND assignment_status='assigned' THEN 1 ELSE 0 END) AS active_cases, "
        "SUM(CASE WHEN status IN ('open','active') AND assignment_status='reassignment_required' THEN 1 ELSE 0 END) AS action_required "
        "FROM workplace_support_cases WHERE provider_id=?",
        (user["id"],),
    ).fetchone()
    pending_review = conn.execute(
        "SELECT 1 FROM workplace_provider_credential_history WHERE provider_id=? AND status='pending_review' LIMIT 1",
        (user["id"],),
    ).fetchone()
    connected_workplaces = conn.execute(
        "SELECT COUNT(*) AS n FROM workplace_providers p JOIN institutions i ON i.id=p.company_id "
        "WHERE p.provider_id=? AND p.status='active' AND i.type='company' AND i.status='ACTIVE'",
        (user["id"],),
    ).fetchone()["n"]
    conn.commit()
    conn.close()
    return {
        "credential_status": credential["status"],
        "reverification_pending": bool(pending_review),
        "credential_valid": credential["credential_valid"],
        "valid_from": credential["valid_from"],
        "expires_at": credential["expires_at"],
        "access_status": credential["access_status"],
        "account_status": str(live_user["status"]).lower() if live_user else "unavailable",
        "availability": credential["availability"],
        "active_case_count": int(counts["active_cases"] or 0),
        "action_required_count": int(counts["action_required"] or 0),
        "connected_workplace_count": int(connected_workplaces or 0),
        "can_receive_new_cases": bool(live_user and str(live_user["status"]).lower() in {"approved", "active"}) and credential["credential_valid"] and credential["access_status"] == "active" and credential["availability"] == "available",
    }


@router.post("/provider/availability")
async def set_provider_availability(data: ProviderAvailability, user: dict = Depends(require_auth)):
    if user.get("role_type") != "workplace_provider" or str(user.get("status") or "").lower() not in {"approved", "active"}:
        raise HTTPException(403, "Active workplace provider access required")
    conn = get_db()
    credential = _provider_credential_state(conn, user["id"])
    if not credential or not credential["credential_valid"] or credential["access_status"] != "active":
        conn.close()
        raise HTTPException(403, "A current verified credential and active provider account are required")
    now = _now()
    conn.execute(
        "INSERT INTO workplace_provider_operations (provider_id,access_status,availability,changed_by,changed_at) VALUES (?,'active',?,?,?) "
        "ON CONFLICT(provider_id) DO UPDATE SET availability=excluded.availability,changed_at=excluded.changed_at",
        (user["id"], data.availability, user["id"], now),
    )
    associated = conn.execute("SELECT DISTINCT company_id FROM workplace_providers WHERE provider_id=?", (user["id"],)).fetchall()
    for row in associated:
        _audit(conn, row["company_id"], None, "WORKPLACE_PROVIDER_AVAILABILITY_CHANGED")
    conn.commit()
    conn.close()
    return {"availability": data.availability}


@router.post("/provider/credentials/reverification", status_code=201)
async def submit_provider_reverification(data: ProviderCredentialSubmission, user: dict = Depends(require_auth)):
    if user.get("role_type") != "workplace_provider":
        raise HTTPException(403, "Workplace provider access required")
    now = _now()
    conn = get_db()
    conn.execute(
        "INSERT INTO workplace_provider_credential_history (id,provider_id,professional_type_encrypted,title_encrypted,qualification_encrypted,registration_encrypted,license_state_encrypted,status,submitted_at) VALUES (?,?,?,?,?,?,?,'pending_review',?)",
        (str(uuid.uuid4()), user["id"], encrypt_pii(data.professional_type.strip()) if data.professional_type else None, encrypt_pii(data.professional_title.strip()), encrypt_pii(data.qualification.strip()), encrypt_pii(data.registration_number.strip()), encrypt_pii(data.license_state.strip()) if data.license_state else None, now),
    )
    for row in conn.execute("SELECT DISTINCT company_id FROM workplace_providers WHERE provider_id=?", (user["id"],)).fetchall():
        _audit(conn, row["company_id"], None, "WORKPLACE_PROVIDER_CREDENTIAL_SUBMITTED")
    conn.commit()
    conn.close()
    return {"submitted": True, "credential_review_status": "pending_review", "submitted_at": now}


@router.post("/provider/departure")
async def provider_departure(user: dict = Depends(require_auth)):
    if user.get("role_type") != "workplace_provider":
        raise HTTPException(403, "Workplace provider access required")
    now = _now()
    conn = get_db()
    conn.execute(
        "INSERT INTO workplace_provider_operations (provider_id,access_status,availability,reason_encrypted,changed_by,changed_at) VALUES (?,'deactivated','unavailable',?,?,?) "
        "ON CONFLICT(provider_id) DO UPDATE SET access_status='deactivated',availability='unavailable',reason_encrypted=excluded.reason_encrypted,changed_by=excluded.changed_by,changed_at=excluded.changed_at",
        (user["id"], encrypt_pii("Provider departure"), user["id"], now),
    )
    conn.execute("UPDATE workplace_providers SET status='inactive' WHERE provider_id=? AND status='active'", (user["id"],))
    _mark_provider_cases_for_reassignment(conn, user["id"], "provider_departure")
    for row in conn.execute("SELECT DISTINCT company_id FROM workplace_providers WHERE provider_id=?", (user["id"],)).fetchall():
        _audit(conn, row["company_id"], None, "WORKPLACE_PROVIDER_DEACTIVATED")
    conn.commit()
    conn.close()
    return {"deactivated": True, "active_cases_require_worker_reassignment": True}


@router.get("/admin/provider-operations")
async def admin_provider_operations(actor: dict = Depends(require_auth)):
    if actor.get("role_type") != "admin":
        raise HTTPException(403, "Global administrator access required")
    conn = get_db()
    rows = conn.execute(
        "SELECT u.id,u.name,u.email,u.status AS account_status,u.invitation_token_hash,u.invitation_expires_at,pc.*,COALESCE(po.access_status,'active') AS access_status, "
        "COALESCE(po.availability,'available') AS availability FROM users u "
        "JOIN workplace_provider_credentials pc ON pc.provider_id=u.id LEFT JOIN workplace_provider_operations po ON po.provider_id=u.id "
        "WHERE u.role_type='workplace_provider' ORDER BY u.name COLLATE NOCASE"
    ).fetchall()
    providers = []
    for row in rows:
        state = _provider_credential_state(conn, row["id"])
        associations = conn.execute(
            "SELECT i.id,i.name,p.status FROM workplace_providers p JOIN institutions i ON i.id=p.company_id WHERE p.provider_id=? ORDER BY i.name COLLATE NOCASE",
            (row["id"],),
        ).fetchall()
        pending = conn.execute(
            "SELECT id,professional_type_encrypted,title_encrypted,qualification_encrypted,registration_encrypted,license_state_encrypted,submitted_at "
            "FROM workplace_provider_credential_history WHERE provider_id=? AND status='pending_review' ORDER BY submitted_at DESC",
            (row["id"],),
        ).fetchall()
        providers.append({
            "id": row["id"], "name": row["name"], "email": row["email"], "account_status": row["account_status"],
            "invitation_pending": bool(row["invitation_token_hash"]),
            "invitation_expires_at": row["invitation_expires_at"],
            "credential_status": state["status"] if state else "pending_review", "credential_valid": bool(state and state["credential_valid"]),
            "valid_from": state["valid_from"] if state else None,
            "expires_at": state["expires_at"] if state else None, "access_status": state["access_status"] if state else "active",
            "expires_soon": bool(state and state["expires_at"] and datetime.now(timezone.utc).date() <= date.fromisoformat(str(state["expires_at"])[:10]) <= datetime.now(timezone.utc).date() + timedelta(days=30)),
            "availability": state["availability"] if state else "unavailable",
            "professional_type": decrypt_pii(row["professional_type"]) if row["professional_type"] else None,
            "title": decrypt_pii(row["title_encrypted"]),
            "associations": [dict(item) for item in associations],
            "demo_only": bool(row["demo_only"]),
            "license_state": decrypt_pii(row["license_state_encrypted"]) if row["license_state_encrypted"] else None,
            "pending_reviews": [{"id": item["id"], "professional_type": decrypt_pii(item["professional_type_encrypted"]) if item["professional_type_encrypted"] else None, "title": decrypt_pii(item["title_encrypted"]), "qualification": decrypt_pii(item["qualification_encrypted"]), "registration_number": decrypt_pii(item["registration_encrypted"]), "license_state": decrypt_pii(item["license_state_encrypted"]) if item["license_state_encrypted"] else None, "submitted_at": item["submitted_at"]} for item in pending],
        })
    conn.commit()
    conn.close()
    return providers


@router.post("/admin/provider-credential-reviews/{review_id}")
async def review_provider_credential(review_id: str, data: ProviderCredentialReview, actor: dict = Depends(require_auth)):
    if actor.get("role_type") != "admin":
        raise HTTPException(403, "Global administrator access required")
    if data.decision == "verify" and not data.verification_reference:
        raise HTTPException(400, "Record the verification reference before approving this credential")
    _validate_credential_period(data.valid_from, data.expires_at)
    now = _now()
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        review = conn.execute("SELECT * FROM workplace_provider_credential_history WHERE id=? AND status='pending_review'", (review_id,)).fetchone()
        if not review:
            raise HTTPException(404, "Pending provider credential review not found")
        if data.decision == "verify":
            conn.execute(
                "INSERT INTO workplace_provider_credential_history (id,provider_id,professional_type_encrypted,title_encrypted,qualification_encrypted,registration_encrypted,verification_reference_encrypted,status,submitted_at,reviewed_by,reviewed_at,valid_from,expires_at,license_state_encrypted) "
                "SELECT ?,provider_id,professional_type,title_encrypted,qualification_encrypted,registration_encrypted,verification_reference_encrypted,status,reviewed_at,reviewed_by,reviewed_at,valid_from,expires_at,license_state_encrypted FROM workplace_provider_credentials WHERE provider_id=?",
                (str(uuid.uuid4()), review["provider_id"]),
            )
            conn.execute(
                "UPDATE workplace_provider_credentials SET professional_type=?,title_encrypted=?,qualification_encrypted=?,registration_encrypted=?,verification_reference_encrypted=?,license_state_encrypted=COALESCE(?,license_state_encrypted),status='verified',reviewed_by=?,reviewed_at=?,valid_from=?,expires_at=?,reason_encrypted=NULL WHERE provider_id=?",
                (review["professional_type_encrypted"], review["title_encrypted"], review["qualification_encrypted"], review["registration_encrypted"], encrypt_pii(data.verification_reference.strip()), review["license_state_encrypted"], actor["id"], now, data.valid_from, data.expires_at, review["provider_id"]),
            )
            conn.execute(
                "UPDATE workplace_provider_credential_history SET status='verified',reviewed_by=?,reviewed_at=?,verification_reference_encrypted=?,valid_from=?,expires_at=? WHERE id=?",
                (actor["id"], now, encrypt_pii(data.verification_reference.strip()), data.valid_from, data.expires_at, review_id),
            )
            conn.execute("UPDATE users SET professional_title=? WHERE id=?", (review["title_encrypted"], review["provider_id"]))
            event = "WORKPLACE_PROVIDER_CREDENTIAL_VERIFIED"
        else:
            conn.execute("UPDATE workplace_provider_credential_history SET status='rejected',reviewed_by=?,reviewed_at=?,reason_encrypted=?,verification_reference_encrypted=? WHERE id=?", (actor["id"], now, encrypt_pii(data.reason.strip()) if data.reason else None, encrypt_pii(data.verification_reference.strip()) if data.verification_reference else None, review_id))
            event = "WORKPLACE_PROVIDER_CREDENTIAL_REJECTED"
        for company in conn.execute("SELECT DISTINCT company_id FROM workplace_providers WHERE provider_id=?", (review["provider_id"],)).fetchall():
            _audit(conn, company["company_id"], None, event)
        conn.commit()
    except HTTPException:
        conn.rollback()
        conn.close()
        raise
    except Exception as exc:
        conn.rollback()
        conn.close()
        raise HTTPException(409, "Unable to record provider credential review") from exc
    conn.close()
    write_audit(actor["id"], "admin", event, "user", review["provider_id"], {"review_id": review_id})
    return {"reviewed": True, "decision": data.decision, "status": "verified" if data.decision == "verify" else "rejected"}


@router.post("/admin/providers/{provider_id}/access")
async def update_provider_access(provider_id: str, data: ProviderAccessAction, actor: dict = Depends(require_auth)):
    if actor.get("role_type") != "admin":
        raise HTTPException(403, "Global administrator access required")
    status = {"suspend": "suspended", "reactivate": "active", "revoke": "revoked", "deactivate": "deactivated"}[data.action]
    now = _now()
    conn = get_db()
    provider = conn.execute("SELECT id FROM users WHERE id=? AND role_type='workplace_provider'", (provider_id,)).fetchone()
    if not provider:
        conn.close()
        raise HTTPException(404, "Workplace provider not found")
    conn.execute(
        "INSERT INTO workplace_provider_operations (provider_id,access_status,availability,reason_encrypted,changed_by,changed_at) VALUES (?,?,?, ?,?,?) "
        "ON CONFLICT(provider_id) DO UPDATE SET access_status=excluded.access_status,availability=excluded.availability,reason_encrypted=excluded.reason_encrypted,changed_by=excluded.changed_by,changed_at=excluded.changed_at",
        (provider_id, status, "unavailable" if status != "active" else "available", encrypt_pii(data.reason.strip()), actor["id"], now),
    )
    if data.action in {"suspend", "revoke", "deactivate"}:
        _mark_provider_cases_for_reassignment(conn, provider_id, status)
    if data.action == "deactivate":
        conn.execute("UPDATE workplace_providers SET status='inactive' WHERE provider_id=? AND status='active'", (provider_id,))
    event = {"suspend": "WORKPLACE_PROVIDER_SUSPENDED", "reactivate": "WORKPLACE_PROVIDER_REACTIVATED", "revoke": "WORKPLACE_PROVIDER_REVOKED", "deactivate": "WORKPLACE_PROVIDER_DEACTIVATED"}[data.action]
    for company in conn.execute("SELECT DISTINCT company_id FROM workplace_providers WHERE provider_id=?", (provider_id,)).fetchall():
        _audit(conn, company["company_id"], None, event)
    conn.commit()
    conn.close()
    write_audit(actor["id"], "admin", event, "user", provider_id, {"reason_recorded": True})
    return {"access_status": status, "active_cases_marked_for_reassignment": data.action in {"suspend", "revoke", "deactivate"}}


@router.post("/admin/providers/{provider_id}/credential-revoke")
async def revoke_provider_credential(provider_id: str, data: ProviderCredentialRevoke, actor: dict = Depends(require_auth)):
    if actor.get("role_type") != "admin":
        raise HTTPException(403, "Global administrator access required")
    now = _now()
    conn = get_db()
    credential = conn.execute("SELECT * FROM workplace_provider_credentials WHERE provider_id=?", (provider_id,)).fetchone()
    if not credential:
        conn.close()
        raise HTTPException(404, "Provider credential not found")
    conn.execute("UPDATE workplace_provider_credentials SET status='revoked',reviewed_by=?,reviewed_at=?,reason_encrypted=? WHERE provider_id=?", (actor["id"], now, encrypt_pii(data.reason.strip()), provider_id))
    conn.execute(
        "INSERT INTO workplace_provider_credential_history (id,provider_id,professional_type_encrypted,title_encrypted,qualification_encrypted,registration_encrypted,verification_reference_encrypted,status,submitted_at,reviewed_by,reviewed_at,valid_from,expires_at,reason_encrypted,license_state_encrypted) VALUES (?,?,?,?,?,? ,?,'revoked',?,?,?,?,?,?,?)",
        (str(uuid.uuid4()), provider_id, credential["professional_type"], credential["title_encrypted"], credential["qualification_encrypted"], credential["registration_encrypted"], credential["verification_reference_encrypted"], now, actor["id"], now, credential["valid_from"], credential["expires_at"], encrypt_pii(data.reason.strip()), credential["license_state_encrypted"]),
    )
    _mark_provider_cases_for_reassignment(conn, provider_id, "credential_revoked")
    for company in conn.execute("SELECT DISTINCT company_id FROM workplace_providers WHERE provider_id=?", (provider_id,)).fetchall():
        _audit(conn, company["company_id"], None, "WORKPLACE_PROVIDER_CREDENTIAL_REVOKED")
    conn.commit()
    conn.close()
    write_audit(actor["id"], "admin", "WORKPLACE_PROVIDER_CREDENTIAL_REVOKED", "user", provider_id, {"reason_recorded": True})
    return {"credential_status": "revoked"}


@router.post("/enrollment/verify")
async def verify_enrollment(data: EnrollmentVerify):
    conn = get_db()
    challenge = conn.execute(
        "SELECT c.*, s.work_email_domains_json, s.privacy_notice_version, s.demo_mode FROM workplace_enrollment_challenges c "
        "JOIN workplace_settings s ON s.company_id = c.company_id "
        "JOIN workplace_enrollment_links l ON l.id = c.link_id AND l.company_id = c.company_id "
        "JOIN institutions i ON i.id = c.company_id "
        "WHERE c.id = ? AND c.used_at IS NULL AND c.expires_at > ? AND l.revoked_at IS NULL "
        "AND (l.expires_at IS NULL OR l.expires_at > ?) AND i.type = 'company' AND i.status = 'ACTIVE' "
        "AND ((s.demo_mode=1 AND EXISTS (SELECT 1 FROM workplace_providers p JOIN workplace_provider_credentials pc ON pc.provider_id=p.provider_id JOIN users pu ON pu.id=p.provider_id LEFT JOIN workplace_provider_operations po ON po.provider_id=p.provider_id WHERE p.company_id=c.company_id AND p.status='active' AND pc.status='verified' AND pc.demo_only=1 AND COALESCE(po.access_status,'active')='active' AND pu.status IN ('approved','active'))) OR "
        "(s.demo_mode=0 AND s.legal_review_complete=1 AND s.policy_status='approved' AND EXISTS (SELECT 1 FROM workplace_providers p JOIN workplace_provider_credentials pc ON pc.provider_id=p.provider_id JOIN users pu ON pu.id=p.provider_id LEFT JOIN workplace_provider_operations po ON po.provider_id=p.provider_id WHERE p.company_id=c.company_id AND p.status='active' AND pc.status='verified' AND pc.demo_only=0 AND (pc.valid_from IS NULL OR pc.valid_from<=date('now')) AND (pc.expires_at IS NULL OR pc.expires_at>=date('now')) AND COALESCE(po.access_status,'active')='active' AND pu.status IN ('approved','active'))))",
        (data.challenge_id, _now(), _now()),
    ).fetchone()
    if not challenge:
        conn.close()
        raise HTTPException(400, "The verification code is invalid or expired")
    if not commercial_can_use(conn, challenge["company_id"], "enrollment"):
        conn.commit(); conn.close()
        raise HTTPException(403, "New workplace enrollment is temporarily unavailable for this company")
    if not secrets.compare_digest(challenge["code_hash"], hash_token(data.code)):
        new_attempts = challenge["attempts_count"] + 1
        conn.execute(
            "UPDATE workplace_enrollment_challenges SET attempts_count = ?, used_at = CASE WHEN ? >= 5 THEN ? ELSE used_at END WHERE id = ?",
            (new_attempts, new_attempts, _now(), data.challenge_id),
        )
        conn.commit()
        conn.close()
        raise HTTPException(400, "The verification code is invalid or expired")
    try:
        from backend.services.crypto import decrypt_pii

        email = decrypt_pii(challenge["email_encrypted"])
        name = decrypt_pii(challenge["name_encrypted"])
    except Exception:
        conn.close()
        raise HTTPException(503, "Unable to complete enrollment securely")
    approved_domains = {str(domain).strip().lower().lstrip("@") for domain in json.loads(challenge["work_email_domains_json"] or "[]")}
    if not challenge["demo_mode"] and str(email).strip().lower().rsplit("@", 1)[-1] not in approved_domains:
        conn.close()
        raise HTTPException(409, "This work email domain is no longer approved. Ask your workplace administrator for guidance.")
    try:
        from backend.database import create_user

        created = create_user(
            email,
            name,
            challenge["password_hash"],
            role_type="workplace_employee",
            institution_id=challenge["company_id"],
        )
        user_id = created["id"]
        now = _now()
        conn.execute(
            "UPDATE users SET status = 'approved', user_category = 'workplace_employee', onboarding_completed_at = ?, terms_accepted_at=?,workplace_terms_version=? WHERE id = ?",
            (now, now, WORKPLACE_EMPLOYEE_TERMS_VERSION, user_id),
        )
        conn.execute(
            "INSERT INTO workplace_memberships (id, company_id, user_id, status, notice_version, consented_at, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                str(uuid.uuid4()),
                challenge["company_id"],
                user_id,
                "active",
                challenge["privacy_notice_version"],
                now,
                now,
                now,
            ),
        )
        conn.execute(
            "UPDATE workplace_enrollment_challenges SET used_at = ? WHERE id = ? AND used_at IS NULL",
            (now, data.challenge_id),
        )
        _audit(conn, challenge["company_id"], user_id, "EMPLOYEE_OPTED_IN")
        _audit(conn, challenge["company_id"], user_id, "WORKPLACE_EMPLOYEE_TERMS_ACCEPTED")
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise HTTPException(
            409,
            "This email may already have an account. Please sign in or contact support.",
        )
    conn.close()
    from backend.auth import create_access_token

    return {
        "access_token": create_access_token(user_id, "workplace_employee"),
        "token_type": "bearer",
        "user": {
            "id": user_id,
            "email": email,
            "name": name,
            "role_type": "workplace_employee",
            "user_category": "workplace_employee",
        },
    }


@router.get("/me")
async def workplace_me(user: dict = Depends(require_auth)):
    membership = _employee(user)
    return {
        "name": user.get("name"),
        "status": membership["status"],
        "participation": "voluntary",
        "social_account_analysis": False,
        "support_available": True,
    }


@router.get("/providers")
async def available_providers(user: dict = Depends(require_auth)):
    membership = _employee(user)
    conn = get_db()
    if not commercial_can_use(conn, membership["company_id"], "provider_services"):
        conn.commit(); conn.close()
        return []
    rows = conn.execute(
        "SELECT u.id, u.name, u.professional_title FROM workplace_providers p JOIN users u ON u.id = p.provider_id JOIN workplace_provider_credentials pc ON pc.provider_id=u.id AND pc.status='verified' LEFT JOIN workplace_provider_operations po ON po.provider_id=u.id WHERE p.company_id = ? AND p.status = 'active' AND u.status IN ('approved','active') AND COALESCE(po.access_status,'active')='active' AND COALESCE(po.availability,'available')='available' AND (pc.valid_from IS NULL OR pc.valid_from<=date('now')) AND (pc.expires_at IS NULL OR pc.expires_at>=date('now')) ORDER BY u.name COLLATE NOCASE",
        (membership["company_id"],),
    ).fetchall()
    conn.close()
    return [
        {
            "id": row["id"],
            "name": row["name"],
            "title": decrypt_pii(row["professional_title"])
            if str(row["professional_title"] or "").startswith("gcm1:")
            else row["professional_title"],
        }
        for row in rows
    ]


@router.post("/checkins", status_code=201)
async def create_checkin(data: CheckinCreate, user: dict = Depends(require_auth)):
    return _store_workplace_checkin(data, user, origin="web")


def _store_workplace_checkin(data: CheckinCreate, user: dict, *, origin: str) -> dict:
    """Persist the existing workplace check-in schema with trusted provenance."""
    if origin not in {"web", "voice"}:
        raise ValueError("Unsupported workplace check-in origin")
    membership = _employee(user)
    now = _now()
    conn = get_db()
    resolve_commercial_account(conn, membership["company_id"])
    sync_offboarding(conn, membership["company_id"])
    if termination_effective(conn, membership["company_id"]):
        conn.commit(); conn.close()
        raise HTTPException(403, "New workplace-funded activity has ended for this company")
    conn.execute(
        "INSERT INTO workplace_checkins (id, company_id, user_id, answers_json, created_at, origin) VALUES (?,?,?,?,?,?)",
        (
            str(uuid.uuid4()),
            membership["company_id"],
            user["id"],
            encrypt_pii(json.dumps(data.model_dump())),
            now,
            origin,
        ),
    )
    _audit(conn, membership["company_id"], user["id"], "PRIVATE_CHECKIN_CREATED")
    conn.commit()
    conn.close()
    return {
        "saved": True,
        "created_at": now,
        "visibility": "private to you; shared with a provider only if you request support and explicitly share it",
    }


@router.post("/support-requests", status_code=201)
async def request_provider_support(
    data: SupportRequest, user: dict = Depends(require_auth)
):
    membership = _employee(user)
    if not data.share_latest_checkin:
        raise HTTPException(
            400,
            "Explicitly choose whether to share your latest check-in with the provider",
        )
    conn = get_db()
    conn.execute("BEGIN IMMEDIATE")
    if not commercial_can_use(conn, membership["company_id"], "provider_services"):
        conn.rollback(); conn.close()
        raise HTTPException(403, "New provider support requests are unavailable for this workplace plan")
    provider = conn.execute(
        "SELECT 1 FROM workplace_providers WHERE company_id = ? AND provider_id = ? AND status = 'active'",
        (membership["company_id"], data.provider_id),
    ).fetchone()
    provider_account = conn.execute(
        "SELECT u.email FROM users u JOIN workplace_provider_credentials c ON c.provider_id=u.id AND c.status='verified' WHERE u.id = ? AND u.role_type = 'workplace_provider' AND u.status IN ('approved','active')",
        (data.provider_id,),
    ).fetchone()
    latest = conn.execute(
        "SELECT id FROM workplace_checkins WHERE company_id = ? AND user_id = ? ORDER BY created_at DESC LIMIT 1",
        (membership["company_id"], user["id"]),
    ).fetchone()
    if not provider or not provider_account or not _provider_can_receive_case(conn, data.provider_id, membership["company_id"]):
        conn.close()
        raise HTTPException(
            400, "That care provider is not available through your workplace"
        )
    if not latest:
        conn.close()
        raise HTTPException(400, "Complete a check-in before requesting support")
    now = _now()
    case_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO workplace_support_cases (id, company_id, user_id, provider_id, status, share_consent_at, shared_checkin_id, created_at, updated_at, assignment_status, assigned_at) VALUES (?,?,?,?,?,?,?,?,?,'assigned',?)",
        (
            case_id,
            membership["company_id"],
            user["id"],
            data.provider_id,
            "open",
            now,
            latest["id"],
            now,
            now,
            now,
        ),
    )
    _audit(
        conn,
        membership["company_id"],
        user["id"],
        "SUPPORT_REQUESTED_AND_CHECKIN_SHARED",
    )
    conn.commit()
    conn.close()
    # No employee identity or check-in content goes into the notification email.
    try:
        send_html_email(
            provider_account["email"],
            "A workplace support request is available",
            "<p>An employee has requested support and shared information with you in MindGuard. Sign in to your workplace provider workspace to review it.</p>",
            related_type="workplace_support_case",
            related_id=case_id,
        )
    except Exception:
        import logging

        logging.getLogger(__name__).warning(
            "Workplace support notification could not be queued for case_id=%s", case_id
        )
    return {
        "case_id": case_id,
        "status": "open",
        "message": "Your selected provider can now see your shared check-in. Your employer is not notified.",
    }


@router.post("/withdraw")
async def withdraw_workplace_participation(user: dict = Depends(require_auth)):
    membership = _employee(user)
    now = _now()
    conn = get_db()
    conn.execute(
        "UPDATE workplace_memberships SET status = 'withdrawn', withdrawn_at = ?, updated_at = ? WHERE id = ?",
        (now, now, membership["id"]),
    )
    conn.execute(
        "UPDATE workplace_support_cases SET status = 'access_withdrawn', withdrawn_at = ?, updated_at = ? WHERE user_id = ? AND company_id = ? AND withdrawn_at IS NULL",
        (now, now, user["id"], membership["company_id"]),
    )
    _audit(
        conn, membership["company_id"], user["id"], "EMPLOYEE_WITHDREW_PARTICIPATION"
    )
    conn.commit()
    conn.close()
    return {
        "withdrawn": True,
        "message": "Workplace participation has ended. Future check-ins and provider access are disabled.",
    }


@router.get("/checkins")
async def own_workplace_checkins(user: dict = Depends(require_auth)):
    membership = _employee(user)
    conn = get_db()
    rows = conn.execute(
        "SELECT id, answers_json, created_at, origin FROM workplace_checkins WHERE company_id = ? AND user_id = ? ORDER BY created_at DESC LIMIT 50",
        (membership["company_id"], user["id"]),
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        try:
            answers = json.loads(decrypt_pii(row["answers_json"]))
        except (ValueError, TypeError, RuntimeError):
            continue
        result.append({"id": row["id"], "answers": answers, "created_at": row["created_at"], "origin": row["origin"]})
    return result


@router.get("/support-requests")
async def own_workplace_support_requests(user: dict = Depends(require_auth)):
    membership = _employee(user)
    conn = get_db()
    assigned = conn.execute("SELECT DISTINCT provider_id FROM workplace_support_cases WHERE company_id=? AND user_id=? AND assignment_status='assigned' AND status IN ('open','active')", (membership["company_id"], user["id"])).fetchall()
    for provider in assigned:
        _provider_credential_state(conn, provider["provider_id"])
    rows = conn.execute(
        "SELECT id, status, assignment_status, created_at, assigned_at, closed_at, withdrawn_at FROM workplace_support_cases WHERE company_id = ? AND user_id = ? ORDER BY created_at DESC",
        (membership["company_id"], user["id"]),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


@router.post("/support-requests/{case_id}/reassign")
async def employee_reassign_support_case(case_id: str, data: WorkplaceCaseReassignment, user: dict = Depends(require_auth)):
    membership = _employee(user)
    if not data.confirm_shared_history:
        raise HTTPException(400, "Confirm before sharing previously shared case information with the new provider")
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        case = conn.execute(
            "SELECT id,company_id,provider_id,status,assignment_status FROM workplace_support_cases "
            "WHERE id=? AND user_id=? AND company_id=? AND withdrawn_at IS NULL",
            (case_id, user["id"], membership["company_id"]),
        ).fetchone()
        if not case or case["assignment_status"] != "reassignment_required" or case["status"] not in {"open", "active"}:
            raise HTTPException(409, "This support case is not awaiting a provider change")
        if data.provider_id == case["provider_id"]:
            raise HTTPException(400, "Choose a different provider")
        if not _provider_can_receive_case(conn, data.provider_id, membership["company_id"]):
            raise HTTPException(400, "Choose a currently eligible provider who is available for new support")
        now = _now()
        conn.execute(
            "UPDATE workplace_support_cases SET provider_id=?,assignment_status='assigned',assigned_at=?,updated_at=? WHERE id=? AND assignment_status='reassignment_required'",
            (data.provider_id, now, now, case_id),
        )
        conn.execute(
            "INSERT INTO workplace_case_assignment_history (id,case_id,company_id,previous_provider_id,new_provider_id,event_type,worker_consent_at,occurred_at) VALUES (?,?,?,?,?,'worker_consented_reassignment',?,?)",
            (str(uuid.uuid4()), case_id, membership["company_id"], case["provider_id"], data.provider_id, now, now),
        )
        _audit(conn, membership["company_id"], user["id"], "WORKPLACE_CASE_REASSIGNED_WITH_WORKER_CONSENT")
        conn.commit()
    except HTTPException:
        conn.rollback()
        conn.close()
        raise
    except Exception as exc:
        conn.rollback()
        conn.close()
        raise HTTPException(409, "Unable to reassign this support case") from exc
    conn.close()
    from backend.database import create_notification
    create_notification(data.provider_id, "A workplace support case is ready", "A worker has confirmed sharing a workplace support case with you. Sign in to review it.", "general")
    return {"reassigned": True, "case_id": case_id, "assignment_status": "assigned", "shared_history_confirmed": True}


@router.post("/support-requests/{case_id}/withdraw")
async def withdraw_case_sharing(case_id: str, user: dict = Depends(require_auth)):
    membership = _employee(user)
    now = _now()
    conn = get_db()
    cur = conn.execute(
        "UPDATE workplace_support_cases SET status = 'access_withdrawn', withdrawn_at = ?, updated_at = ? WHERE id = ? AND company_id = ? AND user_id = ? AND withdrawn_at IS NULL",
        (now, now, case_id, membership["company_id"], user["id"]),
    )
    if cur.rowcount:
        _audit(conn, membership["company_id"], user["id"], "PROVIDER_SHARING_WITHDRAWN")
    conn.commit()
    conn.close()
    if not cur.rowcount:
        raise HTTPException(404, "Active support sharing was not found")
    return {"withdrawn": True}


@router.post("/admin/enrollment-link")
async def create_enrollment_link(user: dict = Depends(require_auth)):
    company_id = _company_admin(user)
    token = secrets.token_urlsafe(40)
    conn = get_db()
    if not commercial_can_use(conn, company_id, "enrollment"):
        conn.commit(); conn.close()
        raise HTTPException(403, "New enrollment links are unavailable for this workplace plan or commercial status")
    setup = conn.execute(
        "SELECT demo_mode,legal_review_complete, policy_status,work_email_domains_json FROM workplace_settings WHERE company_id = ?",
        (company_id,),
    ).fetchone()
    if not setup:
        conn.close()
        raise HTTPException(404, "Workplace setup was not found")
    if setup["demo_mode"]:
        provider = conn.execute("SELECT 1 FROM workplace_providers p JOIN workplace_provider_credentials c ON c.provider_id=p.provider_id JOIN users u ON u.id=p.provider_id WHERE p.company_id=? AND p.status='active' AND c.status='verified' AND c.demo_only=1 AND u.status IN ('approved','active') LIMIT 1", (company_id,)).fetchone()
        if not provider:
            conn.close()
            raise HTTPException(409, "The sample demo provider is not available")
    else:
        if not setup["legal_review_complete"]:
            conn.close()
            raise HTTPException(403, "A documented US privacy and legal review is required before real employee enrollment")
        provider = conn.execute("SELECT 1 FROM workplace_providers p JOIN workplace_provider_credentials c ON c.provider_id=p.provider_id JOIN users u ON u.id=p.provider_id LEFT JOIN workplace_provider_operations po ON po.provider_id=p.provider_id WHERE p.company_id=? AND p.status='active' AND c.status='verified' AND c.demo_only=0 AND (c.valid_from IS NULL OR c.valid_from<=date('now')) AND (c.expires_at IS NULL OR c.expires_at>=date('now')) AND COALESCE(po.access_status,'active')='active' AND u.status IN ('approved','active') LIMIT 1", (company_id,)).fetchone()
        if setup["policy_status"] != "approved" or not provider:
            conn.close()
            raise HTTPException(403, "Complete the company privacy policy and configure an approved provider before real employee enrollment")
        if not json.loads(setup["work_email_domains_json"] or "[]"):
            conn.close()
            raise HTTPException(403, "Add at least one approved company email domain before real employee enrollment")
    link_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    expires = (now + timedelta(days=90)).isoformat()
    conn.execute(
        "INSERT INTO workplace_enrollment_links (id, company_id, token_hash, expires_at, created_by, created_at) VALUES (?,?,?,?,?,?)",
        (link_id, company_id, hash_token(token), expires, user["id"], now.isoformat()),
    )
    _audit(conn, company_id, user["id"], "ENROLLMENT_LINK_CREATED")
    conn.commit()
    conn.close()
    # This is the only time the cleartext link is returned. No redemption data is exposed.
    return {"id": link_id, "token": token, "expires_at": expires, "revocable": True}


@router.get("/enrollment/resolve")
async def resolve_enrollment_link(token: str):
    """Return only the company name and demo marker needed by the public join screen."""
    conn = get_db()
    link = _company_enrollment_is_ready(conn, token=token)
    if not link:
        conn.close()
        raise HTTPException(404, "This enrollment link is invalid, expired, revoked, or not ready")
    company = conn.execute("SELECT name FROM institutions WHERE id=?", (link["company_id"],)).fetchone()
    conn.close()
    return {"company_name": company["name"] if company else "Workplace", "demo_mode": bool(link["demo_mode"])}


@router.get("/admin/enrollment-links")
async def list_enrollment_links(user: dict = Depends(require_auth)):
    company_id = _company_admin(user)
    conn = get_db()
    rows = conn.execute(
        "SELECT id, expires_at, revoked_at, created_at FROM workplace_enrollment_links WHERE company_id = ? ORDER BY created_at DESC",
        (company_id,),
    ).fetchall()
    conn.close()
    # Safe lifecycle metadata only: never return the token or redemption information.
    return [
        {
            "id": row["id"],
            "expires_at": row["expires_at"],
            "revoked_at": row["revoked_at"],
            "created_at": row["created_at"],
            "active": row["revoked_at"] is None
            and (row["expires_at"] is None or row["expires_at"] > _now()),
        }
        for row in rows
    ]


@router.post("/admin/providers", status_code=201)
async def attach_provider(data: ProviderAttach, user: dict = Depends(require_auth)):
    company_id = _company_admin(user)
    conn = get_db()
    if _is_demo_company(conn, company_id):
        conn.close()
        raise HTTPException(409, "A sample provider is already included in the demo workplace")
    conn.execute("BEGIN IMMEDIATE")
    if not commercial_can_use(conn, company_id, "provider_services"):
        conn.commit(); conn.close()
        raise HTTPException(403, "Provider services are unavailable for this workplace plan or commercial status")
    account = resolve_commercial_account(conn, company_id)
    provider_limit = commercial_plan_limit(account, "provider_limit") if account else 0
    provider = conn.execute(
        "SELECT u.id FROM users u JOIN workplace_provider_credentials c ON c.provider_id = u.id AND c.status = 'verified' AND c.demo_only=0 LEFT JOIN workplace_provider_operations po ON po.provider_id=u.id WHERE u.email = ? AND u.role_type = 'workplace_provider' AND u.status IN ('approved','active') AND COALESCE(po.access_status,'active')='active' AND (c.valid_from IS NULL OR c.valid_from<=date('now')) AND (c.expires_at IS NULL OR c.expires_at>=date('now'))",
        (str(data.provider_email).lower(),),
    ).fetchone()
    if not provider:
        candidate = conn.execute(
            "SELECT u.status AS account_status,c.status AS credential_status,c.demo_only,c.valid_from,c.expires_at,"
            "COALESCE(po.access_status,'active') AS access_status FROM users u "
            "LEFT JOIN workplace_provider_credentials c ON c.provider_id=u.id "
            "LEFT JOIN workplace_provider_operations po ON po.provider_id=u.id "
            "WHERE lower(u.email)=? AND u.role_type='workplace_provider' LIMIT 1",
            (str(data.provider_email).lower(),),
        ).fetchone()
        conn.close()
        if not candidate:
            raise HTTPException(404, "No workplace provider account is registered for that email")
        if str(candidate["account_status"]).lower() not in {"approved", "active"}:
            raise HTTPException(409, "The provider must accept their invitation before a workplace can connect them")
        if not candidate["credential_status"] or candidate["credential_status"] != "verified":
            raise HTTPException(409, "The provider’s license review is not approved yet")
        if candidate["demo_only"]:
            raise HTTPException(409, "Demo providers can only be used in demo workplaces")
        current_day = datetime.now(timezone.utc).date().isoformat()
        if candidate["valid_from"] and str(candidate["valid_from"])[:10] > current_day:
            raise HTTPException(409, f"The license is verified but does not become effective until {str(candidate['valid_from'])[:10]}. Ask MindGuard Admin to correct the effective date if it was entered incorrectly.")
        if candidate["expires_at"] and str(candidate["expires_at"])[:10] < current_day:
            raise HTTPException(409, f"The provider’s license expired on {str(candidate['expires_at'])[:10]} and must be updated before connection")
        if candidate["access_status"] != "active":
            raise HTTPException(409, "Provider access is paused. Ask MindGuard Admin to reactivate it before connecting")
        raise HTTPException(409, "The provider account is not currently eligible to connect. Ask MindGuard Admin to review the account status")
    already_attached = conn.execute("SELECT 1 FROM workplace_providers WHERE company_id=? AND provider_id=? AND status='active'", (company_id, provider["id"])).fetchone()
    active_provider_count = conn.execute("SELECT COUNT(*) AS n FROM workplace_providers WHERE company_id=? AND status='active'", (company_id,)).fetchone()["n"]
    if not already_attached and provider_limit is not None and active_provider_count >= provider_limit:
        conn.close()
        raise HTTPException(409, "This workplace plan has reached its provider limit")
    conn.execute(
        "INSERT OR IGNORE INTO workplace_providers (company_id, provider_id, status, created_at) VALUES (?,?, 'active', ?)",
        (company_id, provider["id"], _now()),
    )
    conn.execute("UPDATE workplace_settings SET provider_service_enabled=1,updated_at=? WHERE company_id=?", (_now(), company_id))
    _audit(conn, company_id, user["id"], "WORKPLACE_PROVIDER_ATTACHED")
    conn.commit()
    conn.close()
    return {"attached": True}


@router.get("/admin/providers")
async def company_provider_list(user: dict = Depends(require_auth)):
    company_id = _company_admin(user)
    conn = get_db()
    rows = conn.execute(
        "SELECT u.id, u.name, u.status AS account_status, u.professional_title, p.status AS association_status, c.status AS credential_status,c.valid_from,c.expires_at,COALESCE(o.access_status,'active') AS access_status,COALESCE(o.availability,'available') AS availability,EXISTS (SELECT 1 FROM workplace_provider_credential_history h WHERE h.provider_id=u.id AND h.status='pending_review') AS review_pending FROM workplace_providers p JOIN users u ON u.id = p.provider_id LEFT JOIN workplace_provider_credentials c ON c.provider_id=u.id LEFT JOIN workplace_provider_operations o ON o.provider_id=u.id WHERE p.company_id = ? ORDER BY u.name COLLATE NOCASE",
        (company_id,),
    ).fetchall()
    result = [
        {
            "id": row["id"],
            "name": row["name"],
            "title": decrypt_pii(row["professional_title"])
            if str(row["professional_title"] or "").startswith("gcm1:")
            else row["professional_title"],
            "association_status": row["association_status"],
            "status": "unavailable" if row["association_status"] != "active" or row["access_status"] != "active" or str(row["account_status"]).lower() not in {"approved", "active"} or row["availability"] == "unavailable" else "review_required" if row["credential_status"] != "verified" or bool(row["review_pending"]) or (row["expires_at"] and row["expires_at"] < datetime.now(timezone.utc).date().isoformat()) or (row["valid_from"] and row["valid_from"] > datetime.now(timezone.utc).date().isoformat()) else "verified",
        }
        for row in rows
    ]
    conn.close()
    return result


@router.post("/admin/providers/{provider_id}/deactivate")
async def deactivate_provider(provider_id: str, user: dict = Depends(require_auth)):
    company_id = _company_admin(user)
    conn = get_db()
    conn.execute("BEGIN IMMEDIATE")
    cur = conn.execute(
        "UPDATE workplace_providers SET status = 'inactive' WHERE company_id = ? AND provider_id = ? AND status = 'active'",
        (company_id, provider_id),
    )
    if cur.rowcount:
        _mark_provider_cases_for_reassignment(conn, provider_id, "company_relationship_removed", company_id=company_id)
        remaining = conn.execute("SELECT 1 FROM workplace_providers p JOIN workplace_provider_credentials c ON c.provider_id=p.provider_id JOIN users u ON u.id=p.provider_id LEFT JOIN workplace_provider_operations po ON po.provider_id=p.provider_id WHERE p.company_id=? AND p.status='active' AND c.status='verified' AND (c.valid_from IS NULL OR c.valid_from<=date('now')) AND (c.expires_at IS NULL OR c.expires_at>=date('now')) AND COALESCE(po.access_status,'active')='active' AND u.status IN ('approved','active') LIMIT 1", (company_id,)).fetchone()
        if not remaining:
            conn.execute("UPDATE workplace_settings SET provider_service_enabled=0,updated_at=? WHERE company_id=?", (_now(), company_id))
        _audit(conn, company_id, user["id"], "WORKPLACE_PROVIDER_DEACTIVATED")
    conn.commit()
    conn.close()
    if not cur.rowcount:
        raise HTTPException(404, "Active provider not found")
    return {"deactivated": True}


@router.post("/admin/enrollment-link/{link_id}/revoke")
async def revoke_enrollment_link(link_id: str, user: dict = Depends(require_auth)):
    company_id = _company_admin(user)
    conn = get_db()
    cur = conn.execute(
        "UPDATE workplace_enrollment_links SET revoked_at = ? WHERE id = ? AND company_id = ? AND revoked_at IS NULL",
        (_now(), link_id, company_id),
    )
    if cur.rowcount:
        _audit(conn, company_id, user["id"], "ENROLLMENT_LINK_REVOKED")
    conn.commit()
    conn.close()
    if not cur.rowcount:
        raise HTTPException(404, "Active enrollment link not found")
    return {"revoked": True}


@router.get("/admin/report")
async def workplace_aggregate_report(user: dict = Depends(require_auth)):
    company_id = _company_admin(user)
    conn = get_db()
    insights = get_workplace_insights(conn, company_id, actor_id=user["id"])
    overview = insights.get("overview") or {}
    conn.commit()
    conn.close()
    response = {
        "state": insights["state"],
        "suppressed": insights["state"] != ANALYTICS_AVAILABLE,
        "minimum_cohort": insights["minimum_cohort"],
        "message": insights.get("privacy_message"),
        "period": insights.get("period"),
        "scope": "whole workplace; latest completed month; no filters or individual data",
    }
    if not response["suppressed"]:
        response.update({
            "cohort_size": overview["contributors"],
            "checkins": overview["checkins"],
            "averages": {theme["key"]: theme["average"] for theme in insights.get("themes", [])},
        })
    return response


@router.get("/admin/report/trends")
async def workplace_aggregate_trends(user: dict = Depends(require_auth)):
    company_id = _company_admin(user)
    conn = get_db()
    insights = get_workplace_insights(conn, company_id, actor_id=user["id"])
    conn.commit()
    conn.close()
    periods = []
    for period in insights["trends"]:
        item = {
            "period": period["period"],
            "state": period["state"],
            "suppressed": period["state"] != ANALYTICS_AVAILABLE,
        }
        if not item["suppressed"]:
            item.update({
                "averages": period["averages"],
                "wellbeing_indicator": period["wellbeing_indicator"],
            })
        periods.append(item)
    return {
        "scope": "fixed whole-company completed months",
        "suppressed": not any(period["state"] == ANALYTICS_AVAILABLE for period in insights["trends"]),
        "minimum_cohort": insights["minimum_cohort"],
        "message": insights.get("privacy_message"),
        "periods": periods,
    }


@router.get("/admin/insights")
async def workplace_insights(user: dict = Depends(require_auth)):
    """Executive whole-workplace report; the privacy layer owns all aggregation."""
    company_id = _company_admin(user)
    conn = get_db()
    result = get_workplace_insights(conn, company_id, actor_id=user["id"])
    conn.commit()
    conn.close()
    return result


@router.get("/provider/cases")
async def provider_cases(user: dict = Depends(require_auth)):
    _provider_access(user)
    conn = get_db()
    rows = conn.execute(
        "SELECT c.id, c.company_id, c.user_id, c.shared_checkin_id, c.status, c.created_at, u.name, u.email FROM workplace_support_cases c JOIN users u ON u.id = c.user_id JOIN workplace_providers p ON p.company_id = c.company_id AND p.provider_id = c.provider_id AND (p.status='active' OR (p.status='ending' AND c.continuity_until>?)) JOIN institutions i ON i.id=c.company_id AND i.type='company' AND i.status='ACTIVE' WHERE c.provider_id = ? AND c.assignment_status='assigned' AND c.withdrawn_at IS NULL ORDER BY c.created_at DESC",
        (_now(), user["id"]),
    ).fetchall()
    result = []
    for row in rows:
        checkin = conn.execute(
            "SELECT answers_json, created_at FROM workplace_checkins WHERE id = ? AND company_id = ? AND user_id = ?",
            (row["shared_checkin_id"], row["company_id"], row["user_id"]),
        ).fetchone()
        try:
            shared = (
                json.loads(decrypt_pii(checkin["answers_json"])) if checkin else None
            )
        except (ValueError, TypeError, RuntimeError):
            shared = None
        result.append(
            {
                "case_id": row["id"],
                "employee_name": row["name"],
                "employee_email": row["email"],
                "status": row["status"],
                "created_at": row["created_at"],
                "shared_checkin": shared,
                "checkin_at": checkin["created_at"] if checkin else None,
            }
        )
    conn.close()
    return result


@router.get("/provider/cases/{case_id}")
async def provider_case_detail(case_id: str, user: dict = Depends(require_auth)):
    _provider_access(user, case_id=case_id)
    conn = get_db()
    case = conn.execute("SELECT c.id,c.status,c.created_at,u.name,u.email FROM workplace_support_cases c JOIN users u ON u.id=c.user_id JOIN workplace_providers p ON p.company_id=c.company_id AND p.provider_id=c.provider_id AND (p.status='active' OR (p.status='ending' AND c.continuity_until>?)) JOIN institutions i ON i.id=c.company_id AND i.type='company' AND i.status='ACTIVE' WHERE c.id=? AND c.provider_id=? AND c.assignment_status='assigned' AND c.withdrawn_at IS NULL", (_now(), case_id, user["id"])).fetchone()
    if not case:
        conn.close(); raise HTTPException(404, "Active workplace case not found")
    notes = conn.execute("SELECT id,private_note_encrypted,employee_update_encrypted,shared_at,created_at FROM workplace_case_notes WHERE case_id=? AND provider_id=? ORDER BY created_at DESC", (case_id, user["id"])).fetchall()
    conn.close()
    return {"case": dict(case), "notes": [{"id": n["id"], "private_note": decrypt_pii(n["private_note_encrypted"]), "employee_update": decrypt_pii(n["employee_update_encrypted"]) if n["employee_update_encrypted"] else None, "shared_at": n["shared_at"], "created_at": n["created_at"]} for n in notes]}


@router.post("/provider/cases/{case_id}/notes", status_code=201)
async def create_workplace_case_note(case_id: str, data: WorkplaceCaseNoteCreate, user: dict = Depends(require_auth)):
    _provider_access(user, case_id=case_id, writable=True)
    conn = get_db()
    case = conn.execute("SELECT c.company_id,c.user_id FROM workplace_support_cases c JOIN workplace_providers p ON p.company_id=c.company_id AND p.provider_id=c.provider_id AND (p.status='active' OR (p.status='ending' AND c.continuity_until>?)) JOIN institutions i ON i.id=c.company_id AND i.type='company' AND i.status='ACTIVE' WHERE c.id=? AND c.provider_id=? AND c.withdrawn_at IS NULL AND c.status IN ('open','active')", (_now(), case_id, user["id"])).fetchone()
    if not case:
        conn.close(); raise HTTPException(404, "Active workplace case not found")
    now = _now(); note_id = str(uuid.uuid4()); employee_update = data.employee_update.strip() if data.employee_update else ""
    conn.execute("INSERT INTO workplace_case_notes (id,case_id,provider_id,private_note_encrypted,employee_update_encrypted,shared_at,created_at) VALUES (?,?,?,?,?,?,?)", (note_id, case_id, user["id"], encrypt_pii(data.private_note.strip()), encrypt_pii(employee_update) if employee_update else None, now if employee_update else None, now))
    _audit(conn, case["company_id"], user["id"], "WORKPLACE_CASE_NOTE_CREATED")
    conn.commit(); conn.close()
    if employee_update:
        from backend.database import create_notification
        create_notification(case["user_id"], "New support update", "Your independent care provider shared a new update in your workplace wellbeing space.", "general")
    return {"id": note_id, "shared": bool(employee_update), "created_at": now}


@router.post("/provider/cases/{case_id}/close")
async def close_workplace_case(case_id: str, user: dict = Depends(require_auth)):
    _provider_access(user, case_id=case_id, writable=True)
    conn=get_db()
    row=conn.execute("SELECT c.company_id,c.user_id FROM workplace_support_cases c JOIN workplace_providers p ON p.company_id=c.company_id AND p.provider_id=c.provider_id AND p.status='active' JOIN institutions i ON i.id=c.company_id AND i.type='company' AND i.status='ACTIVE' WHERE c.id=? AND c.provider_id=? AND c.withdrawn_at IS NULL AND c.status IN ('open','active')",(case_id,user["id"])).fetchone()
    if not row:
        conn.close(); raise HTTPException(404,"Active workplace case not found")
    now=_now();conn.execute("UPDATE workplace_support_cases SET status='closed',closed_by=?,closed_at=?,updated_at=? WHERE id=?",(user["id"],now,now,case_id));conn.execute("UPDATE workplace_appointments SET status='cancelled',updated_at=? WHERE case_id=? AND status='scheduled'",(now,case_id));_audit(conn,row["company_id"],user["id"],"WORKPLACE_CASE_CLOSED");conn.commit();conn.close()
    from backend.database import create_notification
    create_notification(row["user_id"],"Workplace support case closed","Your provider closed the current support case. You can request support again if needed.","general")
    return {"ok":True,"status":"closed"}


@router.get("/support-updates")
async def employee_support_updates(user: dict = Depends(require_auth)):
    membership = _employee(user)
    conn = get_db()
    rows = conn.execute("SELECT n.id,n.employee_update_encrypted,n.shared_at FROM workplace_case_notes n JOIN workplace_support_cases c ON c.id=n.case_id WHERE c.company_id=? AND c.user_id=? AND c.withdrawn_at IS NULL AND n.shared_at IS NOT NULL ORDER BY n.shared_at DESC", (membership["company_id"], user["id"])).fetchall()
    conn.close()
    return [{"id": row["id"], "message": decrypt_pii(row["employee_update_encrypted"]), "shared_at": row["shared_at"]} for row in rows]


@router.get("/support/messages")
async def employee_workplace_messages(user: dict = Depends(require_auth)):
    membership = _employee(user)
    conn = get_db()
    rows = conn.execute("SELECT m.id,m.case_id,m.sender_id,m.body_encrypted,m.created_at FROM workplace_messages m JOIN workplace_support_cases c ON c.id=m.case_id WHERE c.company_id=? AND c.user_id=? AND c.withdrawn_at IS NULL AND c.status IN ('open','active') ORDER BY m.created_at", (membership["company_id"], user["id"])).fetchall()
    conn.close()
    return [{"id": r["id"], "case_id": r["case_id"], "from_me": r["sender_id"] == user["id"], "message": decrypt_pii(r["body_encrypted"]), "created_at": r["created_at"]} for r in rows]


@router.post("/support/messages", status_code=201)
async def send_employee_workplace_message(data: WorkplaceMessageCreate, user: dict = Depends(require_auth)):
    membership = _employee(user)
    conn = get_db()
    case = conn.execute("SELECT c.provider_id,c.company_id FROM workplace_support_cases c JOIN workplace_providers p ON p.company_id=c.company_id AND p.provider_id=c.provider_id AND p.status='active' JOIN workplace_provider_credentials pc ON pc.provider_id=c.provider_id AND pc.status='verified' LEFT JOIN workplace_provider_operations po ON po.provider_id=c.provider_id JOIN users u ON u.id=c.provider_id AND u.status IN ('approved','active') JOIN institutions i ON i.id=c.company_id AND i.type='company' AND i.status='ACTIVE' WHERE c.id=? AND c.user_id=? AND c.company_id=? AND c.assignment_status='assigned' AND c.withdrawn_at IS NULL AND c.status IN ('open','active') AND (pc.valid_from IS NULL OR pc.valid_from<=date('now')) AND (pc.expires_at IS NULL OR pc.expires_at>=date('now')) AND COALESCE(po.access_status,'active')='active'", (data.case_id, user["id"], membership["company_id"])).fetchone()
    if not case:
        conn.close(); raise HTTPException(404, "Active provider support case not found")
    now = _now(); conn.execute("INSERT INTO workplace_messages (id,case_id,sender_id,body_encrypted,created_at) VALUES (?,?,?,?,?)", (str(uuid.uuid4()), data.case_id, user["id"], encrypt_pii(data.message.strip()), now))
    _audit(conn, case["company_id"], user["id"], "WORKPLACE_SUPPORT_MESSAGE_SENT"); conn.commit(); conn.close()
    from backend.database import create_notification
    create_notification(case["provider_id"], "New workplace support message", "An employee you support sent you a private message.", "message")
    return {"ok": True, "created_at": now}


@router.get("/appointments")
async def employee_workplace_appointments(user: dict = Depends(require_auth)):
    membership = _employee(user)
    conn = get_db()
    rows = conn.execute("SELECT a.id,a.case_id,a.starts_at,a.mode,a.location_or_link_encrypted,a.status,a.created_at,u.name AS provider_name FROM workplace_appointments a JOIN workplace_support_cases c ON c.id=a.case_id JOIN users u ON u.id=a.provider_id WHERE a.company_id=? AND a.user_id=? AND c.withdrawn_at IS NULL ORDER BY a.starts_at DESC", (membership["company_id"], user["id"])).fetchall()
    conn.close()
    return [{"id": r["id"], "case_id": r["case_id"], "starts_at": r["starts_at"], "mode": r["mode"], "location_or_link": decrypt_pii(r["location_or_link_encrypted"]) if r["location_or_link_encrypted"] else None, "status": r["status"], "created_at": r["created_at"], "provider_name": r["provider_name"]} for r in rows]


@router.post("/provider/cases/{case_id}/appointments", status_code=201)
async def create_workplace_appointment(case_id: str, data: WorkplaceAppointmentCreate, user: dict = Depends(require_auth)):
    _provider_access(user, case_id=case_id, writable=True)
    try:
        starts = datetime.fromisoformat(data.starts_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(400, "Enter a valid appointment date and time") from exc
    if starts.tzinfo is None or starts <= datetime.now(timezone.utc):
        raise HTTPException(400, "Appointment time must include a timezone and be in the future")
    place = data.location_or_link.strip()
    if data.mode == "online" and (urlparse(place).scheme != "https" or not urlparse(place).netloc):
        raise HTTPException(400, "Online appointments require a secure HTTPS meeting link")
    conn = get_db()
    case = conn.execute("SELECT c.company_id,c.user_id FROM workplace_support_cases c JOIN workplace_providers p ON p.company_id=c.company_id AND p.provider_id=c.provider_id AND p.status='active' JOIN institutions i ON i.id=c.company_id AND i.type='company' AND i.status='ACTIVE' WHERE c.id=? AND c.provider_id=? AND c.withdrawn_at IS NULL AND c.status IN ('open','active')", (case_id, user["id"])).fetchone()
    if not case:
        conn.close(); raise HTTPException(404, "Active workplace support case not found")
    now = _now(); appointment_id = str(uuid.uuid4())
    conn.execute("INSERT INTO workplace_appointments (id,case_id,company_id,user_id,provider_id,starts_at,mode,location_or_link_encrypted,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (appointment_id, case_id, case["company_id"], case["user_id"], user["id"], starts.isoformat(), data.mode, encrypt_pii(place), "scheduled", now, now))
    _audit(conn, case["company_id"], user["id"], "WORKPLACE_APPOINTMENT_SCHEDULED"); conn.commit(); conn.close()
    from backend.database import create_notification
    create_notification(case["user_id"], "Workplace support appointment scheduled", "Your independent provider scheduled a support appointment. Open your private workplace space to view the time and details.", "appointment")
    return {"id": appointment_id, "status": "scheduled", "starts_at": starts.isoformat()}


@router.get("/provider/cases/{case_id}/messages")
async def provider_workplace_messages(case_id: str, user: dict = Depends(require_auth)):
    _provider_access(user, case_id=case_id, writable=True)
    conn = get_db()
    case = conn.execute("SELECT c.company_id FROM workplace_support_cases c JOIN workplace_providers p ON p.company_id=c.company_id AND p.provider_id=c.provider_id AND p.status='active' JOIN institutions i ON i.id=c.company_id AND i.type='company' AND i.status='ACTIVE' WHERE c.id=? AND c.provider_id=? AND c.withdrawn_at IS NULL AND c.status IN ('open','active')", (case_id, user["id"])).fetchone()
    if not case:
        conn.close(); raise HTTPException(404, "Active workplace support case not found")
    rows = conn.execute("SELECT id,sender_id,body_encrypted,created_at FROM workplace_messages WHERE case_id=? ORDER BY created_at", (case_id,)).fetchall(); conn.close()
    return [{"id": r["id"], "from_me": r["sender_id"] == user["id"], "message": decrypt_pii(r["body_encrypted"]), "created_at": r["created_at"]} for r in rows]


@router.post("/provider/cases/{case_id}/messages", status_code=201)
async def send_provider_workplace_message(case_id: str, data: WorkplaceMessageBody, user: dict = Depends(require_auth)):
    _provider_access(user, case_id=case_id, writable=True)
    message = data.message
    conn = get_db()
    case = conn.execute("SELECT c.company_id,c.user_id FROM workplace_support_cases c JOIN workplace_providers p ON p.company_id=c.company_id AND p.provider_id=c.provider_id AND p.status='active' JOIN institutions i ON i.id=c.company_id AND i.type='company' AND i.status='ACTIVE' WHERE c.id=? AND c.provider_id=? AND c.withdrawn_at IS NULL AND c.status IN ('open','active')", (case_id, user["id"])).fetchone()
    if not case:
        conn.close(); raise HTTPException(404, "Active workplace support case not found")
    now = _now(); conn.execute("INSERT INTO workplace_messages (id,case_id,sender_id,body_encrypted,created_at) VALUES (?,?,?,?,?)", (str(uuid.uuid4()), case_id, user["id"], encrypt_pii(message.strip()), now))
    _audit(conn, case["company_id"], user["id"], "WORKPLACE_SUPPORT_MESSAGE_SENT"); conn.commit(); conn.close()
    from backend.database import create_notification
    create_notification(case["user_id"], "New provider message", "Your independent care provider sent you a private message.", "message")
    return {"ok": True, "created_at": now}


@router.get("/provider/appointments")
async def provider_workplace_appointments(user: dict = Depends(require_auth)):
    # A newly invited provider can sign in before any company has connected
    # them. In that state, their appointment list is simply empty. The query
    # below still scopes every row to an active workplace relationship.
    _provider_access(user, require_association=False)
    conn=get_db()
    rows=conn.execute("SELECT a.id,a.case_id,a.starts_at,a.mode,a.location_or_link_encrypted,a.status,a.created_at,u.name AS employee_name FROM workplace_appointments a JOIN workplace_support_cases c ON c.id=a.case_id AND c.provider_id=a.provider_id AND c.assignment_status='assigned' JOIN users u ON u.id=a.user_id JOIN workplace_providers p ON p.company_id=a.company_id AND p.provider_id=a.provider_id AND p.status='active' JOIN institutions i ON i.id=a.company_id AND i.type='company' AND i.status='ACTIVE' WHERE a.provider_id=? AND c.withdrawn_at IS NULL ORDER BY a.starts_at DESC",(user["id"],)).fetchall();conn.close()
    return [{"id":r["id"],"case_id":r["case_id"],"starts_at":r["starts_at"],"mode":r["mode"],"location_or_link":decrypt_pii(r["location_or_link_encrypted"]) if r["location_or_link_encrypted"] else None,"status":r["status"],"created_at":r["created_at"],"employee_name":r["employee_name"]} for r in rows]


@router.post("/provider/appointments/{appointment_id}/status")
async def update_workplace_appointment_status(appointment_id: str, data: WorkplaceAppointmentStatus, user: dict = Depends(require_auth)):
    assignment = get_db()
    case_row = assignment.execute("SELECT case_id FROM workplace_appointments WHERE id=? AND provider_id=?", (appointment_id, user["id"])).fetchone()
    assignment.close()
    if not case_row:
        raise HTTPException(404, "Scheduled workplace appointment not found")
    _provider_access(user, case_id=case_row["case_id"], writable=True)
    conn = get_db()
    row = conn.execute("SELECT a.company_id,a.user_id FROM workplace_appointments a JOIN workplace_support_cases c ON c.id=a.case_id AND c.withdrawn_at IS NULL JOIN workplace_providers p ON p.company_id=a.company_id AND p.provider_id=a.provider_id AND p.status='active' JOIN institutions i ON i.id=a.company_id AND i.type='company' AND i.status='ACTIVE' WHERE a.id=? AND a.provider_id=? AND a.status='scheduled'", (appointment_id, user["id"])).fetchone()
    if not row:
        conn.close(); raise HTTPException(404, "Scheduled workplace appointment not found")
    now=_now(); conn.execute("UPDATE workplace_appointments SET status=?,updated_at=? WHERE id=?", (data.status, now, appointment_id)); _audit(conn,row["company_id"],user["id"],f"WORKPLACE_APPOINTMENT_{data.status.upper()}"); conn.commit(); conn.close()
    from backend.database import create_notification
    create_notification(row["user_id"], "Workplace appointment updated", f"Your provider marked the appointment {data.status}.", "appointment")
    return {"ok": True, "status": data.status}
