"""Privacy-separated workplace wellbeing pilot APIs.

Company reporting is deliberately organization-wide and suppressed until at
least ten distinct employees have completed a check-in. There are no member
listing, filtering, or export endpoints for company administrators.
"""

import json
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
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

router = APIRouter(prefix="/api/v1/workplace", tags=["workplace"])
MIN_REPORT_COHORT = 10
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
    """Delete expired wellbeing/case content while preserving active care cases."""
    conn = get_db()
    now = datetime.now(timezone.utc)
    companies = conn.execute(
        "SELECT company_id,retention_days FROM workplace_settings"
    ).fetchall()
    purged_cases = 0
    purged_checkins = 0
    for company in companies:
        cutoff = (now - timedelta(days=max(1, int(company["retention_days"] or 365)))).isoformat()
        expired_cases = conn.execute(
            "SELECT id FROM workplace_support_cases WHERE company_id=? "
            "AND (status IN ('closed','withdrawn','expired') OR withdrawn_at IS NOT NULL) "
            "AND COALESCE(updated_at,created_at)<=?",
            (company["company_id"], cutoff),
        ).fetchall()
        for case in expired_cases:
            conn.execute("DELETE FROM workplace_support_cases WHERE id=?", (case["id"],))
        purged_cases += len(expired_cases)
        deleted_checkins = conn.execute(
            "DELETE FROM workplace_checkins WHERE company_id=? AND created_at<=? "
            "AND NOT EXISTS (SELECT 1 FROM workplace_support_cases c WHERE c.shared_checkin_id=workplace_checkins.id)",
            (company["company_id"], cutoff),
        ).rowcount
        purged_checkins += max(0, deleted_checkins)
        if expired_cases or deleted_checkins:
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
    conn.close()
    if not row or str(row["type"]).lower() != "company":
        raise HTTPException(403, "This account is not assigned to a workplace tenant")
    if str(row["status"] or "").upper() != "ACTIVE":
        raise HTTPException(403, "This workplace is not active")
    if str(user.get("status") or "approved").lower() not in {"approved", "active"}:
        raise HTTPException(403, "Your account is not active")
    if terms and user.get("workplace_terms_version") != WORKPLACE_ADMIN_TERMS_VERSION:
        raise HTTPException(403, "Accept the current workplace administrator terms before continuing")
    if owner and user.get("workplace_admin_role") != "owner":
        raise HTTPException(403, "Company owner access required")
    return user["institution_id"]


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
        "SELECT l.id,l.company_id,s.work_email_domains_json,s.privacy_notice_version "
        "FROM workplace_enrollment_links l JOIN workplace_settings s ON s.company_id=l.company_id "
        "JOIN institutions i ON i.id=l.company_id WHERE 1=1" + where + " "
        "AND i.type='company' AND i.status='ACTIVE' AND s.legal_review_complete=1 "
        "AND s.policy_status='approved' AND EXISTS (SELECT 1 FROM workplace_providers p "
        "JOIN workplace_provider_credentials c ON c.provider_id=p.provider_id "
        "JOIN users pu ON pu.id=p.provider_id WHERE p.company_id=l.company_id AND p.status='active' "
        "AND c.status='verified' AND pu.status IN ('approved','active')) LIMIT 1",
        params,
    ).fetchone()


def _provider_access(user: dict, *, case_id: str | None = None, writable: bool = False):
    """Single authorization path for current provider, tenant, credential and case scope."""
    if user.get("role_type") != "workplace_provider" or str(user.get("status") or "").lower() not in {"approved", "active"}:
        raise HTTPException(403, "Approved workplace provider access required")
    conn = get_db()
    base = (
        "SELECT c.id,c.company_id,c.user_id,c.provider_id,c.shared_checkin_id,c.status,c.withdrawn_at "
        "FROM workplace_support_cases c JOIN workplace_providers p ON p.company_id=c.company_id "
        "AND p.provider_id=c.provider_id AND p.status='active' "
        "JOIN workplace_provider_credentials pc ON pc.provider_id=p.provider_id AND pc.status='verified' "
        "JOIN users pu ON pu.id=p.provider_id AND pu.status IN ('approved','active') "
        "JOIN institutions i ON i.id=c.company_id AND i.type='company' AND i.status='ACTIVE' "
        "WHERE c.provider_id=? AND c.withdrawn_at IS NULL"
    )
    if case_id:
        clauses = " AND c.id=?"
        if writable:
            clauses += " AND c.status IN ('open','active')"
        row = conn.execute(base + clauses, (user["id"], case_id)).fetchone()
        conn.close()
        if not row:
            raise HTTPException(404, "Active workplace support case not found")
        return dict(row)
    valid = conn.execute(
        "SELECT 1 FROM users u JOIN workplace_provider_credentials pc ON pc.provider_id=u.id AND pc.status='verified' "
        "WHERE u.id=? AND u.role_type='workplace_provider' AND u.status IN ('approved','active')",
        (user["id"],),
    ).fetchone()
    conn.close()
    if not valid:
        raise HTTPException(403, "Verified workplace provider access required")
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
    professional_title: str = Field(min_length=2, max_length=160)
    qualification: str = Field(min_length=2, max_length=300)
    registration_number: str = Field(min_length=2, max_length=160)
    verification_reference: str = Field(min_length=4, max_length=500)


class CompanyCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    admin_name: str | None = Field(default=None, max_length=200)
    admin_email: EmailStr
    work_email_domains: list[str] = Field(min_length=1, max_length=20)
    privacy_contact_email: EmailStr | None = None
    employee_population_range: str | None = Field(default=None, max_length=80)
    retention_days: int = Field(default=365, ge=30, le=3650)


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
    link = conn.execute(
        "SELECT l.id, l.company_id, s.work_email_domains_json, s.privacy_notice_version "
        "FROM workplace_enrollment_links l JOIN workplace_settings s ON s.company_id = l.company_id "
        "JOIN institutions i ON i.id = l.company_id "
        "WHERE l.token_hash = ? AND l.revoked_at IS NULL AND (l.expires_at IS NULL OR l.expires_at > ?) "
        "AND i.type = 'company' AND i.status = 'ACTIVE' AND s.legal_review_complete = 1 "
        "AND s.policy_status = 'approved' AND EXISTS (SELECT 1 FROM workplace_providers p JOIN workplace_provider_credentials c ON c.provider_id=p.provider_id JOIN users pu ON pu.id=p.provider_id WHERE p.company_id=l.company_id AND p.status='active' AND c.status='verified' AND pu.status IN ('approved','active'))",
        (hash_token(data.token), _now()),
    ).fetchone()
    if not link:
        conn.close()
        raise HTTPException(400, "This enrollment link is invalid, expired, or revoked")
    try:
        domains = json.loads(link["work_email_domains_json"])
    except (ValueError, TypeError):
        domains = []
    if domain not in {str(d).lower().lstrip("@").strip() for d in domains}:
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
    account = conn.execute("SELECT email,role_type,user_category,institution_id,status FROM users WHERE id=?", (user["id"],)).fetchone()
    email = str(account["email"]).strip().lower()
    domains = {str(d).strip().lower().lstrip("@") for d in json.loads(link["work_email_domains_json"] or "[]")}
    if email.rsplit("@", 1)[-1] not in domains:
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
        "SELECT c.*,s.work_email_domains_json FROM workplace_existing_enrollment_challenges c "
        "JOIN workplace_settings s ON s.company_id=c.company_id JOIN workplace_enrollment_links l ON l.id=c.link_id "
        "JOIN institutions i ON i.id=c.company_id WHERE c.id=? AND c.user_id=? AND c.used_at IS NULL AND c.expires_at>? "
        "AND l.revoked_at IS NULL AND (l.expires_at IS NULL OR l.expires_at>?) AND i.type='company' AND i.status='ACTIVE' "
        "AND s.legal_review_complete=1 AND s.policy_status='approved' AND EXISTS (SELECT 1 FROM workplace_providers p "
        "JOIN workplace_provider_credentials pc ON pc.provider_id=p.provider_id JOIN users pu ON pu.id=p.provider_id "
        "WHERE p.company_id=c.company_id AND p.status='active' AND pc.status='verified' AND pu.status IN ('approved','active'))",
        (data.challenge_id, user["id"], now, now),
    ).fetchone()
    if not row:
        conn.rollback(); conn.close()
        raise HTTPException(400, "The verification code is invalid or expired")
    if not secrets.compare_digest(row["code_hash"], hash_token(data.code)):
        attempts = row["attempts_count"] + 1
        conn.execute("UPDATE workplace_existing_enrollment_challenges SET attempts_count=?,used_at=CASE WHEN ?>=5 THEN ? ELSE used_at END WHERE id=?", (attempts, attempts, now, data.challenge_id))
        conn.commit(); conn.close()
        raise HTTPException(400, "The verification code is invalid or expired")
    account = conn.execute("SELECT email,role_type,user_category,institution_id,status FROM users WHERE id=?", (user["id"],)).fetchone()
    domains = {str(d).strip().lower().lstrip("@") for d in json.loads(row["work_email_domains_json"] or "[]")}
    if not account or account["role_type"] != "student" or account["user_category"] != "adult" or account["institution_id"] or str(account["status"]).lower() not in {"approved", "active"} or str(account["email"]).strip().lower().rsplit("@", 1)[-1] not in domains:
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
        "SELECT i.id, i.name, i.status, s.work_email_domains_json, s.legal_review_complete, s.legal_review_reference, s.legal_reviewed_at, s.employee_population_range, s.retention_days, s.policy_status FROM institutions i JOIN workplace_settings s ON s.company_id = i.id WHERE i.type = 'company' ORDER BY i.name COLLATE NOCASE"
    ).fetchall()
    result = []
    for row in rows:
        admins = conn.execute("SELECT id,name,email,status FROM users WHERE institution_id=? AND role_type='company_admin' ORDER BY created_at LIMIT 10", (row["id"],)).fetchall()
        result.append({
            "id": row["id"], "name": row["name"], "status": row["status"],
            "approved_work_email_domains": json.loads(row["work_email_domains_json"]),
            "legal_review_complete": bool(row["legal_review_complete"]),
            "legal_review_reference": row["legal_review_reference"],
            "legal_reviewed_at": row["legal_reviewed_at"],
            "employee_population_range": row["employee_population_range"],
            "retention_days": row["retention_days"], "policy_status": row["policy_status"],
            "administrators": [dict(admin) for admin in admins],
        })
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
        "SELECT id FROM institutions WHERE id = ? AND type = 'company'", (company_id,)
    ).fetchone()
    if not company:
        conn.close()
        raise HTTPException(404, "Workplace company not found")
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
    providers = conn.execute("SELECT COUNT(*) AS n FROM workplace_providers p JOIN workplace_provider_credentials c ON c.provider_id=p.provider_id AND c.status='verified' JOIN users u ON u.id=p.provider_id WHERE p.company_id=? AND p.status='active' AND u.status IN ('approved','active')", (company_id,)).fetchone()["n"]
    links = conn.execute("SELECT COUNT(*) AS n FROM workplace_enrollment_links WHERE company_id=? AND revoked_at IS NULL AND (expires_at IS NULL OR expires_at>?)", (company_id, _now())).fetchone()["n"]
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
    elif not checks["administrator"]: readiness = "awaiting_administrator"
    elif not checks["privacy_review"]: readiness = "privacy_review_required"
    elif not checks["policy"] or not checks["provider"]: readiness = "provider_setup"
    elif not checks["enrollment_link"]: readiness = "enrollment_setup"
    else: readiness = "ready"
    return {
        "company": {"id": company_id, "name": company["name"], "status": company["status"]},
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
            "INSERT INTO workplace_provider_credentials (provider_id, title_encrypted, qualification_encrypted, registration_encrypted, verification_reference_encrypted, status, reviewed_by, reviewed_at) VALUES (?,?,?,?,?,'verified',?,?)",
            (
                provider["id"],
                encrypt_pii(data.professional_title.strip()),
                encrypt_pii(data.qualification.strip()),
                encrypt_pii(data.registration_number.strip()),
                encrypt_pii(data.verification_reference.strip()),
                actor["id"],
                now,
            ),
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
        "WORKPLACE_PROVIDER_CREDENTIAL_REVIEWED",
        "user",
        provider["id"],
        {"registration_reference_recorded": True},
    )
    return {
        "provider_enabled": True,
        "email": str(data.provider_email).lower(),
        "credential_reviewed_by": actor["id"],
        "reviewed_at": now,
        "note": "The entered verification reference records a human review; this endpoint does not validate a professional registry automatically.",
    }


@router.post("/enrollment/verify")
async def verify_enrollment(data: EnrollmentVerify):
    conn = get_db()
    challenge = conn.execute(
        "SELECT c.*, s.work_email_domains_json, s.privacy_notice_version FROM workplace_enrollment_challenges c "
        "JOIN workplace_settings s ON s.company_id = c.company_id "
        "JOIN workplace_enrollment_links l ON l.id = c.link_id AND l.company_id = c.company_id "
        "JOIN institutions i ON i.id = c.company_id "
        "WHERE c.id = ? AND c.used_at IS NULL AND c.expires_at > ? AND l.revoked_at IS NULL "
        "AND (l.expires_at IS NULL OR l.expires_at > ?) AND s.legal_review_complete = 1 "
        "AND s.policy_status = 'approved' AND i.type = 'company' AND i.status = 'ACTIVE' "
        "AND EXISTS (SELECT 1 FROM workplace_providers p JOIN workplace_provider_credentials pc ON pc.provider_id=p.provider_id JOIN users pu ON pu.id=p.provider_id WHERE p.company_id=c.company_id AND p.status='active' AND pc.status='verified' AND pu.status IN ('approved','active'))",
        (data.challenge_id, _now(), _now()),
    ).fetchone()
    if not challenge:
        conn.close()
        raise HTTPException(400, "The verification code is invalid or expired")
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
    if str(email).strip().lower().rsplit("@", 1)[-1] not in approved_domains:
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
    rows = conn.execute(
        "SELECT u.id, u.name, u.professional_title FROM workplace_providers p JOIN users u ON u.id = p.provider_id JOIN workplace_provider_credentials pc ON pc.provider_id=u.id AND pc.status='verified' WHERE p.company_id = ? AND p.status = 'active' AND u.status IN ('approved','active') ORDER BY u.name COLLATE NOCASE",
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
    membership = _employee(user)
    now = _now()
    conn = get_db()
    conn.execute(
        "INSERT INTO workplace_checkins (id, company_id, user_id, answers_json, created_at) VALUES (?,?,?,?,?)",
        (
            str(uuid.uuid4()),
            membership["company_id"],
            user["id"],
            encrypt_pii(json.dumps(data.model_dump())),
            now,
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
    if not provider or not provider_account:
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
        "INSERT INTO workplace_support_cases (id, company_id, user_id, provider_id, status, share_consent_at, shared_checkin_id, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
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
        "SELECT id, answers_json, created_at FROM workplace_checkins WHERE company_id = ? AND user_id = ? ORDER BY created_at DESC LIMIT 50",
        (membership["company_id"], user["id"]),
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        try:
            answers = json.loads(decrypt_pii(row["answers_json"]))
        except (ValueError, TypeError, RuntimeError):
            continue
        result.append(
            {"id": row["id"], "answers": answers, "created_at": row["created_at"]}
        )
    return result


@router.get("/support-requests")
async def own_workplace_support_requests(user: dict = Depends(require_auth)):
    membership = _employee(user)
    conn = get_db()
    rows = conn.execute(
        "SELECT id, status, created_at, withdrawn_at FROM workplace_support_cases WHERE company_id = ? AND user_id = ? ORDER BY created_at DESC",
        (membership["company_id"], user["id"]),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


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
    setup = conn.execute(
        "SELECT legal_review_complete, policy_status,work_email_domains_json FROM workplace_settings WHERE company_id = ?",
        (company_id,),
    ).fetchone()
    if not setup or not setup["legal_review_complete"]:
        conn.close()
        raise HTTPException(
            403,
            "A documented Kenyan legal/privacy review is required before enabling employee enrollment",
        )
    provider = conn.execute("SELECT 1 FROM workplace_providers p JOIN workplace_provider_credentials c ON c.provider_id=p.provider_id JOIN users u ON u.id=p.provider_id WHERE p.company_id=? AND p.status='active' AND c.status='verified' AND u.status IN ('approved','active') LIMIT 1", (company_id,)).fetchone()
    if setup["policy_status"] != "approved" or not provider:
        conn.close()
        raise HTTPException(403, "Complete company privacy policy and configure an operational independent provider before enabling enrollment")
    if not json.loads(setup["work_email_domains_json"] or "[]"):
        conn.close()
        raise HTTPException(403, "Add at least one approved work email domain before enabling enrollment")
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
    provider = conn.execute(
        "SELECT u.id FROM users u JOIN workplace_provider_credentials c ON c.provider_id = u.id AND c.status = 'verified' WHERE u.email = ? AND u.role_type = 'workplace_provider' AND u.status IN ('approved','active')",
        (str(data.provider_email).lower(),),
    ).fetchone()
    if not provider:
        conn.close()
        raise HTTPException(
            404, "No approved workplace provider is registered for that email"
        )
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
        "SELECT u.id, u.name, u.professional_title, p.status FROM workplace_providers p JOIN users u ON u.id = p.provider_id WHERE p.company_id = ? ORDER BY u.name COLLATE NOCASE",
        (company_id,),
    ).fetchall()
    result = [
        {
            "id": row["id"],
            "name": row["name"],
            "title": decrypt_pii(row["professional_title"])
            if str(row["professional_title"] or "").startswith("gcm1:")
            else row["professional_title"],
            "status": row["status"],
        }
        for row in rows
    ]
    conn.close()
    return result


@router.post("/admin/providers/{provider_id}/deactivate")
async def deactivate_provider(provider_id: str, user: dict = Depends(require_auth)):
    company_id = _company_admin(user)
    conn = get_db()
    cur = conn.execute(
        "UPDATE workplace_providers SET status = 'inactive' WHERE company_id = ? AND provider_id = ? AND status = 'active'",
        (company_id, provider_id),
    )
    if cur.rowcount:
        remaining = conn.execute("SELECT 1 FROM workplace_providers p JOIN workplace_provider_credentials c ON c.provider_id=p.provider_id JOIN users u ON u.id=p.provider_id WHERE p.company_id=? AND p.status='active' AND c.status='verified' AND u.status IN ('approved','active') LIMIT 1", (company_id,)).fetchone()
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
    row = conn.execute(
        "SELECT COUNT(DISTINCT c.user_id) AS people FROM workplace_checkins c JOIN workplace_memberships m ON m.company_id = c.company_id AND m.user_id = c.user_id WHERE c.company_id = ? AND m.status = 'active' AND m.withdrawn_at IS NULL",
        (company_id,),
    ).fetchone()
    if row["people"] < MIN_REPORT_COHORT:
        conn.close()
        return {
            "suppressed": True,
            "minimum_cohort": MIN_REPORT_COHORT,
            "message": "Aggregate reporting becomes available when at least 10 distinct employees have completed check-ins. No participation list is available.",
        }
    # Fixed organization-wide buckets only: no date, department, demographic, or other filters.
    rows = conn.execute(
        "SELECT c.user_id, c.answers_json FROM workplace_checkins c JOIN workplace_memberships m ON m.company_id = c.company_id AND m.user_id = c.user_id WHERE c.company_id = ? AND m.status = 'active' AND m.withdrawn_at IS NULL",
        (company_id,),
    ).fetchall()
    conn.close()
    aggregates = {"mood": 0, "stress": 0, "support_access": 0}
    totals = {key: 0 for key in aggregates}
    people: dict[str, dict[str, list[int]]] = {}
    for record in rows:
        try:
            answers = json.loads(decrypt_pii(record["answers_json"]))
        except (ValueError, TypeError, RuntimeError):
            continue
        person_answers = people.setdefault(
            record["user_id"], {key: [] for key in aggregates}
        )
        for key in aggregates:
            if isinstance(answers.get(key), int):
                person_answers[key].append(answers[key])
    for person_answers in people.values():
        for key, values in person_answers.items():
            if values:
                aggregates[key] += sum(values) / len(values)
                totals[key] += 1
    return {
        "suppressed": False,
        "cohort_size": "10+",
        "checkins": "10+",
        "averages": {
            key: round(aggregates[key] / totals[key], 1)
            if totals[key] >= MIN_REPORT_COHORT
            else None
            for key in aggregates
        },
        "scope": "whole workplace only; no filters or export",
    }


@router.get("/admin/report/trends")
async def workplace_aggregate_trends(user: dict = Depends(require_auth)):
    company_id = _company_admin(user)
    conn = get_db()
    rows = conn.execute(
        "SELECT substr(c.created_at,1,7) AS period,c.user_id,c.answers_json FROM workplace_checkins c JOIN workplace_memberships m ON m.company_id=c.company_id AND m.user_id=c.user_id WHERE c.company_id=? AND m.status='active' AND m.withdrawn_at IS NULL ORDER BY period",
        (company_id,),
    ).fetchall()
    conn.close()
    periods: dict[str, dict[str, list[dict]]] = {}
    for row in rows:
        try: answers = json.loads(decrypt_pii(row["answers_json"]))
        except (ValueError, TypeError, RuntimeError): continue
        periods.setdefault(row["period"], {}).setdefault(row["user_id"], []).append(answers)
    output = []
    for period, people in sorted(periods.items()):
        if len(people) < MIN_REPORT_COHORT:
            continue
        averages = {}
        for key in ("mood", "stress", "support_access"):
            person_values = []
            for answers in people.values():
                values = [a[key] for a in answers if isinstance(a.get(key), int)]
                if values: person_values.append(sum(values) / len(values))
            averages[key] = round(sum(person_values) / len(person_values), 1) if len(person_values) >= MIN_REPORT_COHORT else None
        output.append({"period": period, "suppressed": False, "cohort_size": "10+", "averages": averages})
    return {
        "scope": "fixed whole-company monthly periods",
        "suppressed": not bool(output),
        "minimum_cohort": MIN_REPORT_COHORT,
        "message": "Monthly trends are unavailable until at least 10 distinct employees contribute in a period." if not output else None,
        "periods": output,
    }


@router.get("/provider/cases")
async def provider_cases(user: dict = Depends(require_auth)):
    _provider_access(user)
    conn = get_db()
    rows = conn.execute(
        "SELECT c.id, c.company_id, c.user_id, c.shared_checkin_id, c.status, c.created_at, u.name, u.email FROM workplace_support_cases c JOIN users u ON u.id = c.user_id JOIN workplace_providers p ON p.company_id = c.company_id AND p.provider_id = c.provider_id AND p.status = 'active' JOIN institutions i ON i.id=c.company_id AND i.type='company' AND i.status='ACTIVE' WHERE c.provider_id = ? AND c.withdrawn_at IS NULL ORDER BY c.created_at DESC",
        (user["id"],),
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
    case = conn.execute("SELECT c.id,c.status,c.created_at,u.name,u.email FROM workplace_support_cases c JOIN users u ON u.id=c.user_id JOIN workplace_providers p ON p.company_id=c.company_id AND p.provider_id=c.provider_id AND p.status='active' JOIN institutions i ON i.id=c.company_id AND i.type='company' AND i.status='ACTIVE' WHERE c.id=? AND c.provider_id=? AND c.withdrawn_at IS NULL", (case_id, user["id"])).fetchone()
    if not case:
        conn.close(); raise HTTPException(404, "Active workplace case not found")
    notes = conn.execute("SELECT id,private_note_encrypted,employee_update_encrypted,shared_at,created_at FROM workplace_case_notes WHERE case_id=? AND provider_id=? ORDER BY created_at DESC", (case_id, user["id"])).fetchall()
    conn.close()
    return {"case": dict(case), "notes": [{"id": n["id"], "private_note": decrypt_pii(n["private_note_encrypted"]), "employee_update": decrypt_pii(n["employee_update_encrypted"]) if n["employee_update_encrypted"] else None, "shared_at": n["shared_at"], "created_at": n["created_at"]} for n in notes]}


@router.post("/provider/cases/{case_id}/notes", status_code=201)
async def create_workplace_case_note(case_id: str, data: WorkplaceCaseNoteCreate, user: dict = Depends(require_auth)):
    _provider_access(user, case_id=case_id, writable=True)
    conn = get_db()
    case = conn.execute("SELECT c.company_id,c.user_id FROM workplace_support_cases c JOIN workplace_providers p ON p.company_id=c.company_id AND p.provider_id=c.provider_id AND p.status='active' JOIN institutions i ON i.id=c.company_id AND i.type='company' AND i.status='ACTIVE' WHERE c.id=? AND c.provider_id=? AND c.withdrawn_at IS NULL AND c.status IN ('open','active')", (case_id, user["id"])).fetchone()
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
    now=_now();conn.execute("UPDATE workplace_support_cases SET status='closed',updated_at=? WHERE id=?",(now,case_id));_audit(conn,row["company_id"],user["id"],"WORKPLACE_CASE_CLOSED");conn.commit();conn.close()
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
    case = conn.execute("SELECT c.provider_id,c.company_id FROM workplace_support_cases c JOIN workplace_providers p ON p.company_id=c.company_id AND p.provider_id=c.provider_id AND p.status='active' JOIN workplace_provider_credentials pc ON pc.provider_id=c.provider_id AND pc.status='verified' JOIN users u ON u.id=c.provider_id AND u.status IN ('approved','active') JOIN institutions i ON i.id=c.company_id AND i.type='company' AND i.status='ACTIVE' WHERE c.id=? AND c.user_id=? AND c.company_id=? AND c.withdrawn_at IS NULL AND c.status IN ('open','active')", (data.case_id, user["id"], membership["company_id"])).fetchone()
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
    _provider_access(user)
    conn=get_db()
    rows=conn.execute("SELECT a.id,a.case_id,a.starts_at,a.mode,a.location_or_link_encrypted,a.status,a.created_at,u.name AS employee_name FROM workplace_appointments a JOIN workplace_support_cases c ON c.id=a.case_id JOIN users u ON u.id=a.user_id JOIN workplace_providers p ON p.company_id=a.company_id AND p.provider_id=a.provider_id AND p.status='active' JOIN institutions i ON i.id=a.company_id AND i.type='company' AND i.status='ACTIVE' WHERE a.provider_id=? AND c.withdrawn_at IS NULL ORDER BY a.starts_at DESC",(user["id"],)).fetchall();conn.close()
    return [{"id":r["id"],"case_id":r["case_id"],"starts_at":r["starts_at"],"mode":r["mode"],"location_or_link":decrypt_pii(r["location_or_link_encrypted"]) if r["location_or_link_encrypted"] else None,"status":r["status"],"created_at":r["created_at"],"employee_name":r["employee_name"]} for r in rows]


@router.post("/provider/appointments/{appointment_id}/status")
async def update_workplace_appointment_status(appointment_id: str, data: WorkplaceAppointmentStatus, user: dict = Depends(require_auth)):
    _provider_access(user)
    conn = get_db()
    row = conn.execute("SELECT a.company_id,a.user_id FROM workplace_appointments a JOIN workplace_support_cases c ON c.id=a.case_id AND c.withdrawn_at IS NULL JOIN workplace_providers p ON p.company_id=a.company_id AND p.provider_id=a.provider_id AND p.status='active' JOIN institutions i ON i.id=a.company_id AND i.type='company' AND i.status='ACTIVE' WHERE a.id=? AND a.provider_id=? AND a.status='scheduled'", (appointment_id, user["id"])).fetchone()
    if not row:
        conn.close(); raise HTTPException(404, "Scheduled workplace appointment not found")
    now=_now(); conn.execute("UPDATE workplace_appointments SET status=?,updated_at=? WHERE id=?", (data.status, now, appointment_id)); _audit(conn,row["company_id"],user["id"],f"WORKPLACE_APPOINTMENT_{data.status.upper()}"); conn.commit(); conn.close()
    from backend.database import create_notification
    create_notification(row["user_id"], "Workplace appointment updated", f"Your provider marked the appointment {data.status}.", "appointment")
    return {"ok": True, "status": data.status}
