"""
Consent state machine operations.
Valid transitions:
  DRAFT -> PENDING (dispatch)
  PENDING -> VIEWED (token opened)
  PENDING|VIEWED -> ACCEPTED (accepted)
  PENDING|VIEWED -> DECLINED (declined)
  PENDING|VIEWED -> EXPIRED (TTL elapsed - checked on read)
  PENDING|VIEWED -> INVALID (undeliverable / bounced at the ESP)
  INVALID -> PENDING (re-dispatch)
  ACCEPTED -> REVOKED (revoked)
  ACCEPTED -> RENEWAL_DUE (auto on expiry)
"""
import hmac
import json
import logging
import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from backend.database import (
    create_consent,
    create_consent_event,
    create_user,
    enqueue_email,
    get_consent_by_id,
    get_consent_events,
    get_consents_by_student,
    get_user_by_email,
    get_user_by_id,
    link_parent_guardian,
    get_all_consents,
    get_institution_id_for_consent,
    get_institution_by_id,
    get_active_consent_template,
    mark_analyses_consent_withdrawn,
    set_student_current_consent,
    set_user_invitation,
    update_user_onboarding,
    update_student,
    update_consent_status,
    write_audit,
)
from backend.config import CONSENT_EXPIRY_DAYS, CONSENT_REMINDER_DAYS
from backend.services.crypto import create_signed_token, hash_token, verify_signed_token, decrypt_pii
from backend.services.email_sender import send_html_email
from backend.services.email_templates import (
    admin_consent_notification,
    consent_confirmation,
    consent_reminder,
    parent_consent_request,
    render_consent_request_from_template,
    student_consent_request,
    student_courtesy_copy,
    CONSENT_TEMPLATE_VERSION,
)

logger = logging.getLogger(__name__)

# Maximum portal page loads a single consent link allows (Delivery Brief §5).
MAX_CONSENT_VIEWS = 20

# Bulk roster dispatch runs with a write-ahead outbox: consent/courtesy emails
# are enqueued (fast, durable) and delivered by the background worker instead of
# blocking the request on per-recipient ESP round-trips (Remediation P1-1).
_bulk_enqueue = False


@contextmanager
def bulk_enqueue_mode():
    """Context where consent emails are enqueued instead of sent synchronously."""
    global _bulk_enqueue
    previous = _bulk_enqueue
    _bulk_enqueue = True
    try:
        yield
    finally:
        _bulk_enqueue = previous


def _dispatch_email(
    to_email: str,
    subject: str,
    body_html: str,
    related_type: str | None = None,
    related_id: str | None = None,
    metadata: dict | None = None,
) -> tuple[bool, str]:
    """Route a message through the outbox: enqueue-only during bulk, else sync.

    Under ``bulk_enqueue_mode`` the message is persisted to ``email_outbox`` and
    returned as accepted — delivery happens in the background worker. Otherwise
    it is sent synchronously via ``send_html_email`` (write-ahead + immediate
    attempt, with an ``email_events`` trail).
    """
    if _bulk_enqueue:
        try:
            enqueue_email(
                to_email, subject, body_html,
                related_type=related_type, related_id=related_id, metadata=metadata,
            )
        except Exception as exc:
            logger.warning("outbox enqueue failed for %s: %s", to_email, exc)
            return False, str(exc)
        return True, ""
    return send_html_email(
        to_email, subject, body_html,
        related_type=related_type, related_id=related_id, metadata=metadata,
    )

CONSENT_TRANSITIONS = {
    "DRAFT":       ["PENDING"],
    "PENDING":     ["VIEWED", "ACCEPTED", "DECLINED", "EXPIRED", "INVALID"],
    "VIEWED":      ["ACCEPTED", "DECLINED", "EXPIRED", "INVALID"],
    "ACCEPTED":    ["REVOKED", "RENEWAL_DUE"],
    "DECLINED":    ["PENDING"],  # re-dispatch
    "EXPIRED":     ["PENDING"],  # re-dispatch
    "INVALID":     ["PENDING"],  # re-dispatch after address corrected
    "REVOKED":     [],
    "RENEWAL_DUE": ["PENDING"],
}


def _consent_url(token: str) -> str:
    base_url = os.getenv("APP_BASE_URL") or os.getenv("FRONTEND_URL") or "http://localhost:5173"
    return f"{base_url.rstrip('/')}/consent/{token}"


def verify_consent_token(consent: dict, token: str) -> bool:
    """Validate a portal token against the consent record.

    Signed tokens (``v1.``) are verified by HMAC signature and must match the
    stored SHA-256 hash (the raw token is never persisted; a re-dispatch
    invalidates earlier links). Legacy plain-UUID tokens are accepted for
    backwards compatibility with pre-M3 records.
    """
    token = str(token or "")
    if not token:
        return False
    if token.startswith("v1."):
        if not verify_signed_token(token, consent["id"]):
            return False
        expected = consent.get("signed_token_hash") or ""
        return bool(expected) and hmac.compare_digest(hash_token(token), expected)
    return len(consent.get("magic_token") or "") == 36 and hmac.compare_digest(
        consent.get("magic_token") or "", token
    )


def view_count(consent_id: str) -> int:
    """Number of times the consent portal has been opened."""
    events = get_consent_events(consent_id) or []
    return sum(1 for e in events if e.get("event_type") == "viewed")


def remaining_views(consent_id: str) -> int:
    return max(0, MAX_CONSENT_VIEWS - view_count(consent_id))


def _send_consent_email(consent: dict, reminder: bool = False, token: str | None = None) -> tuple[bool, str, str]:
    """Send a consent request email, honouring the institution's active template.

    When the consent's institution has an active ``consent_templates`` row the
    stored HTML is used (with context tokens substituted); otherwise the
    built-in §4.1/§4.2 template is used. Returns (ok, error, url).
    """
    token = token or consent.get("magic_token") or ""
    url = _consent_url(token)
    institution_id = get_institution_id_for_consent(consent["id"])
    template = get_active_consent_template(institution_id)
    template_version = (template or {}).get("version") or CONSENT_TEMPLATE_VERSION

    # Persist which template version rendered this request (drawer shows it).
    if (consent.get("template_version") or "") != template_version:
        consent = update_consent_status(consent["id"], consent["status"], template_version=template_version) or consent

    context = {
        "institution_name": consent.get("notes") or "your school",
        "student_first_name": _student_first_name(consent),
        "parent_first_name": consent.get("recipient_role") == "parent" and _parent_first_name(consent) or "Parent/Guardian",
        "counsellor_email": _counsellor_email(consent),
        "consent_url": url,
    }
    context.update(_footer_urls(token))

    subject_prefix = "Reminder: " if reminder else ""
    if reminder:
        subject, body_html = consent_reminder(context, day=_reminder_day(consent))
    elif template and not reminder:
        subject, body_html = render_consent_request_from_template(
            template, context, recipient_role=consent.get("recipient_role", "student")
        )
    elif consent.get("recipient_role") == "parent":
        subject, body_html = parent_consent_request(context)
    else:
        subject, body_html = student_consent_request(context)
    subject = subject_prefix + subject

    ok, error = _dispatch_email(
        consent["recipient_email"],
        subject,
        body_html,
        related_type="consent",
        related_id=consent["id"],
        metadata={"kind": "reminder" if reminder else "consent_request", "template_version": template_version},
    )
    return ok, error, url


def check_and_expire(consent: dict) -> dict:
    """If PENDING/VIEWED and past expires_at, flip to EXPIRED."""
    if consent["status"] not in ("PENDING", "VIEWED"):
        return consent
    expires = consent.get("expires_at")
    if expires and datetime.now(timezone.utc).isoformat() > expires:
        consent = update_consent_status(consent["id"], "EXPIRED") or consent
    return consent


def mark_consent_invalid(consent_id: str, reason: str | None = None) -> dict | None:
    """Flip a PENDING/VIEWED consent to INVALID (undeliverable / bounced).

    Called from the ESP webhook pipeline when a consent request bounces: the
    request never reached the recipient, so it must not sit PENDING indefinitely.
    An INVALID consent can be re-dispatched once the address is corrected.
    """
    consent = get_consent_by_id(consent_id)
    if not consent:
        return None
    if consent["status"] not in ("PENDING", "VIEWED"):
        return consent
    updated = update_consent_status(consent_id, "INVALID")
    write_audit(
        None, "system", "CONSENT_INVALIDATED", "consent", consent_id,
        payload={"reason": reason}, ip=None,
    )
    create_consent_event(
        consent_id, "bounced", actor_type="system",
        metadata={"reason": reason, "to_status": "INVALID"},
    )
    return updated


def dispatch_consent(consent_id: str, actor_id: str, ip: str | None = None) -> dict:
    """Transition DRAFT/DECLINED/EXPIRED/RENEWAL_DUE -> PENDING.

    Generates a fresh magic token, refreshes expires_at, and records dispatched_at.
    """
    consent = get_consent_by_id(consent_id)
    if not consent:
        raise ValueError("Consent not found")
    consent = check_and_expire(consent)
    allowed = CONSENT_TRANSITIONS.get(consent["status"], [])
    if "PENDING" not in allowed:
        raise ValueError(f"Cannot dispatch consent in status {consent['status']}")

    now = datetime.now(timezone.utc)
    token = create_signed_token(consent_id)
    updated = update_consent_status(
        consent_id,
        "PENDING",
        signed_token_hash=hash_token(token),
        magic_token_expires_at=(now + timedelta(days=CONSENT_EXPIRY_DAYS)).isoformat(),
        expires_at=(now + timedelta(days=CONSENT_EXPIRY_DAYS)).isoformat(),
        template_version=CONSENT_TEMPLATE_VERSION,
        dispatched_at=now.isoformat(),
    )
    updated["magic_token"] = token
    write_audit(
        actor_id,
        "counsellor",
        "CONSENT_DISPATCHED",
        "consent",
        consent_id,
        payload={"recipient": consent["recipient_email"]},
        ip=ip,
    )
    email_sent, email_error, url = _send_consent_email(updated)
    write_audit(
        actor_id,
        "counsellor",
        "CONSENT_EMAIL_SENT" if email_sent else "CONSENT_EMAIL_FAILED",
        "consent",
        consent_id,
        payload={"recipient": updated["recipient_email"], "error": email_error, "url": url},
        ip=ip,
    )
    updated["email_sent"] = email_sent
    updated["email_error"] = email_error
    updated["consent_url"] = url
    return updated


def remind_consent(consent_id: str, actor_id: str, ip: str | None = None) -> dict:
    consent = get_consent_by_id(consent_id)
    if not consent:
        raise ValueError("Consent not found")
    consent = check_and_expire(consent)
    if consent["status"] not in ("PENDING", "VIEWED"):
        raise ValueError(f"Cannot send reminder for consent in status {consent['status']}")

    token = create_signed_token(consent_id)
    consent = update_consent_status(
        consent_id, consent["status"], signed_token_hash=hash_token(token),
    ) or consent

    email_sent, email_error, url = _send_consent_email(consent, reminder=True, token=token)
    write_audit(
        actor_id,
        "counsellor",
        "CONSENT_REMINDER_SENT" if email_sent else "CONSENT_REMINDER_FAILED",
        "consent",
        consent_id,
        payload={"recipient": consent["recipient_email"], "error": email_error, "url": url},
        ip=ip,
    )
    consent["email_sent"] = email_sent
    consent["email_error"] = email_error
    consent["consent_url"] = url
    return consent


def record_view(consent_id: str, ip: str | None = None, user_agent: str | None = None) -> dict:
    """Record that the consent link was opened (PENDING -> VIEWED)."""
    consent = get_consent_by_id(consent_id)
    if not consent:
        raise ValueError("Consent not found")
    consent = check_and_expire(consent)
    if consent["status"] == "PENDING":
        now = datetime.now(timezone.utc).isoformat()
        consent = update_consent_status(
            consent_id, "VIEWED", viewed_at=now, response_ip=ip,
            response_user_agent=user_agent,
        )
        write_audit(None, "recipient", "CONSENT_VIEWED", "consent", consent_id, ip=ip)
    create_consent_event(consent_id, "viewed", actor_type="recipient", metadata={"ip": ip, "user_agent": user_agent})
    return consent


def accept_consent(
    consent_id: str,
    signature_name: str,
    ip: str,
    platforms: list | None = None,
    user_agent: str | None = None,
    token: str | None = None,
    social_accounts: dict | None = None,
) -> dict:
    """Transition PENDING/VIEWED -> ACCEPTED with signature and optional platform list."""
    consent = get_consent_by_id(consent_id)
    if not consent:
        raise ValueError("Consent not found")
    consent = check_and_expire(consent)
    if consent["status"] not in ("PENDING", "VIEWED"):
        raise ValueError(f"Cannot accept consent in status {consent['status']}")

    now = datetime.now(timezone.utc).isoformat()
    try:
        original_platforms = set(json.loads(consent.get("platforms_json") or "[]"))
    except Exception:
        original_platforms = set()
    if platforms is not None:
        if set(platforms) - original_platforms:
            raise ValueError(f"Invalid platforms: {', '.join(sorted(set(platforms) - original_platforms))}")
    final_platforms = platforms if platforms is not None else json.loads(
        consent.get("platforms_json") or "[]"
    )
    expiry = (
        datetime.now(timezone.utc) + timedelta(days=CONSENT_EXPIRY_DAYS)
    ).isoformat()
    updated = update_consent_status(
        consent_id,
        "ACCEPTED",
        signature_name=signature_name,
        signature_ip=ip,
        accepted_at=now,
        expires_at=expiry,
        response_ip=ip,
        response_user_agent=user_agent,
        platforms_json=json.dumps(final_platforms),
    )
    write_audit(
        None,
        "recipient",
        "CONSENT_ACCEPTED",
        "consent",
        consent_id,
        payload={"signature": signature_name, "user_agent": user_agent},
        ip=ip,
    )
    create_consent_event(consent_id, "accepted", actor_type="recipient",
                         metadata={"signature": signature_name, "ip": ip, "user_agent": user_agent})
    
    # Save social accounts if provided (only if consent is accepted)
    if social_accounts and consent.get("student_id"):
        from backend.database import save_social_account
        for platform, handle in social_accounts.items():
            if handle and platform in final_platforms:
                save_social_account(consent["student_id"], platform, handle, None)
    
    _notify_consent_response(updated, accepted=True, token=token)
    if updated.get("recipient_role") == "parent":
        parent = get_user_by_email(updated.get("recipient_email") or "")
        if parent and (parent.get("role_type") == "parent" or parent.get("user_category") == "parent"):
            link_parent_guardian(updated["student_id"], parent["id"])
            write_audit(parent["id"], "parent", "PARENT_LINKED_TO_STUDENT", "user", updated["student_id"], payload={"consent_id": consent_id}, ip=ip)
    return updated


def decline_consent(consent_id: str, ip: str | None = None, user_agent: str | None = None, token: str | None = None) -> dict:
    """Transition PENDING/VIEWED -> DECLINED."""
    consent = get_consent_by_id(consent_id)
    if not consent:
        raise ValueError("Consent not found")
    consent = check_and_expire(consent)
    if consent["status"] not in ("PENDING", "VIEWED"):
        raise ValueError(f"Cannot decline consent in status {consent['status']}")

    now = datetime.now(timezone.utc).isoformat()
    updated = update_consent_status(
        consent_id, "DECLINED", declined_at=now, response_ip=ip, response_user_agent=user_agent,
    )
    write_audit(None, "recipient", "CONSENT_DECLINED", "consent", consent_id, ip=ip)
    create_consent_event(consent_id, "declined", actor_type="recipient",
                         metadata={"ip": ip, "user_agent": user_agent})
    _notify_consent_response(updated, accepted=False, token=token)
    return updated


def record_consent_decision(
    consent_id: str,
    actor_id: str,
    decision: str,
    signature_name: str | None = None,
    ip: str | None = None,
) -> dict:
    """Record the consent decision from the tracker on behalf of the recipient.

    Used for paper/verbal consent collected outside the portal: the counsellor
    logs what the recipient decided, with the outcome, signature name (when
    provided) and actor written to the immutable audit trail. Valid from any
    dispatchable or pending-like state; record the decision against the same
    state machine the portal uses so downstream gating stays truthful.

    ``decision`` must be "ACCEPTED" or "DECLINED".
    """
    decision = (decision or "").strip().upper()
    if decision not in ("ACCEPTED", "DECLINED"):
        raise ValueError("decision must be 'ACCEPTED' or 'DECLINED'")

    consent = get_consent_by_id(consent_id)
    if not consent:
        raise ValueError("Consent not found")
    consent = check_and_expire(consent)
    if consent["status"] not in ("PENDING", "VIEWED", "DRAFT", "DECLINED", "EXPIRED", "INVALID", "RENEWAL_DUE"):
        raise ValueError(f"Cannot record a decision for consent in status {consent['status']}")

    # Portal dispatch semantics: a decision can only be recorded against a
    # request that was actually sent (or is being re-sent as part of the same
    # flow). DRAFT/DECLINED/EXPIRED/INVALID/RENEWAL_DUE go through dispatch
    # first so a fresh signed link exists for the recipient to change their mind.
    if consent["status"] != "PENDING" and consent["status"] != "VIEWED":
        consent = dispatch_consent(consent_id, actor_id=actor_id, ip=ip)

    now = datetime.now(timezone.utc).isoformat()
    signature = (signature_name or "").strip() or "Recorded by counsellor"
    if decision == "ACCEPTED":
        expiry = (datetime.now(timezone.utc) + timedelta(days=CONSENT_EXPIRY_DAYS)).isoformat()
        updated = update_consent_status(
            consent_id,
            "ACCEPTED",
            signature_name=signature,
            signature_ip=ip,
            accepted_at=now,
            expires_at=expiry,
            response_ip=ip,
        )
    else:
        updated = update_consent_status(
            consent_id,
            "DECLINED",
            declined_at=now,
            response_ip=ip,
        )

    write_audit(
        actor_id,
        "counsellor",
        "CONSENT_ACCEPTED" if decision == "ACCEPTED" else "CONSENT_DECLINED",
        "consent",
        consent_id,
        payload={
            "signature": signature,
            "recorded_by": "counsellor",
            "via": "tracker",
            "recipient": updated["recipient_email"],
        },
        ip=ip,
    )
    create_consent_event(
        consent_id,
        "accepted" if decision == "ACCEPTED" else "declined",
        actor_type="counsellor",
        actor_id=actor_id,
        metadata={"signature": signature, "via": "tracker"},
    )
    # The recipient still gets the §4.5 confirmation email so the decision is
    # reflected in their own records (a failed email must not undo the decision).
    _notify_consent_response(updated, accepted=(decision == "ACCEPTED"), token=consent.get("magic_token"))
    return updated


def revoke_consent(consent_id: str, ip: str | None = None, user_agent: str | None = None) -> dict:
    """Transition ACCEPTED -> REVOKED.

    Marks the student's existing analyses as 'consent withdrawn' so the
    revocation takes effect immediately without silently deleting records
    (Delivery Brief §2.8).
    """
    consent = get_consent_by_id(consent_id)
    if not consent:
        raise ValueError("Consent not found")
    if consent["status"] != "ACCEPTED":
        raise ValueError(f"Cannot revoke consent in status {consent['status']}")

    now = datetime.now(timezone.utc).isoformat()
    updated = update_consent_status(
        consent_id, "REVOKED", revoked_at=now, response_ip=ip, response_user_agent=user_agent,
    )
    withdrawn = mark_analyses_consent_withdrawn(consent["student_id"])
    write_audit(
        None, "recipient", "CONSENT_REVOKED", "consent", consent_id,
        payload={"analyses_withdrawn": withdrawn}, ip=ip,
    )
    create_consent_event(consent_id, "revoked", actor_type="recipient",
                         metadata={"ip": ip, "analyses_withdrawn": withdrawn})
    return updated


# ── Batch maintenance (scheduler) ─────────────────────────────────────

DEFAULT_BULK_PLATFORMS = ["Reddit", "Bluesky", "Mastodon", "YouTube"]

CSV_COLUMNS = [
    "consent_id", "student_id", "student_name", "student_email",
    "recipient_email", "recipient_role", "status", "mode", "platforms",
    "dispatched_at", "viewed_at", "accepted_at", "declined_at",
    "revoked_at", "expires_at", "created_at",
]


def _csv_cell(value) -> str:
    if value is None:
        return ""
    text = str(value)
    if text[:1] in {"=", "+", "-", "@"}:
        text = "'" + text
    return f'"{text.replace(chr(34), chr(34) + chr(34))}"'


def consents_to_csv(rows: list[dict]) -> str:
    """Render consent rows as CSV (header + escaped cells, \\r\\n rows)."""
    lines = [",".join(_csv_cell(col) for col in CSV_COLUMNS)]
    for row in rows:
        platforms = ", ".join(json.loads(row.get("platforms_json") or "[]"))
        cells = [
            row.get("id"),
            row.get("student_id"),
            row.get("student_name"),
            row.get("student_email"),
            row.get("recipient_email"),
            row.get("recipient_role"),
            row.get("status"),
            row.get("mode"),
            platforms,
            row.get("dispatched_at"),
            row.get("viewed_at"),
            row.get("accepted_at"),
            row.get("declined_at"),
            row.get("revoked_at"),
            row.get("expires_at"),
            row.get("created_at"),
        ]
        lines.append(",".join(_csv_cell(c) for c in cells))
    return "\r\n".join(lines)


def dispatch_consents_for_students(
    students: list[dict],
    actor_id: str,
    ip: str | None = None,
    platforms: list | None = None,
) -> dict:
    """Create + dispatch consent requests for a batch of roster students.

    Routing follows Delivery Brief §2.4:
      * adult (is_minor=0)            -> consent request to the student
      * minor + parent_email present  -> consent request to the parent,
                                         plus an informational courtesy
                                         copy to the student (template 4.3)
      * minor without parent_email    -> skipped; recorded as a routing error

    Students that already carry a live consent (ACCEPTED and unexpired, or
    PENDING/VIEWED) are skipped so re-runs never double-send.

    Returns a summary dict: {checked, created, dispatched, email_queued,
    courtesy_queued, skipped_live, skipped_no_parent, routing_errors}
    """
    platforms = platforms or DEFAULT_BULK_PLATFORMS
    summary: dict = {
        "checked": len(students),
        "created": 0,
        "dispatched": 0,
        "email_queued": 0,
        "courtesy_queued": 0,
        "skipped_live": 0,
        "skipped_no_parent": 0,
        "users_created": 0,
        "routing_errors": [],
    }
    now = datetime.now(timezone.utc)
    _created_user_ids: set = set()

    # Bulk dispatch runs in enqueue mode: consent/courtesy emails are persisted
    # to the outbox and delivered by the background worker, so a large roster
    # upload returns without blocking on per-recipient ESP round-trips.
    with bulk_enqueue_mode():
        for student in students:
            sid = student["id"]

            # Consents FK to users(id); roster students live in the students table,
            # so resolve (or create) the matching user account for each student.
            user_id = _resolve_student_user(student)
            if user_id is None:
                summary["routing_errors"].append(
                    {"student_id": sid, "reason": "could not resolve user account"}
                )
                continue
            if user_id not in _created_user_ids:
                _created_user_ids.add(user_id)
                summary["users_created"] += 1

            _ensure_roster_student_invitation(user_id, student)
            if not student.get("user_id"):
                update_student(student["id"], user_id=user_id)

            # Skip students that already have a live consent (no double-send).
            existing = get_consents_by_student(user_id) or []
            live = [c for c in existing if c["status"] in ("PENDING", "VIEWED")]
            live += [c for c in existing if c["status"] == "ACCEPTED" and c.get("expires_at", "9999") > now.isoformat()]
            if live:
                summary["skipped_live"] += 1
                continue

            student_email = decrypt_pii(student["email_encrypted"])
            is_minor = bool(student["is_minor"])

            if is_minor:
                parent_email = ""
                if student.get("parent_email_encrypted"):
                    parent_email = decrypt_pii(student["parent_email_encrypted"])
                if not parent_email:
                    summary["skipped_no_parent"] += 1
                    summary["routing_errors"].append(
                        {"student_id": sid, "reason": "minor without parent_email"}
                    )
                    continue
                consent = create_consent(user_id, actor_id, parent_email, "parent", platforms, mode="ON_DEMAND")
            else:
                consent = create_consent(user_id, actor_id, student_email, "student", platforms, mode="ON_DEMAND")

            try:
                dispatched = dispatch_consent(consent["id"], actor_id, ip=ip)
            except ValueError as exc:
                summary["routing_errors"].append({"student_id": sid, "reason": str(exc)})
                continue

            set_student_current_consent(sid, consent["id"])

            summary["created"] += 1
            summary["dispatched"] += 1
            if dispatched.get("email_sent"):
                summary["email_queued"] += 1
            else:
                summary["routing_errors"].append(
                    {"student_id": sid, "reason": dispatched.get("email_error") or "consent email enqueue failed"}
                )

            if is_minor:
                ok = _send_courtesy_copy(student, consent, dispatched["magic_token"])
                if ok:
                    summary["courtesy_queued"] += 1

    return summary


def _resolve_student_user(student: dict) -> str | None:
    """Find or create the users(row) account that a roster student maps to.

    Consents FK ``student_id`` to ``users(id)``; roster rows live in the
    ``students`` table and link back via ``current_consent_id``. Resolve by
    email so an already-registered student (same email) reuses their account.
    """
    try:
        email = decrypt_pii(student["email_encrypted"])
    except Exception:
        return None
    existing = get_user_by_email(email)
    if existing:
        if not existing.get("institution_id"):
            update_user_onboarding(existing["id"], "institution_managed", student.get("institution_id"))
        return existing["id"]
    name = "Student"
    try:
        name = (decrypt_pii(student.get("first_name_encrypted") or "") or "").strip() or "Student"
    except Exception:
        pass
    user = create_user(email, name, "", role_type="student", institution_id=student.get("institution_id"))
    return user["id"]


def _ensure_roster_student_invitation(user_id: str, student: dict) -> None:
    """Issue one secure activation link for a roster-created student account."""
    user = get_user_by_id(user_id)
    if not user or user.get("password_hash") or user.get("invitation_token_hash"):
        return
    token = os.urandom(32)
    token_value = __import__("base64").urlsafe_b64encode(token).decode().rstrip("=")
    set_user_invitation(
        user_id,
        hash_token(token_value),
        (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
    )
    base = (os.getenv("APP_BASE_URL") or os.getenv("FRONTEND_URL") or "http://localhost:5173").rstrip("/")
    invite_url = f"{base}/invite?token={token_value}"
    first_name = (decrypt_pii(student.get("first_name_encrypted") or "") or "there").split()[0]
    institution = get_institution_by_id(student.get("institution_id")) or {}
    subject = "Complete your MindGuard student account"
    html = (
        f"<p>Hello {first_name},</p>"
        f"<p>{institution.get('name') or 'Your institution'} has invited you to MindGuard.</p>"
        f"<p><a href=\"{invite_url}\">Set your password and activate your account</a></p>"
        "<p>This link expires in 7 days. If you are under 18, a parent or guardian must also complete consent before protected wellbeing features are available.</p>"
    )
    send_html_email(
        user["email"], subject, html,
        related_type="student_invitation", related_id=user_id,
        metadata={"institution_id": student.get("institution_id")},
    )


def _send_courtesy_copy(student: dict, consent: dict, token: str) -> bool:
    """Send the informational courtesy email (template 4.3) to a minor student."""
    first_name = (decrypt_pii(student.get("first_name_encrypted") or "") or "there").split()[0]
    student_email = decrypt_pii(student["email_encrypted"])
    context = {
        "institution_name": consent.get("notes") or "your school",
        "student_first_name": first_name,
    }
    context.update(_footer_urls(token))
    subject, html = student_courtesy_copy(context)
    ok, err = _dispatch_email(
        student_email,
        subject,
        html,
        related_type="consent",
        related_id=consent["id"],
        metadata={"kind": "courtesy_copy"},
    )
    if not ok:
        logger.warning("courtesy copy failed for %s: %s", student_email, err)
    return ok

def _footer_urls(token: str) -> dict:
    base = (os.getenv("APP_BASE_URL") or os.getenv("FRONTEND_URL") or "http://localhost:5173").rstrip("/")
    return {
        "withdraw_url": f"{base}/consent/{token}",
        "privacy_url": f"{base}/privacy",
        "contact_url": f"{base}/contact",
    }


def _reminder_context(consent: dict, token: str) -> dict:
    ctx = {
        "institution_name": consent.get("notes") or "your school",
        "student_first_name": consent.get("student_name") or "there",
        "counsellor_email": "counsellor@mindguard.app",
        "consent_url": _consent_url(token),
    }
    ctx.update(_footer_urls(token))
    return ctx


def _student_first_name(consent: dict) -> str:
    """Best-effort first name for the consent's student (users.name)."""
    user = get_user_by_id(consent.get("student_id") or "")
    if user and user.get("name"):
        return str(user["name"]).strip().split()[0]
    return consent.get("student_name") or "the student"


def _parent_first_name(consent: dict) -> str:
    """Best-effort parent/guardian first name for a parent-routed consent."""
    name = consent.get("signature_name") or ""
    if name:
        return str(name).strip().split()[0]
    return "Parent/Guardian"


def _counsellor_email(consent: dict) -> str:
    """Best-effort initiating counsellor email for email-template context."""
    admin = get_user_by_id(consent.get("counsellor_id") or "")
    if admin and admin.get("email"):
        return admin["email"]
    return "counsellor@mindguard.app"


def _reminder_day(consent: dict) -> int:
    """Day-of-pending for the reminder subject line (3 or 7)."""
    try:
        dispatched = datetime.fromisoformat(consent.get("dispatched_at") or "")
        elapsed = (datetime.now(timezone.utc) - dispatched).days
    except (ValueError, TypeError):
        elapsed = 3
    for target in sorted(CONSENT_REMINDER_DAYS):
        if elapsed >= target:
            return target
    return sorted(CONSENT_REMINDER_DAYS)[0] if CONSENT_REMINDER_DAYS else 3


def _tracker_url() -> str:
    base = (os.getenv("APP_BASE_URL") or os.getenv("FRONTEND_URL") or "http://localhost:5173").rstrip("/")
    return f"{base}/#consent-tracker"


def _notify_consent_response(consent: dict, accepted: bool, token: str | None = None) -> None:
    """Send the §4.5 confirmation + §4.6 admin notification after a response.

    Never raises: a failed email must not undo an already-recorded decision.
    The recipient always receives the confirmation; the admin notification is
    sent to the consent's initiating counsellor when that account resolves.
    """
    token = token or consent.get("magic_token") or ""
    status = "ACCEPTED" if accepted else "DECLINED"
    context = {
        "student_first_name": _student_first_name(consent),
        "status": status,
        "consent_url": _consent_url(token),
        "tracker_url": _tracker_url(),
    }
    context.update(_footer_urls(token))

    subject, html = consent_confirmation(context, accepted=accepted)
    ok, err = _dispatch_email(
        consent["recipient_email"],
        subject,
        html,
        related_type="consent",
        related_id=consent["id"],
        metadata={"kind": "confirmation", "status": status},
    )
    if not ok:
        logger.warning("consent confirmation email failed for %s: %s", consent["recipient_email"], err)

    admin = get_user_by_id(consent.get("counsellor_id") or "")
    admin_email = (admin or {}).get("email")
    if not admin_email:
        logger.warning("no admin user for consent %s; skipping admin notification", consent["id"])
        return
    subject, html = admin_consent_notification(context)
    ok, err = _dispatch_email(
        admin_email,
        subject,
        html,
        related_type="consent",
        related_id=consent["id"],
        metadata={"kind": "admin_notification", "status": status},
    )
    if not ok:
        logger.warning("admin notification failed for %s: %s", admin_email, err)


def process_expired_consents() -> int:
    """Flip expiring consents: PENDING/VIEWED -> EXPIRED, ACCEPTED -> RENEWAL_DUE.

    Returns the number of consents transitioned. Accepted consents past their
    ``expires_at`` surface as RENEWAL_DUE so the tracker can prompt a renewal;
    analysis of that subject is already gated by ``get_active_consent``.
    """
    changed = 0
    for consent in get_all_consents():
        status = consent["status"]
        expires = consent.get("expires_at")
        if status not in ("PENDING", "VIEWED", "ACCEPTED"):
            continue
        if not (expires and datetime.now(timezone.utc).isoformat() > expires):
            continue
        if status in ("PENDING", "VIEWED"):
            update_consent_status(consent["id"], "EXPIRED")
            create_consent_event(consent["id"], "expired", actor_type="system")
        else:
            update_consent_status(consent["id"], "RENEWAL_DUE")
            create_consent_event(consent["id"], "renewal_due", actor_type="system")
        changed += 1
    return changed


def _reminder_days_for_consent(consent: dict) -> list[int]:
    """Effective reminder schedule for a consent.

    Honors the institution's ``consent_reminder_days`` override (stored as a JSON
    array string, e.g. ``"[3,7]"``); falls back to the global
    ``CONSENT_REMINDER_DAYS`` when unset, unparsable, or empty.
    """
    inst_id = get_institution_id_for_consent(consent["id"])
    if inst_id:
        inst = get_institution_by_id(inst_id)
        raw = (inst or {}).get("consent_reminder_days")
        if raw:
            try:
                parsed = json.loads(raw)
            except (ValueError, TypeError):
                parsed = None
            if (
                isinstance(parsed, list)
                and parsed
                and all(isinstance(d, int) and d > 0 for d in parsed)
            ):
                return sorted(parsed)
    return sorted(CONSENT_REMINDER_DAYS)


def process_consent_reminders(now: datetime | None = None) -> dict:
    """Send day-3/day-7 reminders for pending consents. Returns a summary.

    Reminder n is sent when ``dispatched_at`` is at least ``CONSENT_REMINDER_DAYS[n]``
    days old and fewer than n+1 reminders have already been sent. The effective
    schedule is per-institution when that institution overrides the default.
    """
    now = now or datetime.now(timezone.utc)
    sent, failed = [], []
    for consent in get_all_consents():
        if consent["status"] not in ("PENDING", "VIEWED"):
            continue
        dispatched = consent.get("dispatched_at")
        if not dispatched:
            continue
        try:
            elapsed = (now - datetime.fromisoformat(dispatched)).days
        except (ValueError, TypeError):
            continue
        days = _reminder_days_for_consent(consent)
        already = int(consent.get("reminders_sent") or 0)
        for index, target_day in enumerate(days):
            if elapsed >= target_day and already <= index:
                ok, err = _send_reminder_for(consent, target_day, already + 1)
                (sent if ok else failed).append(consent["id"])
                break
    return {"sent": len(sent), "failed": len(failed), "sent_ids": sent, "failed_ids": failed}


def _send_reminder_for(consent: dict, day: int, new_count: int) -> tuple[bool, str]:
    token = create_signed_token(consent["id"])
    consent = update_consent_status(
        consent["id"], consent["status"], signed_token_hash=hash_token(token),
    ) or consent
    subject, html = consent_reminder(_reminder_context(consent, token), day=day)
    ok, err = _dispatch_email(
        consent["recipient_email"],
        subject,
        html,
        related_type="consent",
        related_id=consent["id"],
        metadata={"kind": f"reminder_day_{day}"},
    )
    if ok:
        update_consent_status(
            consent["id"], consent["status"],
            reminders_sent=new_count,
        )
        create_consent_event(
            consent["id"], "reminder_sent", actor_type="system",
            metadata={"day": day, "reminders_sent": new_count},
        )
    else:
        logger.warning("consent reminder %s failed: %s", consent["id"], err)
    return ok, err
