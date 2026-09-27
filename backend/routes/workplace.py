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

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from backend.auth import hash_password, require_auth
from backend.database import consume_rate_limit, create_institution, get_db, write_audit
from backend.services.crypto import decrypt_pii, encrypt_pii, hash_email, hash_token
from backend.services.email_sender import send_html_email

router = APIRouter(prefix="/api/v1/workplace", tags=["workplace"])
MIN_REPORT_COHORT = 10
NOTICE_VERSION = "workplace-v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _audit(conn, company_id: str, actor_id: str | None, event: str) -> None:
    conn.execute(
        "INSERT INTO workplace_audit_events (id, company_id, actor_user_id, event_type, occurred_at) VALUES (?,?,?,?,?)",
        (str(uuid.uuid4()), company_id, actor_id, event, _now()),
    )


def _company_admin(user: dict) -> str:
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
    return user["institution_id"]


def _employee(user: dict) -> dict:
    if user.get("role_type") != "workplace_employee":
        raise HTTPException(403, "Workplace employee access required")
    if str(user.get("status") or "").lower() not in {"approved", "active"}:
        raise HTTPException(403, "Your workplace account is not active")
    conn = get_db()
    row = conn.execute(
        "SELECT m.* FROM workplace_memberships m WHERE m.user_id = ? AND m.status = 'active' AND m.withdrawn_at IS NULL",
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


class EnrollmentVerify(BaseModel):
    challenge_id: str
    code: str = Field(min_length=6, max_length=6, pattern=r"^[0-9]{6}$")


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
    admin_email: EmailStr
    work_email_domains: list[str] = Field(min_length=1, max_length=20)


class LegalReviewRecord(BaseModel):
    reviewed: bool
    reference: str = Field(min_length=4, max_length=500)


@router.post("/enrollment/start", status_code=202)
async def start_enrollment(data: EnrollmentStart, request: Request):
    """Start a private opt-in. Email ownership is verified before account creation."""
    if not data.accepted_notice:
        raise HTTPException(400, "You must accept the voluntary participation notice")
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
        "AND i.type = 'company' AND i.status = 'ACTIVE' AND s.legal_review_complete = 1",
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
            409, "An account already exists for this email. Sign in or contact support."
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


@router.post("/admin/companies", status_code=201)
async def create_workplace_company(
    data: CompanyCreate, actor: dict = Depends(require_auth)
):
    """Global-admin setup; named employee roster and participation list are not created."""
    if actor.get("role_type") != "admin":
        raise HTTPException(403, "Global administrator access required")
    domains = sorted({d.strip().lower().lstrip("@") for d in data.work_email_domains})
    if any(
        not d
        or len(d) > 253
        or not re.fullmatch(
            r"(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", d
        )
        for d in domains
    ):
        raise HTTPException(400, "Enter valid company email domains")
    conn = get_db()
    admin = conn.execute(
        "SELECT * FROM users WHERE email = ?", (str(data.admin_email).lower(),)
    ).fetchone()
    conn.close()
    if (
        not admin
        or admin["role_type"] != "student"
        or dict(admin).get("institution_id")
        or dict(admin).get("user_category") != "adult"
        or dict(admin).get("status") not in {"approved", "active"}
        or str(data.admin_email).lower().rsplit("@", 1)[-1] not in domains
    ):
        raise HTTPException(
            400,
            "The designated company admin must have an existing independent adult account and cannot already belong to a school or staff role",
        )
    company = create_institution(data.name.strip(), "company", actor["id"])
    now = _now()
    conn = get_db()
    try:
        conn.execute(
            "UPDATE institutions SET status = 'ACTIVE' WHERE id = ?", (company["id"],)
        )
        conn.execute(
            "INSERT INTO workplace_settings (company_id, work_email_domains_json, privacy_notice_version, provider_service_enabled, created_at, updated_at) VALUES (?,?,?,0,?,?)",
            (company["id"], json.dumps(domains), NOTICE_VERSION, now, now),
        )
        conn.execute(
            "UPDATE users SET role_type = 'company_admin', user_category = 'company_staff', institution_id = ?, terms_accepted_at = NULL WHERE id = ?",
            (company["id"], admin["id"]),
        )
        _audit(conn, company["id"], actor["id"], "WORKPLACE_COMPANY_CREATED")
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise HTTPException(500, "Unable to configure the workplace tenant")
    conn.close()
    return {
        "id": company["id"],
        "name": company["name"],
        "status": "ACTIVE",
        "admin_email": str(data.admin_email).lower(),
        "approved_work_email_domains": domains,
        "readiness": "legal_privacy_review_required",
        "legal_review_complete": False,
    }


@router.get("/admin/companies")
async def list_workplace_companies(actor: dict = Depends(require_auth)):
    if actor.get("role_type") != "admin":
        raise HTTPException(403, "Global administrator access required")
    conn = get_db()
    rows = conn.execute(
        "SELECT i.id, i.name, i.status, s.work_email_domains_json, s.legal_review_complete, s.legal_review_reference, s.legal_reviewed_at FROM institutions i JOIN workplace_settings s ON s.company_id = i.id WHERE i.type = 'company' ORDER BY i.name COLLATE NOCASE"
    ).fetchall()
    conn.close()
    return [
        {
            "id": row["id"],
            "name": row["name"],
            "status": row["status"],
            "approved_work_email_domains": json.loads(row["work_email_domains_json"]),
            "legal_review_complete": bool(row["legal_review_complete"]),
            "legal_review_reference": row["legal_review_reference"],
            "legal_reviewed_at": row["legal_reviewed_at"],
        }
        for row in rows
    ]


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
    return {"review_recorded": True, "enrollment_enabled": True}


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
        "AND (l.expires_at IS NULL OR l.expires_at > ?) AND s.legal_review_complete = 1 AND i.status = 'ACTIVE'",
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
            "UPDATE users SET status = 'approved', user_category = 'workplace_employee', onboarding_completed_at = ? WHERE id = ?",
            (now, user_id),
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
        "SELECT u.id, u.name, u.professional_title FROM workplace_providers p JOIN users u ON u.id = p.provider_id WHERE p.company_id = ? AND p.status = 'active' AND u.status IN ('approved','active') ORDER BY u.name COLLATE NOCASE",
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
        "SELECT email FROM users WHERE id = ? AND role_type = 'workplace_provider' AND status IN ('approved','active')",
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
        "SELECT legal_review_complete FROM workplace_settings WHERE company_id = ?",
        (company_id,),
    ).fetchone()
    if not setup or not setup["legal_review_complete"]:
        conn.close()
        raise HTTPException(
            403,
            "A documented Kenyan legal/privacy review is required before enabling employee enrollment",
        )
    link_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO workplace_enrollment_links (id, company_id, token_hash, created_by, created_at) VALUES (?,?,?,?,?)",
        (link_id, company_id, hash_token(token), user["id"], _now()),
    )
    _audit(conn, company_id, user["id"], "ENROLLMENT_LINK_CREATED")
    conn.commit()
    conn.close()
    # This is the only time the cleartext link is returned. No redemption data is exposed.
    return {"id": link_id, "token": token, "revocable": True}


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


@router.get("/provider/cases")
async def provider_cases(user: dict = Depends(require_auth)):
    if user.get("role_type") != "workplace_provider" or str(
        user.get("status") or ""
    ).lower() not in {"approved", "active"}:
        raise HTTPException(403, "Approved workplace provider access required")
    conn = get_db()
    rows = conn.execute(
        "SELECT c.id, c.company_id, c.user_id, c.shared_checkin_id, c.status, c.created_at, u.name, u.email FROM workplace_support_cases c JOIN users u ON u.id = c.user_id JOIN workplace_providers p ON p.company_id = c.company_id AND p.provider_id = c.provider_id AND p.status = 'active' WHERE c.provider_id = ? AND c.withdrawn_at IS NULL ORDER BY c.created_at DESC",
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
