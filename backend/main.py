import asyncio
import io
import html as html_lib
import ipaddress
import json
import logging
import os
import re
import secrets
import string
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode, urlparse
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

import numpy as np
import httpx
import jwt
from pathlib import Path

from fastapi import FastAPI, Header, Request, UploadFile, File, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from backend.config import (
    SUPABASE_URL,
    SUPABASE_ANON_KEY,
    RESEND_WEBHOOK_SECRET,
    WEBHOOK_TOLERANCE_SECONDS,
    REDDIT_CLIENT_SECRET,
    DEMO_NOTIFY_EMAIL,
)
from backend.models.schemas import (
    TextAnalysisRequest,
    TextAnalysisResponse,
    PlatformRequest,
    LoginRequest,
    RegisterRequest,
    ChangePasswordRequest,
    CreateGroupRequest,
    UpdateGroupRequest,
    GroupMessageRequest,
    UpdateNotificationPreferenceRequest,
    MuteGroupRequest,
    NOTIFICATION_TYPES,
    DemoRequestCreate,
    DemoRequestUpdate,
)
from backend.services.email_sender import (
    get_email_provider_status,
    process_email_outbox,
    send_html_email,
)
from backend.services.predictor import (
    predict_one,
    predict_batch,
    InferenceUnavailableError,
)
from backend.services.webhook_service import handle_webhook
from backend.services.email_templates import (
    demo_request_confirmation,
    demo_request_notification,
    student_status_notification,
    counsellor_invitation_notification,
)
from backend.utils import (
    clean_text,
    risk_label,
    detect_socioeconomic,
    calibrate_risk_score,
    RESOURCES,
    US_STATE_RESOURCES,
    TEAM_MEMBERS,
)
from backend.database import (
    init_db,
    seed_defaults,
    ensure_user_approved,
    get_user_by_email,
    get_user_by_id,
    create_user,
    mark_user_as_staff,
    get_individual_users,
    get_students,
    update_student_status,
    update_user_status,
    set_user_invitation,
    get_user_by_invitation_token_hash,
    clear_user_invitation,
    update_user_onboarding,
    link_parent_guardian,
    create_analysis_session,
    get_analysis_sessions_for_student,
    get_analysis_session,
    save_analysis,
    get_analytics,
    create_referral,
    get_referrals,
    get_referral,
    update_referral,
    create_alert,
    create_appointment,
    get_appointment,
    list_appointments,
    update_appointment_status,
    send_message,
    get_conversation,
    get_conversations,
    mark_read,
    mark_all_read,
    create_notification,
    get_notifications,
    get_notification_summary,
    mark_notification_read,
    get_counsellor_dashboard,
    accept_user_terms,
    # v1 additions
    create_consent,
    get_consent_by_id,
    get_consent_by_token,
    query_consents,
    get_consent_with_student,
    get_audit_log_for_target,
    get_consent_events,
    create_linked_account,
    get_linked_accounts,
    revoke_linked_account,
    get_alerts,
    get_alert_by_id,
    transition_alert,
    has_consent_relationship,
    write_audit,
    get_audit_log,
    get_all_audit_log,
    health_check,
    create_note,
    get_notes,
    get_rolling_risk,
    get_rolling_risk_history,
    get_user_by_referral_code,
    get_all_users,
    permanently_delete_user,
    update_user_password,
    update_staff_profile,
    update_user_role,
    get_institution_by_id,
    list_institutions,
    create_institution,
    update_institution,
    list_students,
    archive_student,
    update_student,
    get_student_by_id,
    get_student_by_user_id,
    get_student_by_student_id_hash,
    purge_roster_student,
    create_demo_request,
    get_demo_request,
    get_demo_request_by_response_token,
    list_demo_requests,
    update_demo_request,
    # groups
    create_group,
    get_group_by_id,
    update_group,
    delete_group,
    add_group_member,
    remove_group_member,
    get_group_members,
    get_groups_for_user,
    is_group_member,
    get_group_unread_count,
    send_group_message,
    get_group_messages,
    mark_all_group_messages_read,
    # notification preferences
    get_notification_preferences,
    set_notification_preference,
    should_notify,
    # social accounts & assignments
    get_social_accounts,
    get_social_account,
    create_social_account_claim,
    rotate_social_account_claim_code,
    mark_social_account_verified,
    delete_social_account,
    assign_student_to_counsellor,
    unassign_student_from_counsellor,
    get_assignment,
    get_assignments_for_counsellor,
    get_assignments_for_student,
    consume_rate_limit,
)
from backend.services.consent_service import (
    dispatch_consent,
    remind_consent,
    record_consent_decision,
    record_view,
    accept_consent,
    decline_consent,
    revoke_consent,
    verify_consent_token,
    remaining_views,
    process_consent_reminders,
    process_expired_consents,
    dispatch_consents_for_students,
    consents_to_csv,
)
from backend.services.analysis_service import (
    INFERENCE_UNAVAILABLE_MESSAGE,
    inference_http_error,
    run_consented_student_analysis,
)
from backend.services.crypto import (
    decrypt_pii,
    encrypt_pii,
    hash_student_id,
    hash_token,
)
from backend.services.consent_gate import consent_status_for_ui
from backend.services.risk_policy import assess_risk
from backend.services.demo_service import (
    demo_email_context,
    work_email_warning,
    verify_recaptcha_token,
)
from backend.services.roster_service import upsert_roster
from backend.services.retention_service import run_retention_cleanup
from backend.permissions import (
    PERM_ANALYSIS_RUN,
    PERM_ROSTER_UPLOAD,
    PERM_STUDENTS_VIEW,
    PERM_CONSENT_MANAGE,
    PERM_DEMO_MANAGE,
    PERM_AUDIT_VIEW,
    require_permission,
    require_any_permission,
)
from backend.auth import (
    hash_password,
    verify_password,
    create_access_token,
    require_auth,
    blacklist_token,
)
from backend.logging_setup import (
    generate_request_id,
    set_request_context,
    setup_logging,
)

_background_tasks: list[asyncio.Task] = []

setup_logging()
logger = logging.getLogger(__name__)


def _sentry_before_send(event, hint):
    """Never upload PII: drop request bodies and recipient emails from reports."""
    for key in ("request",):
        event.pop(key, None)
    for key in list(event.get("extra", {})):
        if "email" in key.lower() or "recipient" in key.lower():
            event["extra"].pop(key, None)
    return event


_SENTRY_DSN = os.getenv("SENTRY_DSN", "").strip()
if _SENTRY_DSN:
    import sentry_sdk

    sentry_sdk.init(
        dsn=_SENTRY_DSN,
        environment=os.getenv("SENTRY_ENVIRONMENT", "production"),
        traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
        release=f"mindguard-backend@{os.getenv('APP_VERSION', '2.0.0')}",
        before_send=lambda event, hint: _sentry_before_send(event, hint),
    )
    logger.info(
        "Sentry initialised (env=%s)", os.getenv("SENTRY_ENVIRONMENT", "production")
    )


app = FastAPI(title="MindGuard API", version="2.0.0")


@app.exception_handler(InferenceUnavailableError)
async def inference_unavailable_handler(
    request: Request, exc: InferenceUnavailableError
):
    """Constrained hosts (too little RAM for torch) fail cleanly with a 503.

    Catches the pre-import memory guard so that every inference route —
    including the platform scrapers that re-wrap RuntimeError as 400 — returns
    "service unavailable" instead of a misleading client error or an OOM kill.
    """
    return JSONResponse(
        status_code=503, content={"detail": INFERENCE_UNAVAILABLE_MESSAGE}
    )


class SPAStaticFiles(StaticFiles):
    _PUBLIC = {
        "/robots.txt": (
            "text/plain",
            b"User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /dashboard\nDisallow: /auth\n",
        ),
    }

    async def get_response(self, path: str, scope):
        if path in self._PUBLIC:
            ct, body = self._PUBLIC[path]
            from starlette.responses import Response

            return Response(content=body, media_type=ct)
        try:
            return await super().get_response(path, scope)
        except Exception as exc:
            if getattr(exc, "status_code", None) == 404:
                return await super().get_response("index.html", scope)
            raise


def _require_analysis_staff(user: dict) -> None:
    require_permission(user, PERM_ANALYSIS_RUN)


def _require_self_adult(user: dict) -> None:
    """Self-analysis workspace is adult-gated (user declared adult on onboarding)."""
    if (
        user.get("role_type") in {"admin", "school_admin", "counsellor"}
        or (user.get("user_category") or "pending") != "adult"
    ):
        raise HTTPException(
            403, "Complete onboarding as an adult to use the self-analysis workspace."
        )


def _require_account_owner(user: dict) -> None:
    """Only a signed-in student/adult can claim an account for themselves."""
    if (
        user.get("role_type") != "student"
        or user.get("status") not in {"approved", "active"}
        or user.get("user_category") not in {"adult", "minor", "institution_managed"}
    ):
        raise HTTPException(
            403, "Only an active student or adult account can manage social accounts."
        )


def _auth_user_category(user: dict) -> str:
    if user.get("role_type") in {"admin", "school_admin", "counsellor"}:
        return "staff"
    return user.get("user_category") or "pending"


def _staff_profile_payload(user: dict) -> dict:
    def value(key: str) -> str:
        raw = user.get(key) or ""
        if isinstance(raw, str) and raw.startswith("gcm1:"):
            try:
                return decrypt_pii(raw)
            except Exception:
                return ""
        return str(raw)

    return {
        "phone": value("phone"),
        "country": value("country"),
        "address": value("address"),
        "professional_title": value("professional_title"),
        "qualification": value("qualification"),
        "emergency_contact": value("emergency_contact"),
        "profile_completed": bool(user.get("profile_completed_at")),
    }


def _decode_json_field(value: Any) -> Any:
    if value in (None, "", []):
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return value


def _decode_session_json(session: dict) -> dict:
    out = dict(session)
    for db_key, out_key in (
        ("platforms_json", "platforms"),
        ("findings_json", "findings"),
        ("progress_json", "progress"),
        ("error_json", "error"),
    ):
        if db_key in out:
            out[out_key] = _decode_json_field(out.pop(db_key))
    for key in ("insights", "recommendations"):
        if key in out and out.get(key):
            decoded = _decode_json_field(out[key])
            if isinstance(decoded, list):
                out[key] = decoded
            elif isinstance(decoded, str):
                out[key] = [decoded]
    return out


_cors_origins = [
    o.strip()
    for o in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000,http://localhost:5188,http://127.0.0.1:5188",
    ).split(",")
    if o.strip()
]
_ORIGIN_RE = re.compile(r"^https?://[a-zA-Z0-9\-\.]+(?::\d{1,5})?$")
for _origin in _cors_origins:
    if _origin == "*":
        raise RuntimeError("CORS_ORIGINS must not be '*' while allow_credentials=True")
    if not _ORIGIN_RE.match(_origin):
        raise RuntimeError(f"Invalid origin in CORS_ORIGINS: {_origin!r}")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


# ── CSRF defense (Origin check) ─────────────────────────────────────────
# Bearer-token auth already blocks cookie-based CSRF, but an extra Origin check
# on state-changing requests defends against confused-deputy / drive-by POSTs.
# Requests from browsers carry an Origin header (or Sec-Fetch-Site); we reject
# any unsafe request whose Origin is neither the request's own host nor an
# explicitly trusted origin. Requests with no Origin/Sec-Fetch-Site (curl, server
# webhooks, mobile clients) pass, and same-site (Sec-Fetch-Site: same-site) calls
# to an untrusted host still require an explicit trusted origin.
_TRUSTED_ORIGINS = {
    o.rstrip("/") for o in os.getenv("TRUSTED_ORIGINS", "").split(",") if o.strip()
} | set(_cors_origins)
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _origin_matches_host(origin: str, request: Request) -> bool:
    """True when an Origin header matches the request's own host (scheme-aware)."""
    try:
        parsed = urlparse(origin)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return False
    # The immediate Host may be rewritten by a reverse proxy (e.g. Next.js
    # `rewrites` forwards /api calls to the backend); fall back to the first
    # X-Forwarded-Host hop. The browser still sets Origin itself, so an attacker
    # cannot forge it — this only widens which host reflects a legitimate origin.
    hosts = [request.headers.get("host", "")]
    forwarded = request.headers.get("x-forwarded-host", "")
    if forwarded:
        hosts.append(forwarded.split(",")[0].strip())
    hosts = [h for h in hosts if h]
    if not hosts:
        return False
    scheme = "https" if _request_is_secure(request) else "http"
    return parsed.scheme == scheme and any(parsed.netloc == h for h in hosts)


@app.middleware("http")
async def csrf_origin_middleware(request: Request, call_next):
    if request.method in _SAFE_METHODS:
        return await call_next(request)
    origin = request.headers.get("origin", "")
    site = (request.headers.get("sec-fetch-site", "") or "").strip().lower()
    if site == "cross-site":
        logger.warning(
            "csrf: blocking cross-site %s %s", request.method, request.url.path
        )
        return Response("Forbidden", status_code=403)
    if origin:
        if origin in _TRUSTED_ORIGINS or _origin_matches_host(origin, request):
            return await call_next(request)
        logger.warning(
            "csrf: blocking %s %s from untrusted origin %s",
            request.method,
            request.url.path,
            origin,
        )
        return Response("Forbidden", status_code=403)
    if site and site not in ("same-origin", "same-site", "none"):
        logger.warning(
            "csrf: blocking %s %s (sec-fetch-site=%s)",
            request.method,
            request.url.path,
            site,
        )
        return Response("Forbidden", status_code=403)
    return await call_next(request)


# ── Security headers (Delivery Brief §8) ──────────────────────────────
# CSP is applied only to HTML documents served by this app (the production SPA
# mount) and never to API responses or the interactive docs, so /docs keeps its
# inline Swagger assets while the SPA gets a strict, nonce-free policy. The
# always-on headers apply to every response.
_CSP_ENABLED = os.getenv("MINDGUARD_CSP", "true").strip().lower() != "false"

_SECURITY_ALWAYS_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), interest-cohort=()",
}

_CSP_POLICY = (
    "default-src 'self' blob:; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net; "
    "font-src 'self' data: https://fonts.gstatic.com https://cdn.jsdelivr.net; "
    "img-src 'self' data: blob:; "
    "connect-src 'self' https://*.supabase.co wss://*.supabase.co; "
    "frame-src 'self' blob:; "
    "object-src 'self' blob:; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)

# Paths serving non-SPA HTML (interactive API docs) that rely on inline/CDN
# scripts and must not receive the SPA CSP.
_CSP_HTML_EXEMPT_PATHS = ("/docs", "/redoc", "/openapi.json")


def _build_security_headers(content_type: str, path: str) -> dict[str, str]:
    headers = dict(_SECURITY_ALWAYS_HEADERS)
    if (
        _CSP_ENABLED
        and (content_type or "").startswith("text/html")
        and not path.startswith(_CSP_HTML_EXEMPT_PATHS)
    ):
        headers["Content-Security-Policy"] = _CSP_POLICY
    return headers


def _request_is_secure(request: Request) -> bool:
    """True when the client connection is HTTPS (honors X-Forwarded-Proto).

    HSTS is only meaningful over HTTPS; emitting it on plain HTTP would let a
    network attacker inject the header and disable a host's HSTS entirely, so it
    is gated on a secure channel (including behind TLS-terminating proxies).
    """
    proto = request.headers.get("x-forwarded-proto", "")
    if proto:
        return proto.split(",")[0].strip() == "https"
    return request.url.scheme == "https"


_HSTS = "max-age=31536000; includeSubDomains"


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    headers = _build_security_headers(
        response.headers.get("content-type", ""), request.url.path
    )
    if _request_is_secure(request):
        headers.setdefault("Strict-Transport-Security", _HSTS)
    for name, value in headers.items():
        response.headers.setdefault(name, value)
    return response


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """Correlate all logs for a request and emit a structured access line."""
    request_id = generate_request_id()
    request.state.request_id = request_id
    start = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        set_request_context(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status_code=status_code,
            duration_ms=duration_ms,
            ip=request.client.host if request.client else None,
            user_id=_token_subject(request),
        )
        logger.info(
            "http %s %s -> %s (%sms)",
            request.method,
            request.url.path,
            status_code,
            duration_ms,
        )
        # Clear the context so background work after the response is not
        # incorrectly attributed to the last request.
        set_request_context()


def _token_subject(request: Request) -> str | None:
    """Best-effort user id from the Bearer token (unverified, logging only).

    Never fails: malformed/missing credentials simply yield None so the access
    line still records ``user_id: null`` without perturbing the request.
    """
    try:
        auth = request.headers.get("Authorization", "")
        if not auth.lower().startswith("bearer "):
            return None
        token = auth.split(None, 1)[1]
        payload = jwt.decode(token, options={"verify_signature": False})
        return payload.get("sub")
    except Exception:
        return None


@app.on_event("startup")
async def startup():
    init_db()
    seed_defaults()
    _bootstrap_admins()
    logger.info("Database initialized and seeded")
    email_status = get_email_provider_status()
    logger.info(
        "email delivery configured: provider=%s resend=%s webhook=%s sender=%s",
        email_status["provider"],
        email_status["resend_configured"],
        email_status["webhook_configured"],
        email_status["sender"],
    )
    _background_tasks.clear()
    if os.getenv("MINDGUARD_DISABLE_BACKGROUND_TASKS", "").strip().lower() not in {
        "1",
        "true",
        "yes",
    }:
        _background_tasks.extend(
            [
                asyncio.create_task(
                    _consent_maintenance_loop(), name="consent-maintenance"
                ),
                asyncio.create_task(
                    _retention_maintenance_loop(), name="retention-maintenance"
                ),
                asyncio.create_task(_email_drain_loop(), name="email-drain"),
            ]
        )


@app.on_event("shutdown")
async def shutdown():
    """Cancel maintenance workers so TestClient and graceful shutdown can exit."""
    tasks = list(_background_tasks)
    _background_tasks.clear()
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


def _bootstrap_admins() -> None:
    """Promote bootstrap admin emails (MINDGUARD_BOOTSTRAP_ADMIN_EMAIL) to admin.

    Security-conscious provisioning: the operator lists exact existing user emails
    (comma-separated). Each matching user is promoted to ``admin`` and the change
    is recorded in the audit log as USER_PROMOTED. Unknown emails are logged and
    skipped (no account is created implicitly).
    """
    raw = os.getenv("MINDGUARD_BOOTSTRAP_ADMIN_EMAIL", "")
    emails = [e.strip().lower() for e in raw.split(",") if e.strip()]
    if len(emails) == 0:
        return
    for email in emails:
        user = get_user_by_email(email)
        if not user:
            logger.warning(
                "bootstrap admin: %s not found; create the account first, then redeploy",
                email,
            )
            continue
        ensure_user_approved(user["id"])
        if user["role_type"] == "admin":
            logger.info("bootstrap admin: %s is already an admin", email)
            continue
        update_user_role(user["id"], "admin")
        ensure_user_approved(user["id"])
        write_audit(
            user["id"],
            "admin",
            "USER_PROMOTED",
            "user",
            user["id"],
            payload={"bootstrap": True, "previous_role": user["role_type"]},
        )
        logger.info("bootstrap admin: promoted %s to admin", email)


async def _consent_maintenance_loop() -> None:
    """Hourly batch: expire stale consents and send day-7/day-14 reminders."""
    while True:
        try:
            expired = process_expired_consents()
            reminders = process_consent_reminders()
            if expired or reminders["sent"] or reminders["failed"]:
                logger.info(
                    "consent maintenance: expired=%s reminder_sent=%s reminder_failed=%s",
                    expired,
                    reminders["sent"],
                    reminders["failed"],
                )
        except Exception:
            logger.exception("consent maintenance run failed")
        await asyncio.sleep(3600)


async def _email_drain_loop() -> None:
    """Drain the email outbox in the background (Remediation P1-1).

    Polls every ``EMAIL_WORKER_POLL_SECONDS`` (default 3s) and delivers rows the
    request path enqueued without a synchronous flush (bulk roster dispatch) or
    that were left ``queued`` by a crash mid-send. Runs in a worker thread so the
    blocking SQLite/transport work never stalls the event loop.
    """
    while True:
        try:
            await asyncio.to_thread(
                process_email_outbox,
                batch_size=int(os.getenv("EMAIL_WORKER_BATCH_SIZE", "50")),
                max_attempts=int(os.getenv("EMAIL_WORKER_MAX_ATTEMPTS", "5")),
            )
        except Exception:
            logger.exception("email outbox drain failed")
        await asyncio.sleep(int(os.getenv("EMAIL_WORKER_POLL_SECONDS", "3")))


async def _retention_maintenance_loop() -> None:
    """Daily anonymisation of archived institution students past retention."""
    while True:
        try:
            result = await asyncio.to_thread(run_retention_cleanup)
            if result["anonymized"]:
                logger.info(
                    "retention maintenance: eligible=%s anonymized=%s",
                    result["eligible"],
                    result["anonymized"],
                )
        except Exception:
            logger.exception("retention maintenance run failed")
        await asyncio.sleep(86400)


@app.get("/api/health")
@app.get("/api/v1/healthz")
async def healthz():
    """Liveness/readiness probe (Delivery Brief §12) — includes a DB check."""
    db = health_check()
    ok = db.get("db") == "ok"
    return {
        "status": "ok" if ok else "degraded",
        "version": "2.0.0",
        "db": db,
        "email": get_email_provider_status(),
    }


# ── Rate limiting ─────────────────────────────────────────────────────

# Kept as a compatibility handle for older tests and integrations. Rate state
# itself is persisted in SQLite by ``consume_rate_limit``.
_rate_store: dict[str, list[float]] = defaultdict(list)
_RATE_WINDOW = 60  # seconds
_AUTH_RATE_MAX = 10  # max auth attempts per window per IP
_ANALYSIS_RATE_MAX = 30  # max analysis/platform inferences per window per user


def _check_rate_limit(
    key: str, max_requests: int = _AUTH_RATE_MAX, window: int = _RATE_WINDOW
):
    if not consume_rate_limit(key, max_requests, window):
        raise HTTPException(429, "Too many requests. Please try again later.")


def _check_analysis_rate_limit(user_id: str):
    """Cap expensive model/network inferences per authenticated user.

    The analysis and platform endpoints fetch remote profiles and run model
    inference; without a cap a single account can hammer them into a DoS. The
    budget is shared across all analysis endpoints so switching between them
    cannot bypass the limit.
    """
    _check_rate_limit(f"analyze:{user_id}", max_requests=_ANALYSIS_RATE_MAX)


# ── Helpers ───────────────────────────────────────────────────────────


def _generate_referral_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "REF" + "".join(secrets.choice(alphabet) for _ in range(6))


def _safe_notify(user_id: str, title: str, message: str, ntype: str = "general"):
    """Create a notification without crashing the caller on failure."""
    try:
        create_notification(user_id, title, message, ntype)
    except Exception as e:
        logger.error("Notification creation failed for user %s: %s", user_id, e)


_PRIVATE_HOST_PATTERNS = re.compile(
    r"^(localhost|127\.|0\.0\.0\.0|0x7f\.|2130706433|::1|169\.254\.|10\.|172\.(1[6-9]|2\d|3[01])\.|192\.168\.)",
    re.IGNORECASE,
)


def _validate_external_host(host: str) -> None:
    """Block SSRF by rejecting private literals and private DNS resolutions."""
    host = host.strip().lower()
    if not host or len(host) > 253:
        raise HTTPException(400, "Invalid hostname")
    if _PRIVATE_HOST_PATTERNS.match(host):
        raise HTTPException(400, "Invalid hostname")
    if not re.match(r"^[a-z0-9][a-z0-9\-\.]{0,251}[a-z0-9]$", host):
        raise HTTPException(400, "Invalid hostname")
    try:
        import socket

        addresses = {
            info[4][0]
            for info in socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
        }
    except OSError:
        raise HTTPException(400, "Host could not be resolved")
    if not addresses or any(_is_private_ip(address) for address in addresses):
        raise HTTPException(400, "Host resolves to a private network")


def _is_private_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved


def _validate_public_video_url(video_url: str) -> None:
    """SSRF guard for yt-dlp inputs: the URL must be http(s) with a public host.

    Blocks literal loopback/private/cloud-metadata hosts and refuses names whose
    DNS resolves only to private addresses (defense against rebinding).
    """
    if not video_url or len(video_url) > 2048:
        raise HTTPException(400, "Invalid video URL")
    parsed = urlparse(video_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(400, "Invalid video URL")
    host = parsed.hostname.lower()
    if host.endswith("."):
        host = host[:-1]
    _validate_external_host(host)
    try:
        import socket

        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except OSError:
        raise HTTPException(400, "Invalid video URL")
    for info in infos:
        if _is_private_ip(info[4][0]):
            raise HTTPException(400, "Invalid video URL")


# ── Auth routes ──────────────────────────────────────────────────────


@app.post("/api/auth/login")
async def login(req: LoginRequest, request: Request):
    client_ip = _client_ip(request)
    _check_rate_limit(f"login:{client_ip}")

    # reCAPTCHA is enforced only when RECAPTCHA_SECRET is configured; local/dev
    # stays token-free so the flow keeps working without a Google console setup.
    if not await verify_recaptcha_token(req.recaptcha_token):
        raise HTTPException(403, "reCAPTCHA verification failed")

    user = get_user_by_email(req.email)
    if not user or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(401, "Invalid email or password")
    if str(user.get("status") or "").lower() == "revoked":
        raise HTTPException(401, "Account has been revoked")

    token = create_access_token(user["id"], user["role_type"])
    logger.info("Login: user=%s ip=%s", user["id"], client_ip)
    return {
        "email": user["email"],
        "name": user["name"],
        "role": user["role_type"].capitalize(),
        "role_type": user["role_type"],
        "referral_code": _generate_referral_code(),
        "terms_accepted": bool(user.get("terms_accepted_at")),
        "user_category": _auth_user_category(user),
        "institution_id": user.get("institution_id"),
        "profile_completed": bool(user.get("profile_completed_at"))
        if user.get("role_type") in {"school_admin", "counsellor"}
        else True,
        "staff_role": user.get("role_type")
        if _auth_user_category(user) == "staff"
        else None,
        "access_token": token,
    }


@app.post("/api/auth/register")
async def register(req: RegisterRequest, request: Request):
    client_ip = _client_ip(request)
    _check_rate_limit(f"register:{client_ip}")

    if not await verify_recaptcha_token(req.recaptcha_token):
        raise HTTPException(403, "reCAPTCHA verification failed")

    existing = get_user_by_email(req.email)
    if existing:
        raise HTTPException(400, "Email already registered")

    _role_map = {
        "student": "student",
        "counsellor": "counsellor",
        "counselor": "counsellor",
    }
    role_type = _role_map.get(req.role.lower(), "student") if req.role else "student"

    # Staff roles carry access to every student's personal data and consent
    # records, so they must be provisioned by an institution/admin — never via
    # open self-registration. An unverified stranger must not be able to sign
    # up as a counsellor and read the whole student roster.
    if role_type != "student":
        raise HTTPException(
            403,
            "Counsellor and school-admin accounts are provisioned by your institution. "
            "Public registration is for students only.",
        )

    # Parental consent gate for minor students
    is_minor = False
    if role_type == "student" and req.dob:
        try:
            birth = datetime.fromisoformat(req.dob)
            age = (
                datetime.now(timezone.utc) - birth.replace(tzinfo=timezone.utc)
            ).days // 365
            is_minor = age < 18
        except ValueError:
            pass
    if is_minor and not req.parent_email:
        raise HTTPException(
            400, "Parent or guardian email is required for students under 18"
        )

    # Validate referral code if provided
    referred_by_id: str | None = None
    if req.referred_by:
        referrer = get_user_by_referral_code(req.referred_by)
        if referrer:
            referred_by_id = referrer["id"]

    pw_hash = hash_password(req.password)
    user = create_user(
        req.email,
        req.name,
        pw_hash,
        role_type=role_type,
        dob=req.dob,
        parent_email=req.parent_email if is_minor else None,
        referred_by=referred_by_id,
    )

    # Notify all counsellors if a minor registered so they can follow up on parental consent
    if is_minor:
        counsellors = [u for u in get_all_users() if u["role_type"] == "counsellor"]
        for c in counsellors:
            _safe_notify(
                c["id"],
                "Minor Registration",
                f"Student {req.name} ({req.email}) registered and is under 18. Parental consent link sent to {req.parent_email}.",
                "system",
            )

    write_audit(
        user["id"],
        role_type,
        "USER_REGISTERED",
        "user",
        user["id"],
        payload={"minor": is_minor},
        ip=client_ip,
    )

    logger.info(
        "Register: user=%s role=%s minor=%s ip=%s",
        user["id"],
        role_type,
        is_minor,
        client_ip,
    )
    return {"ok": True, "user": user}


@app.post("/api/auth/change-password")
async def change_password(
    req: ChangePasswordRequest, request: Request, user: dict = Depends(require_auth)
):
    client_ip = _client_ip(request)
    _check_rate_limit(f"change-password:{client_ip}")

    fresh = get_user_by_id(user["id"])
    if not fresh or not verify_password(req.current_password, fresh["password_hash"]):
        raise HTTPException(401, "Current password is incorrect")

    if req.new_password == req.current_password:
        raise HTTPException(
            400, "New password must be different from the current password"
        )

    update_user_password(user["id"], hash_password(req.new_password))
    exp = user.get("_token_exp")
    expires_at = datetime.fromtimestamp(exp, timezone.utc).isoformat() if exp else None
    blacklist_token(user.get("_token_jti", ""), expires_at=expires_at)
    write_audit(
        user["id"],
        user["role_type"],
        "PASSWORD_CHANGED",
        "user",
        user["id"],
        ip=client_ip,
    )
    logger.info("Password changed: user=%s ip=%s", user["id"], client_ip)
    return {"ok": True}


@app.get("/api/auth/me")
async def get_me(user: dict = Depends(require_auth)):
    return {
        "email": user["email"],
        "name": user["name"],
        "role": user["role_type"].capitalize(),
        "role_type": user["role_type"],
        "referral_code": user.get("referral_code") or _generate_referral_code(),
        "terms_accepted": bool(user.get("terms_accepted_at")),
        "user_category": _auth_user_category(user),
        "institution_id": user.get("institution_id"),
        "onboarding_completed": bool(user.get("onboarding_completed_at")),
        "id": user["id"],
        "status": user.get("status"),
        "profile_completed": bool(user.get("profile_completed_at"))
        if user.get("role_type") in {"counsellor", "school_admin"}
        else True,
        "invitation_status": (
            "accepted"
            if user.get("status") == "approved"
            and not user.get("invitation_token_hash")
            else ("pending" if user.get("invitation_token_hash") else None)
        ),
        "staff_role": user.get("role_type")
        if _auth_user_category(user) == "staff"
        else None,
        "institution_permissions": list(
            __import__(
                "backend.permissions", fromlist=["user_permissions"]
            ).user_permissions(user)
        ),
        "profile": _staff_profile_payload(user)
        if user.get("role_type") in {"counsellor", "school_admin"}
        else None,
    }


@app.post("/api/auth/terms")
async def accept_terms(request: Request, user: dict = Depends(require_auth)):
    newly = accept_user_terms(user["id"])
    if newly:
        write_audit(
            user["id"],
            user["role_type"],
            "TERMS_ACCEPTED",
            "user",
            user["id"],
            ip=_client_ip(request),
        )
        logger.info("Terms accepted: user=%s", user["id"])
    return {"ok": True}


@app.post("/api/auth/onboarding")
async def complete_onboarding(
    data: dict, request: Request, user: dict = Depends(require_auth)
):
    """Explicit age/status declaration for individual vs institution-managed flow."""
    if user.get("role_type") in {"admin", "school_admin", "counsellor"}:
        raise HTTPException(
            403,
            "Staff accounts use the operational workspace and cannot complete consumer onboarding",
        )
    category = (data.get("user_category") or data.get("category") or "").strip().lower()
    allowed = {"adult", "minor", "parent", "institution_managed", "pending"}
    if category not in allowed:
        raise HTTPException(
            400, f"user_category must be one of {', '.join(sorted(allowed))}"
        )
    institution_id = data.get("institution_id")
    parent_email = (data.get("parent_email") or "").strip().lower()
    current_category = (user.get("user_category") or "pending").strip().lower()
    if current_category != "pending":
        if category != current_category or institution_id != user.get("institution_id"):
            raise HTTPException(
                403,
                "Onboarding identity and institution links cannot be changed after completion",
            )
    if category == "minor" and not parent_email:
        raise HTTPException(400, "parent_email is required for minors")
    if parent_email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", parent_email):
        raise HTTPException(400, "Invalid parent_email")
    parent_id = None
    if parent_email:
        if parent_email == str(user.get("email") or "").strip().lower():
            raise HTTPException(
                400, "A user cannot nominate themselves as their guardian"
            )
        parent_user = get_user_by_email(parent_email)
        if parent_user:
            if parent_user["id"] == user["id"] or (
                parent_user.get("role_type") != "parent"
                and parent_user.get("user_category") != "parent"
            ):
                raise HTTPException(400, "Guardian must be a separate parent account")
            parent_id = parent_user["id"]
    if user.get("parent_guardian_id") and parent_id != user.get("parent_guardian_id"):
        raise HTTPException(403, "Parent or guardian relationship cannot be changed")
    if institution_id:
        from backend.database import get_institution_by_id

        if not get_institution_by_id(institution_id):
            raise HTTPException(400, "Institution not found")
        if user.get("institution_id") != institution_id:
            raise HTTPException(
                403, "Institution membership must be provisioned by an administrator"
            )
    ok = update_user_onboarding(user["id"], category, institution_id, parent_id)
    if not ok:
        raise HTTPException(500, "Failed to update onboarding")
    write_audit(
        user["id"],
        user["role_type"],
        "ONBOARDING_COMPLETED",
        "user",
        user["id"],
        payload={"category": category, "institution_id": institution_id},
        ip=_client_ip(request),
    )
    fresh = get_user_by_id(user["id"])
    return {"ok": True, "user": fresh}


@app.get("/api/self/platforms")
async def self_platform_catalog(user: dict = Depends(require_auth)):
    _require_account_owner(user)
    from backend.services.platform_registry import all_platforms

    accounts = {a["platform"]: a for a in get_social_accounts(user["id"])}
    platforms = []
    for spec in all_platforms():
        key = spec["key"]
        acc = accounts.get(key)
        platforms.append(
            {
                **spec,
                "connected": acc is not None,
                "verification_status": (acc or {}).get("verification_status")
                or "not_connected",
                "verified_handle": (acc or {}).get("verified_handle"),
                "verified_profile_url": (acc or {}).get("verified_profile_url"),
                "analysis_status": (acc or {}).get("analysis_status") or "not_run",
                "handle": (acc or {}).get("handle"),
                "profile_url": (acc or {}).get("profile_url"),
            }
        )
    return {"platforms": platforms}


@app.get("/api/self/social-accounts")
async def get_own_social_accounts(user: dict = Depends(require_auth)):
    _require_account_owner(user)
    return {"accounts": get_social_accounts(user["id"])}


@app.post("/api/self/social-accounts")
async def add_own_social_account(
    data: dict, request: Request, user: dict = Depends(require_auth)
):
    _require_account_owner(user)
    from backend.services.platform_registry import get_platform, normalize_platform

    platform = normalize_platform((data.get("platform") or "").strip()) or ""
    if not platform:
        raise HTTPException(400, "platform is required")
    spec = get_platform(platform) or {}
    handle = (data.get("handle") or "").strip()
    profile_url = (data.get("profile_url") or "").strip()
    raw_creds = data.get("credentials")
    raw_creds = raw_creds if isinstance(raw_creds, dict) else {}

    # Accept a URL pasted into the handle field.
    if (
        handle
        and not profile_url
        and handle.lower().startswith(("http://", "https://"))
    ):
        profile_url, handle = handle, ""
    if not handle and not profile_url:
        raise HTTPException(400, "handle or profile_url required")
    if len(handle) > 128 or len(profile_url) > 512:
        raise HTTPException(400, "Field too long")

    # Build the secret bag from the platform's declared fields only — anything
    # else (attacker-injected keys) is discarded before it reaches the DB.
    allowed_fields = set(
        (spec.get("credentials") or {}).get("secret_fields", []) or []
    ) | {"handle", "channel", "profile_url"}
    creds: dict = {}
    if handle:
        creds["handle"] = handle
    if profile_url:
        creds["profile_url"] = profile_url
    for key, value in raw_creds.items():
        if key in allowed_fields and isinstance(value, str) and value.strip():
            creds[key] = value.strip()[:256]
    if platform == "youtube":
        creds["channel"] = (data.get("channel") or profile_url or handle or "").strip()[
            :512
        ]

    acc, verification_code = create_social_account_claim(
        user["id"],
        platform,
        handle or None,
        profile_url or None,
        credentials=creds or None,
    )
    write_audit(
        user["id"],
        user["role_type"],
        "SOCIAL_ACCOUNT_CLAIMED",
        "user",
        user["id"],
        payload={"platform": platform},
        ip=_client_ip(request),
    )
    return {
        "ok": True,
        "platform": platform,
        "account": acc,
        "verification_code": verification_code,
        "verification_instructions": "Add this code to the public bio/about section of the exact profile, then select Verify ownership. Do not share the code.",
    }


@app.patch("/api/self/social-accounts/{platform}")
async def update_own_social_account(
    platform: str, data: dict, request: Request, user: dict = Depends(require_auth)
):
    """Changing a handle always invalidates the former verification."""
    _require_account_owner(user)
    data = {**data, "platform": platform}
    return await add_own_social_account(data, request, user)


@app.post("/api/self/social-accounts/{platform}/verify")
async def verify_own_social_account(
    platform: str, data: dict, request: Request, user: dict = Depends(require_auth)
):
    _require_account_owner(user)
    from backend.services.platform_registry import normalize_platform

    slug = normalize_platform(platform)
    if not slug:
        raise HTTPException(400, "Unknown platform")
    account = get_social_account(user["id"], slug, include_verification_secret=True)
    if not account:
        raise HTTPException(404, "Account not found")
    if account.get("verification_status") == "verified":
        return {
            "verified": True,
            "account": get_social_account(user["id"], slug),
            "message": "This account is already verified.",
        }
    profile_url = str(account.get("profile_url") or "").strip()
    if not profile_url:
        raise HTTPException(
            400, "Add the public profile URL before verifying ownership."
        )
    parsed = urlparse(profile_url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise HTTPException(400, "Use a valid HTTPS public profile URL.")
    _validate_external_host(parsed.hostname)
    # The proof is server-verified. Never accept a client assertion, screenshot,
    # or a handle alone as evidence of ownership.
    import hashlib

    try:
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
            response = await client.get(
                profile_url,
                headers={"User-Agent": "MindGuard account-ownership verifier/1.0"},
            )
        if response.status_code >= 400:
            raise HTTPException(
                422,
                "We could not access that public profile. Check the URL and ensure the profile is public.",
            )
        code_hash = account.get("verification_code_hash")
        # Codes are deliberately never returned from the database. Check a
        # bounded candidate-free page only by matching the user-held proof via
        # the endpoint payload below.
        code = data.get("verification_code", "")
        if (
            not code
            or not code_hash
            or hashlib.sha256(str(code).encode()).hexdigest() != code_hash
        ):
            raise HTTPException(
                400,
                "Enter the current verification code shown when you claimed this account.",
            )
        if str(code).lower() not in response.text.lower():
            raise HTTPException(
                422,
                "The verification code was not found on the public profile. Add it to the profile bio/about section, wait for it to be visible publicly, then try again.",
            )
    except HTTPException:
        raise
    except httpx.HTTPError:
        raise HTTPException(
            422,
            "We could not confirm this public profile right now. Your account remains pending verification.",
        )
    verified = mark_social_account_verified(user["id"], slug)
    result = {
        "verified": True,
        "account": verified,
        "message": "Account ownership verified. Your assigned counsellor can now analyse it when consent permits.",
    }
    write_audit(
        user["id"],
        user["role_type"],
        "PLATFORM_VERIFY",
        "social_account",
        slug,
        payload={"platform": slug, "verified": result.get("verified")},
        ip=_client_ip(request),
    )
    return result


@app.post("/api/self/social-accounts/{platform}/verification-code")
async def rotate_own_social_account_code(
    platform: str, request: Request, user: dict = Depends(require_auth)
):
    _require_account_owner(user)
    from backend.services.platform_registry import normalize_platform

    slug = normalize_platform(platform)
    if not slug:
        raise HTTPException(400, "Unknown platform")
    result = rotate_social_account_claim_code(user["id"], slug)
    if not result:
        raise HTTPException(404, "Account not found")
    account, code = result
    write_audit(
        user["id"],
        user["role_type"],
        "SOCIAL_ACCOUNT_VERIFICATION_CODE_ROTATED",
        "social_account",
        slug,
        payload={"platform": slug},
        ip=_client_ip(request),
    )
    return {
        "account": account,
        "verification_code": code,
        "verification_instructions": "Replace any old code in the public profile bio/about section with this code, then verify ownership.",
    }


@app.delete("/api/self/social-accounts/{platform}")
async def delete_own_social_account(
    platform: str, request: Request, user: dict = Depends(require_auth)
):
    _require_account_owner(user)
    from backend.services.platform_registry import normalize_platform

    slug = normalize_platform(platform)
    if not slug:
        raise HTTPException(400, "Unknown platform")
    ok = delete_social_account(user["id"], slug)
    if not ok:
        raise HTTPException(404, "Account not found")
    write_audit(
        user["id"],
        user["role_type"],
        "SOCIAL_ACCOUNT_DELETED",
        "user",
        user["id"],
        payload={"platform": slug},
        ip=_client_ip(request),
    )
    return {"ok": True}


@app.post("/api/self/analyze")
async def analyze_own_account(
    data: dict, request: Request, user: dict = Depends(require_auth)
):
    """Adult analyzes only own connected accounts (ownership enforced).

    Runs real per-platform retrieval and model scoring. If nothing could be
    retrieved, the session is recorded as ``no_data`` — never a fake score.
    """
    raise HTTPException(
        403,
        "Analysis is performed only by your assigned counsellor after account ownership is verified and consent is valid.",
    )
    _check_analysis_rate_limit(user["id"])
    from backend.services.platform_registry import normalize_platform
    from backend.services.self_analysis import run_self_analysis

    platform = (data.get("platform") or "").strip()
    slugs: list[str] = []
    if platform:
        slug = normalize_platform(platform)
        if not slug:
            raise HTTPException(400, "Unknown platform")
        from backend.database import get_social_accounts

        connected_accounts = get_social_accounts(user["id"])
        if connected_accounts and not any(
            a.get("platform") == slug for a in connected_accounts
        ):
            raise HTTPException(
                400, f"Connect your {slug} account before analysing it."
            )
        slugs = [slug]

    try:
        session = await run_self_analysis(user["id"], slugs)
    except Exception as exc:  # noqa: BLE001
        raise inference_http_error(exc)

    write_audit(
        user["id"],
        user["role_type"],
        "SELF_ANALYSIS",
        "analysis_session",
        session["id"],
        payload={"platforms": slugs, "status": session.get("status")},
        ip=_client_ip(request),
    )
    return {"session": _decode_session_json(session)}


@app.get("/api/v1/students/{student_id}/analysis-sessions")
async def list_analysis_sessions(
    student_id: str,
    user: dict = Depends(require_auth),
    limit: int = 50,
    offset: int = 0,
):
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    if user["id"] == student_id:
        pass
    elif user["role_type"] == "admin":
        pass
    else:
        _require_counsellor_student_access(user, student_id, require_consent=False)
        # history remains auditable even after consent revoked; only new analysis requires valid consent
    sessions = get_analysis_sessions_for_student(student_id, limit=limit, offset=offset)
    total = len(get_analysis_sessions_for_student(student_id, limit=1000, offset=0))
    return {"sessions": sessions, "total": total, "limit": limit, "offset": offset}


@app.get("/api/self/analysis-sessions")
async def list_own_analysis_sessions(
    user: dict = Depends(require_auth), limit: int = 50, offset: int = 0
):
    _require_self_adult(user)
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    sessions = get_analysis_sessions_for_student(
        user["id"], limit=limit, offset=offset, analysis_type="self"
    )
    decoded = [_decode_session_json(s) for s in sessions]
    return {
        "sessions": decoded,
        "total": len(
            get_analysis_sessions_for_student(
                user["id"], limit=1000, offset=0, analysis_type="self"
            )
        ),
        "limit": limit,
        "offset": offset,
    }


@app.get("/api/self/analysis-sessions/{session_id}")
async def get_own_analysis_session(session_id: str, user: dict = Depends(require_auth)):
    _require_self_adult(user)
    from backend.database import get_analysis_session_for_student

    sess = get_analysis_session_for_student(
        session_id, user["id"], analysis_type="self"
    )
    if not sess:
        raise HTTPException(404, "Session not found")
    return {"session": _decode_session_json(sess)}


@app.get("/api/v1/analysis-sessions/{session_id}")
async def get_single_analysis_session(
    session_id: str, user: dict = Depends(require_auth)
):
    sess = get_analysis_session(session_id)
    if not sess:
        raise HTTPException(404, "Session not found")
    student_id = sess["student_id"]
    if user["id"] == student_id or user["role_type"] == "admin":
        return {"session": sess}
    if (
        user.get("institution_id")
        and sess.get("institution_id")
        and user["institution_id"] != sess["institution_id"]
    ):
        raise HTTPException(403, "Session not in your institution")
    _require_counsellor_student_access(user, student_id)
    return {"session": sess}


@app.post("/api/auth/logout")
async def logout(authorization: str = Header(...), user: dict = Depends(require_auth)):
    jti = user.get("_token_jti", "")
    if jti:
        exp = user.get("_token_exp")
        expires_at = (
            datetime.fromtimestamp(exp, timezone.utc).isoformat() if exp else None
        )
        blacklist_token(jti, expires_at=expires_at)
    logger.info("Logout: user=%s", user["id"])
    return {"ok": True}


@app.post("/api/auth/google")
async def google_auth(data: dict, request: Request):
    client_ip = _client_ip(request)
    _check_rate_limit(f"google:{client_ip}")

    if not await verify_recaptcha_token(data.get("recaptcha_token")):
        raise HTTPException(403, "reCAPTCHA verification failed")

    access_token = data.get("access_token")
    if not access_token:
        raise HTTPException(400, "access_token required")

    try:
        from supabase import create_client

        supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
        user_resp = supabase.auth.get_user(access_token)
        sb_user = user_resp.user
    except Exception as e:
        logger.warning("Google auth failed ip=%s: %s", client_ip, e)
        raise HTTPException(401, "Invalid Supabase token")

    # The account identity must come from the verified Supabase session. The
    # client-supplied body is attacker-controlled and must never influence which
    # account is matched or created (an attacker could otherwise log in as any
    # existing user by passing their email alongside a valid Google token).
    email = (sb_user.email or "").strip().lower()
    if not email:
        raise HTTPException(401, "Invalid Supabase token")

    existing = get_user_by_email(email)
    if existing:
        user = existing
    else:
        # Display name only for brand-new accounts, sanitised and length-capped.
        # Existing accounts keep their stored name.
        client_name = (data.get("name") or "").strip()
        verified_name = (
            sb_user.user_metadata.get("full_name") if sb_user.user_metadata else None
        ) or ""
        name = (
            verified_name
            or client_name
            or email.split("@")[0].replace(".", " ").title()
        )
        name = str(name).strip()[:80] or email.split("@")[0].replace(".", " ").title()
        create_user(email, name, "", role_type="student")
        user = get_user_by_email(email)

    token = create_access_token(user["id"], user["role_type"])
    return {
        "email": user["email"],
        "name": user["name"],
        "role": user["role_type"].capitalize(),
        "role_type": user["role_type"],
        "referral_code": _generate_referral_code(),
        "terms_accepted": bool(user.get("terms_accepted_at")),
        "user_category": _auth_user_category(user),
        "institution_id": user.get("institution_id"),
        "profile_completed": bool(user.get("profile_completed_at"))
        if user.get("role_type") in {"school_admin", "counsellor"}
        else True,
        "staff_role": user.get("role_type")
        if _auth_user_category(user) == "staff"
        else None,
        "access_token": token,
    }


# ── Mastodon handle normalization ──────────────────────────────────────
# Parses Mastodon handles of the form @username@instance and derives
# the profile URL (https://instance/@username).  Used when saving social
# accounts and when the profile_url is not pre‑stored.
_MASTODON_HANDLE_RE = re.compile(r"^@([^@]+)@([^@]+)$")


def _normalize_mastodon_handle(
    handle: str | None,
) -> tuple[str | None, str | None, str | None]:
    """Return (canonical_handle, instance, profile_url) for a Mastodon handle.

    If the handle is not a Mastodon handle, returns (handle, None, None).
    """
    if not handle:
        return None, None, None
    m = _MASTODON_HANDLE_RE.match(handle)
    if m:
        username, instance = m.group(1), m.group(2)
        canonical = f"@{username}@{instance}"
        profile_url = f"https://{instance}/@{username}"
        return canonical, instance, profile_url
    return handle, None, None


# ── Analysis routes ──────────────────────────────────────────────────


@app.post("/api/analysis/text")
async def analyze_text(req: TextAnalysisRequest, user: dict = Depends(require_auth)):
    _check_analysis_rate_limit(user["id"])
    try:
        prob, ms = await predict_one(req.text)
    except Exception as exc:
        logger.error("ML inference error: %s", exc)
        raise HTTPException(
            503,
            "Analysis service temporarily unavailable. Please try again in a moment.",
        )

    cls = "Suicidal" if prob >= 0.5 else "Non-Suicidal"
    save_analysis(user["id"], "text", req.text, prob, cls)
    analytics = get_analytics(user["id"])
    assessment = assess_risk(prob)

    return TextAnalysisResponse(
        prob=prob,
        latency_ms=ms,
        analytics=analytics,
        risk_tier=assessment.tier,
        alert_eligible=assessment.alert_eligible,
        crisis_escalation_eligible=assessment.crisis_escalation_eligible,
    )


@app.post("/api/analysis/image")
async def analyze_image(
    file: UploadFile = File(...), user: dict = Depends(require_auth)
):
    _check_analysis_rate_limit(user["id"])
    MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10 MB
    try:
        import pytesseract
        from PIL import Image, UnidentifiedImageError

        contents = await file.read()
        if len(contents) > MAX_IMAGE_SIZE:
            raise HTTPException(413, "Image file too large (max 10 MB)")
        try:
            img = Image.open(io.BytesIO(contents)).convert("RGB")
        except UnidentifiedImageError:
            raise HTTPException(400, "Invalid or unrecognised image format")
        text = pytesseract.image_to_string(img, config="--psm 6").strip()
        if not text:
            raise HTTPException(400, "No text could be extracted from the image")

        try:
            prob, ms = await predict_one(text)
        except Exception as exc:
            logger.error("ML inference error: %s", exc)
            raise HTTPException(
                503,
                "Analysis service temporarily unavailable. Please try again in a moment.",
            )
        cls = "Suicidal" if prob >= 0.5 else "Non-Suicidal"
        save_analysis(user["id"], "image", "[Image OCR] " + text, prob, cls)
        analytics = get_analytics(user["id"])
        assessment = assess_risk(prob)

        return TextAnalysisResponse(
            prob=prob,
            latency_ms=ms,
            analytics=analytics,
            risk_tier=assessment.tier,
            alert_eligible=assessment.alert_eligible,
            crisis_escalation_eligible=assessment.crisis_escalation_eligible,
        )
    except HTTPException:
        raise
    except ImportError:
        raise HTTPException(501, "OCR not available (pytesseract not installed)")
    except Exception as e:
        logger.error("Image analysis error: %s", e)
        raise HTTPException(500, "Image analysis failed")


# ── Platform routes ──────────────────────────────────────────────────


def _build_platform_result(posts: list, platform_key: str) -> dict:
    scores = np.array([p["risk_score"] for p in posts])
    df = [
        {
            k: p.get(k)
            for k in [
                "text",
                "date",
                "url",
                "risk_score",
                "raw_risk_score",
                "low_context",
                "adjustment_reason",
                "word_count",
                "char_count",
                "subreddit",
                "type",
            ]
        }
        for p in posts
    ]
    return {
        "df": df,
        "overall": float(np.percentile(scores, 85)) if len(scores) > 0 else 0.0,
        "n_posts": len(posts),
        "n_high": int((scores >= 0.55).sum()) if len(scores) > 0 else 0,
        "signals": detect_socioeconomic(posts),
        "platform_key": platform_key,
    }


def _run_scraper_worker(platform: str, url: str, months: int = 3) -> list:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise HTTPException(400, "Enter a valid profile URL")
    _validate_external_host(parsed.hostname)

    worker = Path(__file__).resolve().parent.parent / "scraper_worker.py"
    if not worker.exists():
        raise HTTPException(500, "Scraper worker is missing")

    try:
        result = subprocess.run(
            [sys.executable, str(worker), platform, url, str(months)],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(
            408, "Scraping timed out. Try again or use File Upload with an archive."
        )

    if result.returncode != 0:
        err = (
            result.stderr.strip().splitlines()[-1]
            if result.stderr.strip()
            else "Scraper failed"
        )
        raise HTTPException(400, err)

    try:
        data = json.loads(result.stdout.strip())
    except json.JSONDecodeError:
        logger.error("Could not parse scraper output: %s", result.stdout[:500])
        raise HTTPException(500, "Could not parse scraper output")

    if not data.get("ok"):
        raise HTTPException(400, data.get("error") or "Scraper failed")

    posts = []
    for p in data.get("posts", []):
        text = (p.get("text") or "").strip()
        if not text:
            continue
        try:
            date = datetime.fromisoformat(str(p.get("date", "")).replace("Z", "+00:00"))
        except ValueError:
            date = datetime.now(timezone.utc)
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        posts.append(
            {
                "text": text,
                "date": date.isoformat(),
                "url": p.get("url")
                or ("" if platform in {"facebook", "twitter"} else url),
            }
        )
    return posts


def _login_bluesky(identifier: str, password: str) -> str:
    url = "https://bsky.social/xrpc/com.atproto.server.createSession"
    payload = json.dumps({"identifier": identifier, "password": password}).encode(
        "utf-8"
    )
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "MindGuard/3.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))["accessJwt"]
    except urllib.error.HTTPError as exc:
        if exc.code in (400, 401):
            raise HTTPException(401, f"Login failed for Bluesky handle '{identifier}'.")
        raise HTTPException(exc.code, f"Bluesky login failed with HTTP {exc.code}.")
    except Exception as exc:
        raise HTTPException(502, f"Could not reach Bluesky login API: {exc}")


def _fetch_bluesky_posts(handle: str, access_token: str) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=90)
    headers = {"User-Agent": "MindGuard/3.0", "Authorization": f"Bearer {access_token}"}
    resolve_url = (
        "https://bsky.social/xrpc/com.atproto.identity.resolveHandle?"
        + urlencode({"handle": handle})
    )
    try:
        req = urllib.request.Request(resolve_url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            did = json.loads(resp.read().decode("utf-8"))["did"]
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise HTTPException(404, f"Handle not found: {handle}.")
        raise HTTPException(
            exc.code, f"Could not resolve Bluesky handle (HTTP {exc.code})."
        )
    except Exception as exc:
        raise HTTPException(502, f"Could not reach Bluesky API: {exc}")

    posts: list[dict] = []
    cursor = None

    def public_bluesky_url_available(post_url: str) -> bool:
        try:
            parsed = urlparse(post_url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                return False
            _validate_external_host(parsed.hostname)
            req = urllib.request.Request(
                post_url, headers={"User-Agent": "MindGuard/3.0"}
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                html = resp.read(300_000).decode("utf-8", errors="ignore").lower()
                return resp.status < 400 and "post not found" not in html
        except Exception:
            return False

    for _ in range(10):
        params = {"actor": did, "limit": 100}
        if cursor:
            params["cursor"] = cursor
        feed_url = "https://bsky.social/xrpc/app.bsky.feed.getAuthorFeed?" + urlencode(
            params
        )
        try:
            req = urllib.request.Request(feed_url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise HTTPException(
                exc.code, f"Could not fetch Bluesky posts (HTTP {exc.code})."
            )
        except Exception as exc:
            raise HTTPException(502, f"Could not fetch Bluesky posts: {exc}")

        feed = data.get("feed", [])
        if not feed:
            break
        oldest_in_page = None
        for item in feed:
            post = item.get("post", {})
            record = post.get("record", {})
            created_at = record.get("createdAt", "")
            try:
                created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            except ValueError:
                continue
            oldest_in_page = created
            if created < cutoff:
                continue
            text = (record.get("text") or "").strip()
            if len(text) <= 5:
                continue
            uri = post.get("uri", "")
            rkey = uri.split("/")[-1] if uri else ""
            post_url = f"https://bsky.app/profile/{handle}/post/{rkey}"
            if not public_bluesky_url_available(post_url):
                continue
            posts.append(
                {
                    "text": text,
                    "date": created.isoformat(),
                    "url": post_url,
                }
            )
        cursor = data.get("cursor")
        if not cursor:
            break
        if oldest_in_page and oldest_in_page < cutoff:
            break
    posts.sort(key=lambda p: p["date"])
    return posts


# Per-user platform results to prevent cross-user data leakage.
_platform_results: dict[str, dict] = defaultdict(dict)


def _fetch_reddit_rss_posts(username: str) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=182)
    safe_username = username.strip().lstrip("u/")
    if not re.match(r"^[A-Za-z0-9_-]{3,20}$", safe_username):
        raise HTTPException(400, "Enter a valid Reddit username.")

    feeds = [
        ("Post", f"https://www.reddit.com/user/{safe_username}/submitted/.rss"),
        ("Comment", f"https://www.reddit.com/user/{safe_username}/comments/.rss"),
    ]
    namespaces = {
        "atom": "http://www.w3.org/2005/Atom",
        "media": "http://search.yahoo.com/mrss/",
    }
    raw_posts: list[dict] = []
    seen_urls = set()
    feed_errors: list[str] = []

    for source_type, feed_url in feeds:
        try:
            req = urllib.request.Request(
                feed_url,
                headers={
                    "User-Agent": "Mozilla/5.0 (MindGuard local research prototype; Reddit RSS mode)"
                },
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                xml_text = resp.read().decode("utf-8", errors="ignore")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                continue
            feed_errors.append(f"{source_type} feed HTTP {exc.code}")
            continue
        except Exception as exc:
            feed_errors.append(f"{source_type} feed error: {exc}")
            continue

        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            continue

        for entry in root.findall("atom:entry", namespaces):
            title = (
                entry.findtext("atom:title", default="", namespaces=namespaces) or ""
            ).strip()
            content = (
                entry.findtext("atom:content", default="", namespaces=namespaces) or ""
            ).strip()
            content = re.sub(r"<[^>]+>", " ", content)
            content = re.sub(r"\s+", " ", content).strip()
            published = (
                entry.findtext("atom:published", default="", namespaces=namespaces)
                or ""
            )
            updated = (
                entry.findtext("atom:updated", default="", namespaces=namespaces) or ""
            )
            date_text = published or updated
            try:
                created = datetime.fromisoformat(date_text.replace("Z", "+00:00"))
            except ValueError:
                created = datetime.now(timezone.utc)
            if created < cutoff:
                continue

            link = ""
            for link_el in entry.findall("atom:link", namespaces):
                href = link_el.attrib.get("href", "")
                if href and "reddit.com" in href:
                    link = href
                    break
            if not link or link in seen_urls:
                continue
            seen_urls.add(link)

            text = (
                f"{title} {content}".strip()
                if source_type == "Post"
                else content or title
            )
            text = re.sub(r"\s+", " ", text).strip()
            if len(text) <= 10 or text.lower() in {"[deleted]", "[removed]"}:
                continue

            subreddit_match = re.search(r"/r/([^/]+)/", link)
            raw_posts.append(
                {
                    "text": text,
                    "date": created.isoformat(),
                    "url": link,
                    "subreddit": subreddit_match.group(1) if subreddit_match else "",
                    "type": source_type,
                }
            )

    if not raw_posts and feed_errors:
        raise HTTPException(
            502, "Could not fetch Reddit RSS feeds: " + "; ".join(feed_errors)
        )

    raw_posts.sort(key=lambda p: p["date"])
    return raw_posts


@app.post("/api/platforms/reddit")
async def analyze_reddit(req: PlatformRequest, user: dict = Depends(require_auth)):
    _require_analysis_staff(user)
    _check_analysis_rate_limit(user["id"])
    client_id = req.client_id or os.getenv("REDDIT_CLIENT_ID", "")
    client_secret = req.client_secret or REDDIT_CLIENT_SECRET
    if not req.username.strip():
        raise HTTPException(400, "Reddit username is required.")

    try:
        username = req.username.strip().lstrip("u/")
        if not client_id or not client_secret:
            raw_posts = _fetch_reddit_rss_posts(username)
            if not raw_posts:
                raise HTTPException(
                    404, f"No RSS posts found for u/{username} in the last 6 months."
                )

            text_col = [clean_text(p["text"]) for p in raw_posts]
            scores = await predict_batch(text_col)
            for i, p in enumerate(raw_posts):
                p.update(calibrate_risk_score(p["text"], float(scores[i])))

            result = _build_platform_result(raw_posts, "reddit")
            result["min_risk"] = req.min_risk
            result["n_show"] = req.n_show
            result["username"] = username
            result["mode"] = "rss"
            _platform_results[user["id"]]["reddit"] = result
            return result

        import praw
        import prawcore

        reddit = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            user_agent="MindGuard/1.0",
        )
        redditor = reddit.redditor(username)
        cutoff = datetime.now(timezone.utc) - timedelta(days=182)

        raw_posts = []
        for submission in redditor.submissions.new(limit=200):
            created = datetime.fromtimestamp(submission.created_utc, tz=timezone.utc)
            if created < cutoff:
                break
            text = f"{submission.title} {submission.selftext or ''}".strip()
            if len(text) <= 10:
                continue
            raw_posts.append(
                {
                    "text": text,
                    "date": created.isoformat(),
                    "url": f"https://reddit.com{submission.permalink}",
                    "subreddit": submission.subreddit.display_name,
                    "type": "post",
                }
            )
        for comment in redditor.comments.new(limit=500):
            created = datetime.fromtimestamp(comment.created_utc, tz=timezone.utc)
            if created < cutoff:
                break
            text = (comment.body or "").strip()
            if len(text) <= 10 or text in ("[deleted]", "[removed]"):
                continue
            raw_posts.append(
                {
                    "text": text,
                    "date": created.isoformat(),
                    "url": f"https://reddit.com{comment.permalink}",
                    "subreddit": comment.subreddit.display_name,
                    "type": "comment",
                }
            )
        raw_posts.sort(key=lambda p: p["date"])

        if not raw_posts:
            raise HTTPException(
                404, f"No posts found for u/{username} in the last 6 months."
            )

        text_col = [clean_text(p["text"]) for p in raw_posts]
        scores = await predict_batch(text_col)
        for i, p in enumerate(raw_posts):
            p.update(calibrate_risk_score(p["text"], float(scores[i])))

        result = _build_platform_result(raw_posts, "reddit")
        result["min_risk"] = req.min_risk
        result["n_show"] = req.n_show
        result["username"] = username
        _platform_results[user["id"]]["reddit"] = result
        return result

    except HTTPException:
        raise
    except InferenceUnavailableError:
        raise
    except ImportError:
        raise HTTPException(501, "PRAW not installed. Install with: pip install praw")
    except prawcore.exceptions.NotFound:
        raise HTTPException(404, f"Reddit user '{req.username}' not found.")
    except prawcore.exceptions.Forbidden:
        raise HTTPException(403, f"Access forbidden for Reddit user '{req.username}'.")
    except prawcore.exceptions.ResponseException as e:
        logger.error("Reddit API error: %s", e)
        raise HTTPException(502, f"Reddit API responded with an error: {e}")
    except Exception as e:
        logger.error("Reddit analysis error: %s", e)
        raise HTTPException(400, f"Reddit analysis failed: {e}")


@app.post("/api/platforms/bluesky")
async def analyze_bluesky(req: PlatformRequest, user: dict = Depends(require_auth)):
    _require_analysis_staff(user)
    _check_analysis_rate_limit(user["id"])
    target_handle = req.handle.strip().lstrip("@")
    login_handle = (req.identifier or req.handle).strip().lstrip("@")
    if target_handle and "." not in target_handle:
        target_handle = f"{target_handle}.bsky.social"
    if login_handle and "." not in login_handle:
        login_handle = f"{login_handle}.bsky.social"
    if not target_handle:
        raise HTTPException(400, "Enter the Bluesky handle you want to analyse.")
    if not login_handle or not req.password:
        raise HTTPException(400, "Enter your Bluesky handle and App Password.")
    try:
        access_token = await asyncio.to_thread(
            _login_bluesky, login_handle, req.password
        )
        raw_posts = await asyncio.to_thread(
            _fetch_bluesky_posts, target_handle, access_token
        )

        if not raw_posts:
            raise HTTPException(
                404, f"No posts found for '{target_handle}' in the last 3 months."
            )

        texts = [clean_text(p["text"]) for p in raw_posts]
        scores = await predict_batch(texts)
        for i, p in enumerate(raw_posts):
            p.update(calibrate_risk_score(p["text"], float(scores[i])))

        result = _build_platform_result(raw_posts, "bluesky")
        result["min_risk"] = req.min_risk
        result["n_show"] = req.n_show
        result["handle"] = target_handle
        _platform_results[user["id"]]["bluesky"] = result
        return result

    except HTTPException:
        raise
    except InferenceUnavailableError:
        raise
    except Exception as e:
        logger.error("Bluesky analysis error: %s", e)
        raise HTTPException(400, f"Bluesky analysis failed: {e}")


@app.post("/api/platforms/mastodon")
async def analyze_mastodon(req: PlatformRequest, user: dict = Depends(require_auth)):
    _require_analysis_staff(user)
    _check_analysis_rate_limit(user["id"])
    if not req.handle:
        raise HTTPException(400, "Handle required")
    handle_input = req.handle.strip().lstrip("@")
    if "@" not in handle_input:
        raise HTTPException(
            400, "Mastodon handle must be in format: username@instance.social"
        )
    parts = handle_input.split("@")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise HTTPException(
            400, "Mastodon handle must be in format: username@instance.social"
        )
    username, instance = parts
    _validate_external_host(instance)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                f"https://{instance}/api/v1/accounts/lookup",
                params={"acct": username},
            )
            if r.status_code == 404:
                raise HTTPException(
                    404, f"Could not find Mastodon account: {username}@{instance}"
                )
            r.raise_for_status()
            acct = r.json()

            raw_posts = []
            max_id = None
            cutoff = datetime.now(timezone.utc) - timedelta(days=90)

            async def public_status_url_available(status_url: str) -> bool:
                if not status_url:
                    return False
                parsed_url = urlparse(status_url)
                if (
                    parsed_url.scheme not in {"http", "https"}
                    or not parsed_url.hostname
                ):
                    return False
                _validate_external_host(parsed_url.hostname)
                try:
                    check = await client.head(
                        status_url, follow_redirects=True, timeout=8.0
                    )
                    if check.status_code in {405, 501}:
                        check = await client.get(
                            status_url, follow_redirects=True, timeout=8.0
                        )
                    return 200 <= check.status_code < 400
                except Exception:
                    return False

            for _ in range(10):
                params: dict = {"limit": 40, "exclude_replies": False}
                if max_id:
                    params["max_id"] = max_id
                r = await client.get(
                    f"https://{instance}/api/v1/accounts/{acct['id']}/statuses",
                    params=params,
                )
                if r.status_code in {401, 403, 404}:
                    raise HTTPException(
                        r.status_code,
                        "Could not fetch Mastodon posts. The account may be private, restricted, or unavailable.",
                    )
                r.raise_for_status()
                statuses = r.json()
                if not statuses:
                    break

                for s in statuses:
                    try:
                        created = datetime.fromisoformat(
                            s["created_at"].replace("Z", "+00:00")
                        )
                    except (ValueError, KeyError):
                        created = datetime.now(timezone.utc)
                    if created < cutoff:
                        break
                    text = re.sub(r"<[^>]+>", "", s.get("content", "")).strip()
                    if len(text) <= 5:
                        continue
                    status_url = s.get("url", "")
                    if not await public_status_url_available(status_url):
                        continue
                    raw_posts.append(
                        {
                            "text": text,
                            "date": s.get("created_at", ""),
                            "url": status_url,
                        }
                    )
                max_id = statuses[-1]["id"]
                if (
                    raw_posts
                    and datetime.fromisoformat(
                        str(raw_posts[-1]["date"]).replace("Z", "+00:00")
                    )
                    < cutoff
                ):
                    break

        if not raw_posts:
            raise HTTPException(404, "No posts found or account is private/not found.")

        texts = [clean_text(p["text"]) for p in raw_posts]
        scores = await predict_batch(texts)
        for i, p in enumerate(raw_posts):
            p.update(calibrate_risk_score(p["text"], float(scores[i])))

        result = _build_platform_result(raw_posts, "mastodon")
        result["min_risk"] = req.min_risk
        result["n_show"] = req.n_show
        result["handle"] = f"{username}@{instance}"
        _platform_results[user["id"]]["mastodon"] = result
        return result

    except HTTPException:
        raise
    except InferenceUnavailableError:
        raise
    except httpx.HTTPStatusError as e:
        logger.error("Mastodon HTTP status error: %s", e)
        raise HTTPException(
            400, f"Mastodon API returned an error: HTTP {e.response.status_code}"
        )
    except httpx.RequestError as e:
        logger.error("Mastodon network error: %s", e)
        raise HTTPException(400, f"Could not reach Mastodon API: {e}")
    except Exception as e:
        logger.error("Mastodon analysis error: %s", e)
        raise HTTPException(400, f"Mastodon analysis failed: {e}")


def _download_and_transcribe_video(
    video_url: str, max_seconds: int = 600
) -> tuple[str, str]:
    _validate_public_video_url(video_url)
    import yt_dlp
    from faster_whisper import WhisperModel

    with tempfile.TemporaryDirectory() as tmpdir:
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": os.path.join(tmpdir, "audio.%(ext)s"),
            "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}],
            "quiet": True,
            "noplaylist": True,
            "socket_timeout": 90,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])

        audio_file = next(
            (os.path.join(tmpdir, f) for f in os.listdir(tmpdir) if f.endswith(".mp3")),
            None,
        )
        if not audio_file:
            raise RuntimeError("Could not download audio")

        trimmed = os.path.join(tmpdir, "trimmed.mp3")
        proc = subprocess.run(
            ["ffmpeg", "-i", audio_file, "-t", str(max_seconds), "-y", trimmed],
            capture_output=True,
            timeout=max(180, max_seconds // 2),
        )
        if proc.returncode != 0 and not os.path.exists(trimmed):
            raise RuntimeError("Audio trimming failed")

        target = trimmed if os.path.exists(trimmed) else audio_file
        whisper = WhisperModel("tiny", device="cpu", compute_type="int8")
        segments, _ = whisper.transcribe(target)
        transcript = " ".join(seg.text.strip() for seg in segments).strip()
        return transcript, target


@app.post("/api/platforms/youtube")
async def analyze_youtube(req: PlatformRequest, user: dict = Depends(require_auth)):
    _require_analysis_staff(user)
    _check_analysis_rate_limit(user["id"])
    if not req.channel_url:
        raise HTTPException(400, "YouTube channel or video URL required")
    try:
        api_key = req.api_key.strip()
        channel_id = None
        channel_input = req.channel_url.strip()
        lowered_input = channel_input.lower()

        is_video_url = (
            "youtube.com/watch" in lowered_input
            or "youtu.be/" in lowered_input
            or "youtube.com/shorts/" in lowered_input
            or "youtube.com/live/" in lowered_input
        )

        if is_video_url:
            transcript, _ = await asyncio.to_thread(
                _download_and_transcribe_video, channel_input, 600
            )
            if not transcript.strip():
                raise HTTPException(
                    422, "No speech transcript was returned, so no prediction was made."
                )

            prob, _ = await predict_one(transcript)
            raw_posts = [
                {
                    "text": transcript,
                    "date": datetime.now(timezone.utc).isoformat(),
                    "url": channel_input,
                    "type": "Transcript",
                    **calibrate_risk_score(transcript, float(prob)),
                }
            ]

            result = _build_platform_result(raw_posts, "youtube")
            result["min_risk"] = req.min_risk
            result["n_show"] = req.n_show
            result["channel"] = channel_input
            result["analysis_mode"] = "video_transcript"
            _platform_results[user["id"]]["youtube"] = result
            return result

        if not api_key:
            raise HTTPException(
                400,
                "YouTube API key required for channel analysis. Direct video URLs can be analysed without an API key.",
            )

        async with httpx.AsyncClient(timeout=10.0) as client:
            if "youtube.com/channel/" in channel_input:
                channel_id = (
                    channel_input.split("youtube.com/channel/")[-1]
                    .split("/")[0]
                    .split("?")[0]
                )
            elif "youtube.com/@" in channel_input:
                handle = (
                    channel_input.split("youtube.com/@")[-1].split("/")[0].split("?")[0]
                )
                r = await client.get(
                    "https://www.googleapis.com/youtube/v3/channels",
                    params={"part": "id", "forHandle": handle, "key": api_key},
                )
                r.raise_for_status()
                items = r.json().get("items", [])
                if items:
                    channel_id = items[0]["id"]
            else:
                handle = channel_input.lstrip("@")
                r = await client.get(
                    "https://www.googleapis.com/youtube/v3/channels",
                    params={"part": "id", "forHandle": handle, "key": api_key},
                )
                r.raise_for_status()
                items = r.json().get("items", [])
                if items:
                    channel_id = items[0]["id"]

            if not channel_id:
                raise HTTPException(
                    400,
                    "Could not resolve YouTube channel. Use a channel URL or @handle.",
                )

            raw_posts = []
            cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            r = await client.get(
                "https://www.googleapis.com/youtube/v3/search",
                params={
                    "part": "id,snippet",
                    "channelId": channel_id,
                    "type": "video",
                    "order": "date",
                    "maxResults": 50,
                    "publishedAfter": cutoff,
                    "key": api_key,
                },
            )
            r.raise_for_status()
            for item in r.json().get("items", []):
                vid_id = item["id"].get("videoId", "")
                snippet = item.get("snippet", {})
                title = snippet.get("title", "")
                desc = snippet.get("description", "")
                published = snippet.get("publishedAt", "")
                text = f"{title} {desc}".strip()
                if len(text) > 5:
                    raw_posts.append(
                        {
                            "text": text,
                            "date": published,
                            "url": f"https://youtube.com/watch?v={vid_id}"
                            if vid_id
                            else "",
                            "type": "Title/Description",
                            "video_id": vid_id,
                        }
                    )
                if not vid_id:
                    continue
                try:
                    cr = await client.get(
                        "https://www.googleapis.com/youtube/v3/commentThreads",
                        params={
                            "part": "snippet",
                            "videoId": vid_id,
                            "maxResults": 20,
                            "order": "relevance",
                            "key": api_key,
                        },
                    )
                    cr.raise_for_status()
                    for c in cr.json().get("items", []):
                        comment_text = c["snippet"]["topLevelComment"]["snippet"].get(
                            "textDisplay", ""
                        )
                        comment_text = re.sub(r"<[^>]+>", "", comment_text).strip()
                        if len(comment_text) > 5:
                            raw_posts.append(
                                {
                                    "text": comment_text,
                                    "date": published,
                                    "url": f"https://youtube.com/watch?v={vid_id}",
                                    "type": "Comment",
                                    "video_id": vid_id,
                                }
                            )
                except Exception:
                    pass

            transcript_limit = min(req.transcript_limit, 3)
            if req.transcribe_videos and transcript_limit > 0:
                transcribed = 0
                videos_to_transcribe = []
                seen_video_ids = set()
                for post in raw_posts:
                    vid_id = post.get("video_id")
                    if vid_id and vid_id not in seen_video_ids:
                        seen_video_ids.add(vid_id)
                        videos_to_transcribe.append(
                            {
                                "video_id": vid_id,
                                "date": post.get("date", ""),
                                "url": post.get("url", ""),
                            }
                        )
                    if len(videos_to_transcribe) >= transcript_limit:
                        break

                for video in videos_to_transcribe:
                    try:
                        transcript, _ = await asyncio.to_thread(
                            _download_and_transcribe_video, video["url"], 600
                        )
                    except Exception as exc:
                        logger.warning(
                            "Could not transcribe YouTube video %s: %s",
                            video["video_id"],
                            exc,
                        )
                        continue
                    if len(transcript.strip()) > 5:
                        raw_posts.append(
                            {
                                "text": transcript.strip(),
                                "date": video["date"],
                                "url": video["url"],
                                "type": "Transcript",
                                "video_id": video["video_id"],
                            }
                        )
                        transcribed += 1

        if not raw_posts:
            raise HTTPException(404, "No content found in the last 3 months.")
        raw_posts.sort(key=lambda p: p["date"])

        texts = [clean_text(p["text"]) for p in raw_posts]
        scores = await predict_batch(texts)
        for i, p in enumerate(raw_posts):
            p.update(calibrate_risk_score(p["text"], float(scores[i])))

        result = _build_platform_result(raw_posts, "youtube")
        result["min_risk"] = req.min_risk
        result["n_show"] = req.n_show
        result["channel"] = channel_input
        result["transcribed_videos"] = sum(
            1 for p in raw_posts if p.get("type") == "Transcript"
        )
        result["transcript_limit"] = (
            min(req.transcript_limit, 3) if req.transcribe_videos else 0
        )
        _platform_results[user["id"]]["youtube"] = result
        return result

    except HTTPException:
        raise
    except InferenceUnavailableError:
        raise
    except ImportError:
        raise HTTPException(501, "Video processing dependencies not installed")
    except subprocess.TimeoutExpired:
        raise HTTPException(408, "Video processing timed out")
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error("YouTube analysis error: %s", e)
        raise HTTPException(400, "YouTube analysis failed")


@app.post("/api/platforms/video")
async def analyze_video(req: PlatformRequest, user: dict = Depends(require_auth)):
    _require_analysis_staff(user)
    _check_analysis_rate_limit(user["id"])
    if not req.video_url:
        raise HTTPException(400, "Video URL required")
    try:
        transcript, _ = await asyncio.to_thread(
            _download_and_transcribe_video, req.video_url, 600
        )
        if not transcript.strip():
            raise HTTPException(
                422, "No speech transcript was returned, so no prediction was made."
            )
        prob, ms = await predict_one(transcript)
        label, color, level = risk_label(prob)
        result = {
            "ok": True,
            "risk": prob,
            "transcription": transcript,
            "label": label,
            "latency_ms": ms,
            "video_url": req.video_url,
            "signals": detect_socioeconomic([{"text": transcript}]),
        }
        _platform_results[user["id"]]["video"] = result
        return result

    except HTTPException:
        raise
    except InferenceUnavailableError:
        raise
    except ImportError:
        raise HTTPException(501, "Video processing dependencies not installed")
    except subprocess.TimeoutExpired:
        raise HTTPException(408, "Video processing timed out")
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error("Video analysis error: %s", e)
        raise HTTPException(400, "Video analysis failed")


@app.post("/api/platforms/facebook")
async def analyze_facebook(req: PlatformRequest, user: dict = Depends(require_auth)):
    _require_analysis_staff(user)
    _check_analysis_rate_limit(user["id"])
    if not req.profile_url:
        raise HTTPException(400, "Facebook profile URL is required")
    if "facebook.com" not in req.profile_url.lower():
        raise HTTPException(
            400, "Enter a full Facebook URL, e.g. https://www.facebook.com/username"
        )

    try:
        raw_posts = await asyncio.to_thread(
            _run_scraper_worker, "facebook", req.profile_url, req.months
        )
        if not raw_posts:
            raise HTTPException(
                404,
                "No public posts found. The profile may be private or Facebook blocked the request.",
            )

        texts = [clean_text(p["text"]) for p in raw_posts]
        scores = await predict_batch(texts)
        for i, p in enumerate(raw_posts):
            p.update(calibrate_risk_score(p["text"], float(scores[i])))

        result = _build_platform_result(raw_posts, "facebook")
        result["min_risk"] = req.min_risk
        result["n_show"] = req.n_show
        result["url"] = req.profile_url
        _platform_results[user["id"]]["facebook"] = result
        return result

    except HTTPException:
        raise
    except InferenceUnavailableError:
        raise
    except ImportError:
        raise HTTPException(
            501, "Playwright is not installed. Install with: pip install playwright"
        )
    except Exception as e:
        logger.error("Facebook analysis error: %s", e)
        raise HTTPException(400, f"Facebook analysis failed: {e}")


@app.post("/api/platforms/twitter")
async def analyze_twitter(req: PlatformRequest, user: dict = Depends(require_auth)):
    _require_analysis_staff(user)
    _check_analysis_rate_limit(user["id"])
    if not req.profile_url:
        raise HTTPException(400, "Twitter/X profile URL is required")
    lowered = req.profile_url.lower()
    if "twitter.com" not in lowered and "x.com" not in lowered:
        raise HTTPException(
            400, "Enter a valid Twitter/X URL, e.g. https://x.com/username"
        )

    try:
        raw_posts = await asyncio.to_thread(
            _run_scraper_worker, "twitter", req.profile_url, 3
        )
        if not raw_posts:
            raise HTTPException(
                404,
                "No tweets found. The profile may be private or Twitter/X may require login.",
            )

        texts = [clean_text(p["text"]) for p in raw_posts]
        scores = await predict_batch(texts)
        for i, p in enumerate(raw_posts):
            p.update(calibrate_risk_score(p["text"], float(scores[i])))

        result = _build_platform_result(raw_posts, "twitter")
        result["min_risk"] = req.min_risk
        result["n_show"] = req.n_show
        result["url"] = req.profile_url
        _platform_results[user["id"]]["twitter"] = result
        return result

    except HTTPException:
        raise
    except InferenceUnavailableError:
        raise
    except ImportError:
        raise HTTPException(
            501, "Playwright is not installed. Install with: pip install playwright"
        )
    except Exception as e:
        logger.error("Twitter/X analysis error: %s", e)
        raise HTTPException(400, f"Twitter/X analysis failed: {e}")


@app.post("/api/platforms/file")
async def analyze_file(
    file: UploadFile = File(...),
    min_risk: float = 0.0,
    n_show: int = 20,
    user: dict = Depends(require_auth),
):
    _require_analysis_staff(user)
    _check_analysis_rate_limit(user["id"])
    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
    try:
        contents = await file.read()
        if len(contents) > MAX_FILE_SIZE:
            raise HTTPException(413, "File too large (max 50 MB)")
        text = contents.decode("utf-8", errors="replace")
        lines = text.split("\n")

        raw_posts = []
        wa_pattern = re.compile(r"\[\d{1,2}/\d{1,2}/\d{2,4}.*?\] .*?: ")

        whatsapp_mode = bool(wa_pattern.search(text[:500]))

        if whatsapp_mode:
            current_text = ""
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                m = re.match(r"\[(.*?)\] (.*?): (.*)", line)
                if m:
                    if current_text.strip():
                        raw_posts.append(
                            {"text": current_text.strip(), "date": "", "url": ""}
                        )
                    current_text = m.group(3)
                else:
                    current_text += " " + line
            if current_text.strip():
                raw_posts.append({"text": current_text.strip(), "date": "", "url": ""})
        else:
            for line in lines:
                line = line.strip()
                if line:
                    raw_posts.append({"text": line, "date": "", "url": ""})

        if not raw_posts:
            raise HTTPException(400, "No posts found in file")

        texts = [clean_text(p["text"]) for p in raw_posts]
        scores = await predict_batch(texts)
        for i, p in enumerate(raw_posts):
            p.update(calibrate_risk_score(p["text"], float(scores[i])))

        result = _build_platform_result(raw_posts, "file")
        result["min_risk"] = min_risk
        result["n_show"] = n_show
        result["filename"] = file.filename
        return result

    except HTTPException:
        raise
    except InferenceUnavailableError:
        raise
    except Exception as e:
        logger.error("File analysis error: %s", e)
        raise HTTPException(400, "File analysis failed")


@app.get("/api/platforms/unified")
async def get_unified(user: dict = Depends(require_auth)):
    _require_analysis_staff(user)
    _check_analysis_rate_limit(user["id"])
    user_results = _platform_results.get(user["id"], {})
    platforms = {}
    for key in ["reddit", "bluesky", "mastodon", "youtube", "file"]:
        r = user_results.get(key)
        if r:
            platforms[key] = {
                "overall": r["overall"],
                "n_posts": r["n_posts"],
                "n_high": r["n_high"],
            }
    if user_results.get("video"):
        v = user_results["video"]
        platforms["Video"] = {
            "overall": v["risk"],
            "n_posts": 1,
            "n_high": 1 if v["risk"] >= 0.55 else 0,
        }

    scores = [p["overall"] for p in platforms.values()]
    unified = float(np.mean(scores)) if scores else 0.0
    return {"platforms": platforms, "unified_score": unified}


# ── Counsellor management routes (admin only) ───────────────────────────────


def _staff_invitation_email(
    user: dict, token: str, institution_id: str | None
) -> tuple[bool, str]:
    institution_name = "MindGuard"
    if institution_id:
        institution = get_institution_by_id(institution_id)
        if institution:
            institution_name = institution.get("name") or institution_name
    base = os.getenv("APP_BASE_URL", "https://app.mindguardai.me").rstrip("/")
    invite_url = f"{base}/invite?token={token}"
    context = {
        "counsellor_name": user.get("name") or "there",
        "staff_role": user.get("role_type"),
        "institution_name": institution_name,
        "invite_url": invite_url,
        "setup_url": invite_url,
        "support_email": os.getenv("DEMO_NOTIFY_EMAIL", "support@mindguard.ai"),
        "withdraw_url": f"{base}/privacy",
        "privacy_url": f"{base}/privacy",
        "contact_url": f"{base}/contact",
    }
    subject, body = counsellor_invitation_notification(context)
    return send_html_email(
        user["email"],
        subject,
        body,
        related_type="staff_invitation",
        related_id=user["id"],
        metadata={"role_type": user.get("role_type"), "institution_id": institution_id},
    )


@app.post("/api/institution/staff/{staff_id}/resend")
async def resend_institution_staff_invite_legacy(
    staff_id: str, request: Request, user: dict = Depends(require_auth)
):
    institution_id = _require_institution_admin(user)
    staff = get_user_by_id(staff_id)
    if (
        not staff
        or staff.get("institution_id") != institution_id
        or staff.get("role_type") not in {"school_admin", "counsellor"}
    ):
        raise HTTPException(404, "Institution staff member not found")
    if staff.get("status") == "approved" and not staff.get("invitation_token_hash"):
        raise HTTPException(400, "Staff member has already activated this invitation")
    token = secrets.token_urlsafe(32)
    set_user_invitation(
        staff_id,
        hash_token(token),
        (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
    )
    email_sent, email_error = _staff_invitation_email(staff, token, institution_id)
    write_audit(
        user["id"],
        user["role_type"],
        "STAFF_INVITE_RESENT",
        "user",
        staff_id,
        payload={"email_sent": email_sent},
        ip=_client_ip(request),
    )
    return {"ok": True, "email_sent": email_sent, "email_error": email_error or None}


@app.get("/api/institution/setup")
async def institution_setup(user: dict = Depends(require_auth)):
    institution_id = _require_institution_scope(user)
    if not institution_id:
        raise HTTPException(400, "Select an institution context")
    institution = get_institution_by_id(institution_id)
    conn = __import__("backend.database", fromlist=["get_db"]).get_db()
    staff_rows = conn.execute(
        "SELECT role_type, status FROM users WHERE institution_id = ? AND role_type IN ('school_admin','counsellor')",
        (institution_id,),
    ).fetchall()
    student_count = conn.execute(
        "SELECT COUNT(*) FROM students WHERE institution_id = ? AND deleted_at IS NULL",
        (institution_id,),
    ).fetchone()[0]
    assignment_count = conn.execute(
        "SELECT COUNT(*) FROM counsellor_student_assignments WHERE institution_id = ? AND active = 1",
        (institution_id,),
    ).fetchone()[0]
    consent_pending = conn.execute(
        "SELECT COUNT(*) FROM students s LEFT JOIN consents c ON c.id = s.current_consent_id "
        "WHERE s.institution_id = ? AND s.deleted_at IS NULL AND s.archived_at IS NULL "
        "AND (c.id IS NULL OR c.status != 'ACCEPTED')",
        (institution_id,),
    ).fetchone()[0]
    conn.close()
    active_admins = sum(
        1
        for row in staff_rows
        if row["role_type"] == "school_admin"
        and row["status"] in ("approved", "active")
    )
    active_counsellors = sum(
        1
        for row in staff_rows
        if row["role_type"] == "counsellor" and row["status"] in ("approved", "active")
    )
    checks = [
        {
            "key": "school_admin",
            "label": "Activate a school administrator",
            "complete": active_admins > 0,
        },
        {
            "key": "counsellor",
            "label": "Invite at least one counsellor",
            "complete": active_counsellors > 0,
        },
        {
            "key": "roster",
            "label": "Upload the student roster",
            "complete": student_count > 0,
        },
        {
            "key": "assignments",
            "label": "Assign students to counsellors",
            "complete": student_count == 0 or assignment_count >= student_count,
        },
    ]
    next_action = next(
        (item["label"] for item in checks if not item["complete"]),
        "Institution is ready",
    )
    return {
        "institution": institution,
        "checks": checks,
        "next_action": next_action,
        "counts": {
            "school_admins": active_admins,
            "counsellors": active_counsellors,
            "students": student_count,
            "active_assignments": assignment_count,
            "consent_pending": consent_pending,
        },
        "consent_note": f"{consent_pending} student(s) are still awaiting valid consent; this does not prevent operational readiness.",
    }


@app.post("/api/institution/ready")
async def mark_institution_ready(request: Request, user: dict = Depends(require_auth)):
    institution_id = _require_institution_admin(user)
    if not institution_id:
        raise HTTPException(400, "Select an institution context")
    setup = await institution_setup(user)
    incomplete = [item["label"] for item in setup["checks"] if not item["complete"]]
    if incomplete:
        raise HTTPException(
            400, {"message": "Institution setup is incomplete", "items": incomplete}
        )
    updated = update_institution(institution_id, status="ACTIVE")
    write_audit(
        user["id"],
        user["role_type"],
        "INSTITUTION_READY",
        "institution",
        institution_id,
        ip=_client_ip(request),
    )
    return {"ok": True, "institution": updated}


@app.patch("/api/institution/staff/profile")
async def patch_staff_profile(
    data: dict, request: Request, user: dict = Depends(require_auth)
):
    if user.get("role_type") not in {"school_admin", "counsellor"}:
        raise HTTPException(403, "Staff account required")
    updated = update_staff_profile(user["id"], **data)
    write_audit(
        user["id"],
        user["role_type"],
        "STAFF_PROFILE_UPDATED",
        "user",
        user["id"],
        ip=_client_ip(request),
    )
    return {
        "ok": True,
        "profile": _staff_profile_payload(updated or user),
        "user": updated,
    }


@app.get("/api/institution/staff/profile")
async def get_staff_profile(user: dict = Depends(require_auth)):
    if user.get("role_type") not in {"school_admin", "counsellor"}:
        raise HTTPException(403, "Staff account required")
    return _staff_profile_payload(user)


@app.post("/api/admin/counsellors")
async def create_counsellor(
    data: dict, request: Request, user: dict = Depends(require_auth)
):
    """Create a new counsellor account via magic-link invitation (admin only)."""
    if user["role_type"] != "admin":
        raise HTTPException(403, "Admin access required")
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    institution_id = data.get("institution_id")

    if not name or not email:
        raise HTTPException(400, "Name and email are required")
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise HTTPException(400, "Invalid email address")

    existing = get_user_by_email(email)
    if existing:
        raise HTTPException(400, "A user with this email already exists")

    if institution_id:
        from backend.database import get_institution_by_id

        if not get_institution_by_id(institution_id):
            raise HTTPException(400, "Institution not found")

    placeholder_hash = hash_password(secrets.token_urlsafe(32))
    counsellor = create_user(
        email,
        name,
        placeholder_hash,
        role_type="counsellor",
        institution_id=institution_id,
    )

    from backend.services.crypto import hash_token

    token = secrets.token_urlsafe(32)
    token_hash = hash_token(token)
    expires_at = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    set_user_invitation(counsellor["id"], token_hash, expires_at)

    write_audit(
        user["id"],
        "admin",
        "COUNSELLOR_CREATED",
        "user",
        counsellor["id"],
        payload={
            "counsellor_name": name,
            "counsellor_email": email,
            "institution_id": institution_id,
        },
        ip=_client_ip(request),
    )

    email_sent, email_error = False, ""
    if email:
        institution_name = "MindGuard"
        if institution_id:
            try:
                inst = get_institution_by_id(institution_id)
                if inst:
                    institution_name = inst.get("name") or institution_name
            except Exception:
                pass
        base = (
            os.getenv("APP_BASE_URL", "https://app.mindguardai.me").rstrip("/")
            or "https://app.mindguardai.me"
        )
        invite_url = f"{base}/invite?token={token}"
        context = {
            "counsellor_name": name,
            "institution_name": institution_name,
            "invite_url": invite_url,
            "setup_url": invite_url,
            "support_email": os.getenv("DEMO_NOTIFY_EMAIL", "support@mindguard.ai"),
            "withdraw_url": f"{base}/privacy",
            "privacy_url": f"{base}/privacy",
            "contact_url": f"{base}/contact",
        }
        subject, body = counsellor_invitation_notification(context)
        email_sent, email_error = send_html_email(
            email,
            subject,
            body,
            related_type="counsellor_invitation",
            related_id=counsellor["id"],
            metadata={"action": "create", "invite": True},
        )
        write_audit(
            user["id"],
            "admin",
            "COUNSELLOR_INVITE_SENT",
            "user",
            counsellor["id"],
            payload={"email_sent": email_sent, "error": email_error or None},
            ip=_client_ip(request),
        )

    return {
        "ok": True,
        "counsellor": {
            "id": counsellor["id"],
            "name": counsellor["name"],
            "email": counsellor["email"],
            "status": counsellor["status"],
        },
        "email_sent": email_sent,
        "email_error": email_error or None,
    }


@app.post("/api/auth/invite/verify")
async def verify_invite(data: dict):
    """Verify counsellor invitation token is valid (no auth, no consumption)."""
    token = (data.get("token") or "").strip()
    if not token:
        raise HTTPException(400, "Token is required")
    from backend.services.crypto import hash_token

    token_hash = hash_token(token)
    user = get_user_by_invitation_token_hash(token_hash)
    if not user:
        raise HTTPException(400, "Invalid or expired invitation")
    expires_at = user.get("invitation_expires_at")
    if expires_at:
        try:
            exp = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) > exp:
                raise HTTPException(400, "Invitation has expired")
        except HTTPException:
            raise
        except Exception:
            pass
    if user.get("status") not in ("pending", "invited"):
        raise HTTPException(400, "Invitation already used")
    return {"ok": True, "email": user["email"], "name": user["name"]}


@app.post("/api/auth/invite/accept")
async def accept_invite(data: dict, request: Request):
    """Accept counsellor invitation: set password and activate account."""
    token = (data.get("token") or "").strip()
    password = data.get("password") or ""
    if not token or not password:
        raise HTTPException(400, "Token and password are required")
    if len(password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    from backend.services.crypto import hash_token

    token_hash = hash_token(token)
    user = get_user_by_invitation_token_hash(token_hash)
    if not user:
        raise HTTPException(400, "Invalid or expired invitation")
    expires_at = user.get("invitation_expires_at")
    if expires_at:
        try:
            exp = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) > exp:
                raise HTTPException(400, "Invitation has expired")
        except HTTPException:
            raise
        except Exception:
            pass
    if user.get("status") not in ("pending", "invited"):
        raise HTTPException(400, "Invitation already used")
    pw_hash = hash_password(password)
    update_user_password(user["id"], pw_hash)
    update_user_status(user["id"], "approved")
    mark_user_as_staff(user["id"])
    clear_user_invitation(user["id"])
    write_audit(
        user["id"],
        user["role_type"],
        "COUNSELLOR_INVITE_ACCEPTED",
        "user",
        user["id"],
        payload={"email": user["email"]},
        ip=_client_ip(request),
    )
    fresh = get_user_by_id(user["id"])
    token_value = create_access_token(fresh["id"], fresh["role_type"])
    return {
        "ok": True,
        "access_token": token_value,
        "user": {
            "id": fresh["id"],
            "email": fresh["email"],
            "name": fresh["name"],
            "role_type": fresh["role_type"],
            "user_category": _auth_user_category(fresh),
            "institution_id": fresh.get("institution_id"),
            "profile_completed": bool(fresh.get("profile_completed_at")),
        },
    }


@app.post("/api/admin/counsellors/{counsellor_id}/resend-invite")
async def resend_counsellor_invite(
    counsellor_id: str, request: Request, user: dict = Depends(require_auth)
):
    """Regenerate invitation token and resend email (admin only)."""
    if user["role_type"] != "admin":
        raise HTTPException(403, "Admin access required")
    counsellor = get_user_by_id(counsellor_id)
    if not counsellor or counsellor["role_type"] != "counsellor":
        raise HTTPException(404, "Counsellor not found")
    if counsellor.get("status") == "approved":
        raise HTTPException(400, "Counsellor already active; no invite needed")
    from backend.services.crypto import hash_token

    token = secrets.token_urlsafe(32)
    token_hash = hash_token(token)
    expires_at = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    set_user_invitation(counsellor_id, token_hash, expires_at)
    base = (
        os.getenv("APP_BASE_URL", "https://app.mindguardai.me").rstrip("/")
        or "https://app.mindguardai.me"
    )
    invite_url = f"{base}/invite?token={token}"
    institution_name = "MindGuard"
    context = {
        "counsellor_name": counsellor.get("name") or "there",
        "institution_name": institution_name,
        "invite_url": invite_url,
        "setup_url": invite_url,
        "support_email": os.getenv("DEMO_NOTIFY_EMAIL", "support@mindguard.ai"),
        "withdraw_url": f"{base}/privacy",
        "privacy_url": f"{base}/privacy",
        "contact_url": f"{base}/contact",
    }
    subject, body = counsellor_invitation_notification(context)
    email_sent, email_error = send_html_email(
        counsellor["email"],
        subject,
        body,
        related_type="counsellor_invitation",
        related_id=counsellor_id,
        metadata={"action": "resend"},
    )
    write_audit(
        user["id"],
        "admin",
        "COUNSELLOR_INVITE_RESENT",
        "user",
        counsellor_id,
        payload={"email_sent": email_sent},
        ip=_client_ip(request),
    )
    return {"ok": True, "email_sent": email_sent, "email_error": email_error or None}


@app.get("/api/admin/counsellors")
async def list_counsellors(user: dict = Depends(require_auth)):
    """List all counsellors (admin only)."""
    if user["role_type"] != "admin":
        raise HTTPException(403, "Admin access required")
    from backend.database import get_db

    conn = get_db()
    rows = conn.execute(
        "SELECT id, email, name, role_type, status, created_at FROM users "
        "WHERE role_type = 'counsellor' ORDER BY created_at DESC"
    ).fetchall()
    conn.close()

    result = []
    for row in rows:
        assignments = get_assignments_for_counsellor(row["id"])
        result.append(
            {
                "id": row["id"],
                "email": row["email"],
                "name": row["name"],
                "status": row["status"],
                "created_at": row["created_at"],
                "assigned_student_count": len(assignments),
            }
        )
    return result


@app.patch("/api/admin/counsellors/{counsellor_id}")
async def update_counsellor(
    counsellor_id: str, data: dict, request: Request, user: dict = Depends(require_auth)
):
    """Update a counsellor's status (admin only)."""
    if user["role_type"] != "admin":
        raise HTTPException(403, "Admin access required")
    counsellor = get_user_by_id(counsellor_id)
    if not counsellor or counsellor["role_type"] != "counsellor":
        raise HTTPException(404, "Counsellor not found")

    new_status = data.get("status")
    if new_status and new_status not in ("approved", "revoked", "suspended"):
        raise HTTPException(400, "Invalid status")

    old_status = counsellor.get("status")
    if new_status:
        update_user_role(counsellor_id, "counsellor")  # ensure role stays counsellor
        update_user_status(counsellor_id, new_status)
        if new_status in ("revoked", "suspended"):
            for a in get_assignments_for_counsellor(counsellor_id, active_only=True):
                unassign_student_from_counsellor(a["id"])
            try:
                pass
                # best-effort: blacklist any active tokens would require store, rely on status check
            except Exception:
                pass
        counsellor = get_user_by_id(counsellor_id)

        action = (
            "COUNSELLOR_DEACTIVATED"
            if new_status in ("revoked", "suspended")
            else "COUNSELLOR_ACTIVATED"
        )
        write_audit(
            user["id"],
            "admin",
            action,
            "user",
            counsellor_id,
            payload={"previous_status": old_status, "new_status": new_status},
            ip=_client_ip(request),
        )

    return {"ok": True, "counsellor": counsellor}


@app.post("/api/admin/assignments")
async def create_assignment(
    data: dict, request: Request, user: dict = Depends(require_auth)
):
    """Assign a student to a counsellor (admin only)."""
    scoped_institution = _require_institution_admin(user, data.get("institution_id"))
    counsellor_id = data.get("counsellor_id")
    student_id = data.get("student_id")
    requested_institution_id = data.get("institution_id")

    if not counsellor_id or not student_id:
        raise HTTPException(400, "Counsellor ID and student ID are required")

    counsellor = get_user_by_id(counsellor_id)
    student = get_user_by_id(student_id)

    if not counsellor or counsellor["role_type"] != "counsellor":
        raise HTTPException(404, "Counsellor not found")
    if not student or student["role_type"] != "student":
        raise HTTPException(404, "Student not found")

    # The admin UI selects a counsellor and a roster student, not a raw tenant
    # ID. Derive the tenant from those server-owned records; request input may
    # only narrow the authenticated admin's scope.
    roster_student = get_student_by_user_id(student_id)
    student_institution_id = student.get("institution_id") or (
        roster_student.get("institution_id") if roster_student else None
    )
    institution_id = (
        scoped_institution
        or requested_institution_id
        or counsellor.get("institution_id")
        or student_institution_id
    )
    if not institution_id:
        raise HTTPException(
            400,
            "The counsellor or student must be linked to an institution before assignment",
        )
    if requested_institution_id and requested_institution_id != institution_id:
        raise HTTPException(
            403, "Requested institution does not match the assignment context"
        )
    if (
        counsellor.get("institution_id") != institution_id
        or student_institution_id != institution_id
    ):
        raise HTTPException(
            403, "Counsellor, student, and assignment institution must match"
        )

    assignment = assign_student_to_counsellor(
        counsellor_id, student_id, institution_id, user["id"]
    )

    write_audit(
        user["id"],
        "admin",
        "STUDENT_ASSIGNED",
        "user",
        student_id,
        payload={"counsellor_id": counsellor_id, "institution_id": institution_id},
        ip=_client_ip(request),
    )

    return {"ok": True, "assignment": assignment}


@app.delete("/api/admin/assignments/{assignment_id}")
async def remove_assignment(
    assignment_id: str, request: Request, user: dict = Depends(require_auth)
):
    """Remove a student-counsellor assignment (admin only)."""
    assignment = get_assignment(assignment_id)
    if not assignment:
        raise HTTPException(404, "Assignment not found")
    _require_institution_admin(user, assignment.get("institution_id"))

    ok = unassign_student_from_counsellor(assignment_id)
    if not ok:
        raise HTTPException(404, "Assignment not found")

    write_audit(
        user["id"],
        "admin",
        "STUDENT_UNASSIGNED",
        "user",
        assignment["student_id"],
        payload={"counsellor_id": assignment["counsellor_id"]},
        ip=_client_ip(request),
    )

    return {"ok": True}


@app.get("/api/admin/assignments")
async def list_assignments(
    counsellor_id: str | None = None,
    student_id: str | None = None,
    user: dict = Depends(require_auth),
):
    """List assignments (admin only)."""
    scoped = _require_institution_scope(user)

    if scoped:
        from backend.database import get_db

        conn = get_db()
        rows = conn.execute(
            "SELECT csa.*, u_c.name as counsellor_name, u_c.email as counsellor_email, "
            "u_s.name as student_name, u_s.email as student_email, i.name as institution_name "
            "FROM counsellor_student_assignments csa "
            "JOIN users u_c ON csa.counsellor_id = u_c.id JOIN users u_s ON csa.student_id = u_s.id "
            "LEFT JOIN institutions i ON csa.institution_id = i.id "
            "WHERE csa.institution_id = ? AND csa.active = 1 ORDER BY csa.assigned_at DESC",
            (scoped,),
        ).fetchall()
        conn.close()
        return [dict(row) for row in rows]
    if counsellor_id:
        assignments = get_assignments_for_counsellor(counsellor_id)
    elif student_id:
        assignments = get_assignments_for_student(student_id)
    else:
        from backend.database import get_db

        conn = get_db()
        rows = conn.execute(
            "SELECT csa.*, u_c.name as counsellor_name, u_c.email as counsellor_email, "
            "u_s.name as student_name, u_s.email as student_email, "
            "i.name as institution_name "
            "FROM counsellor_student_assignments csa "
            "JOIN users u_c ON csa.counsellor_id = u_c.id "
            "JOIN users u_s ON csa.student_id = u_s.id "
            "LEFT JOIN institutions i ON csa.institution_id = i.id "
            "WHERE csa.active = 1 ORDER BY csa.assigned_at DESC"
        ).fetchall()
        conn.close()
        assignments = [dict(r) for r in rows]

    return assignments


# ── Counsellor routes ─────────────────────────────────────────────────


@app.get("/api/counsellor/students")
async def get_counsellor_students(user: dict = Depends(require_auth)):
    _require_counsellor(user)
    is_admin = user["role_type"] == "admin"
    return get_students(counsellor_id=None if is_admin else user["id"])


@app.post("/api/counsellor/students/approve")
async def approve_counsellor_student(
    data: dict, request: Request, user: dict = Depends(require_auth)
):
    _require_counsellor(user)
    sid = data.get("id")
    if not sid:
        raise HTTPException(400, "Student ID required")
    student = get_user_by_id(sid)
    if not student:
        raise HTTPException(404, "Student not found")
    _require_counsellor_student_access(user, sid, require_consent=False)
    # Prevent duplicate emails: only send if status actually changes
    if student.get("status") == "approved":
        return {
            "ok": True,
            "status": "approved",
            "email_sent": False,
            "email_error": None,
            "note": "Student already approved",
        }
    ok = update_student_status(sid, "approved")
    if not ok:
        raise HTTPException(404, "Student not found")
    _safe_notify(
        sid,
        "Account Approved",
        "Your account has been approved by a counsellor.",
        "approval",
    )
    email_sent, email_error = False, ""
    if student.get("email"):
        context = {
            "student_name": student.get("name", ""),
            "institution_name": "MindGuard",
            "login_url": os.getenv("APP_BASE_URL", "https://app.mindguardai.me"),
            "support_email": os.getenv("DEMO_NOTIFY_EMAIL", "support@mindguard.ai"),
        }
        subject, body = student_status_notification(context, approved=True)
        email_sent, email_error = send_html_email(
            student["email"],
            subject,
            body,
            related_type="student_status",
            related_id=sid,
            metadata={"status": "approved"},
        )
    write_audit(
        user["id"],
        user["role_type"],
        "STUDENT_APPROVED",
        "user",
        sid,
        payload={"status": "approved", "email_sent": email_sent},
        ip=_client_ip(request),
    )
    return {
        "ok": True,
        "status": "approved",
        "email_sent": email_sent,
        "email_error": email_error or None,
    }


@app.post("/api/counsellor/students/revoke")
async def revoke_counsellor_student(
    data: dict, request: Request, user: dict = Depends(require_auth)
):
    _require_counsellor(user)
    sid = data.get("id")
    if not sid:
        raise HTTPException(400, "Student ID required")
    student = get_user_by_id(sid)
    if not student:
        raise HTTPException(404, "Student not found")
    _require_counsellor_student_access(user, sid, require_consent=False)
    # Prevent duplicate emails: only send if status actually changes
    if student.get("status") == "revoked":
        return {
            "ok": True,
            "status": "revoked",
            "email_sent": False,
            "email_error": None,
            "note": "Student already revoked",
        }
    ok = update_student_status(sid, "revoked")
    if not ok:
        raise HTTPException(404, "Student not found")
    _safe_notify(
        sid, "Account Revoked", "Your account access has been revoked.", "general"
    )
    email_sent, email_error = False, ""
    if student.get("email"):
        context = {
            "student_name": student.get("name", ""),
            "institution_name": "MindGuard",
            "support_email": os.getenv("DEMO_NOTIFY_EMAIL", "support@mindguard.ai"),
        }
        subject, body = student_status_notification(context, approved=False)
        email_sent, email_error = send_html_email(
            student["email"],
            subject,
            body,
            related_type="student_status",
            related_id=sid,
            metadata={"status": "revoked"},
        )
    write_audit(
        user["id"],
        user["role_type"],
        "STUDENT_REVOKED",
        "user",
        sid,
        payload={"status": "revoked", "email_sent": email_sent},
        ip=_client_ip(request),
    )
    return {
        "ok": True,
        "status": "revoked",
        "email_sent": email_sent,
        "email_error": email_error or None,
    }


@app.get("/api/counsellor/students/{student_id}")
async def get_student_detail(student_id: str, user: dict = Depends(require_auth)):
    student = get_user_by_id(student_id)
    if not student or student["role_type"] != "student":
        raise HTTPException(404, "Student not found")
    _require_counsellor_student_access(user, student_id, require_consent=False)
    _require_counsellor_student_access(user, student_id)
    from backend.database import get_analyses

    analyses = get_analyses(student_id, limit=50)
    rolling = get_rolling_risk(student_id)
    if analyses:
        latest_prob = analyses[0]["prob"]
        latest_label, latest_color, _ = risk_label(latest_prob)
    elif rolling:
        latest_prob = rolling["score"]
        latest_label, latest_color, _ = risk_label(latest_prob)
    else:
        latest_prob = 0.0
        latest_label = "No data"
        latest_color = "#6b7280"
    return {
        "id": student["id"],
        "email": student["email"],
        "name": student["name"],
        "status": student["status"],
        "created_at": student["created_at"],
        "risk_summary": {
            "latest_prob": latest_prob,
            "latest_label": latest_label,
            "latest_color": latest_color,
            "total_analyses": len(analyses),
            "high_risk_count": sum(1 for a in analyses if a["prob"] >= 0.75),
        },
        "rolling_risk": rolling,
        "analyses": analyses,
        "consent_status": consent_status_for_ui(student_id),
    }


# ── Referrals routes ─────────────────────────────────────────────────


@app.get("/api/counsellor/referrals")
async def get_counsellor_referrals(
    institution_id: str | None = None, user: dict = Depends(require_auth)
):
    _require_counsellor(user)
    scoped = _require_institution_scope(user, institution_id)
    if user["role_type"] == "admin":
        return get_referrals(institution_id=scoped)
    if user["role_type"] == "school_admin":
        return get_referrals(institution_id=scoped)
    return get_referrals(user["id"], institution_id=scoped)


@app.post("/api/counsellor/referrals")
async def create_counsellor_referral(
    data: dict, request: Request, user: dict = Depends(require_auth)
):
    if user["role_type"] not in ("counsellor", "school_admin", "admin"):
        raise HTTPException(403, "Counsellor or admin access required")
    student_id = data.get("student_id")
    urgency = data.get("urgency", "medium")
    notes = data.get("notes", "")
    destination = (data.get("destination") or "").strip() or None
    follow_up_at = (data.get("follow_up_at") or "").strip() or None
    if not student_id:
        raise HTTPException(400, "Student ID required")
    if urgency not in ("low", "medium", "high", "crisis"):
        raise HTTPException(400, "Invalid urgency level")
    student = get_user_by_id(student_id)
    if not student or student["role_type"] != "student":
        raise HTTPException(400, "Invalid student ID")
    scoped = _require_institution_scope(user)
    if user["role_type"] == "school_admin":
        if student.get("institution_id") != scoped:
            raise HTTPException(403, "Student is outside your institution")
    else:
        _require_counsellor_student_access(user, student_id)
    referral = create_referral(
        user["id"], student_id, urgency, notes, destination, follow_up_at
    )
    if urgency == "crisis":
        create_alert(student_id, user["id"], 1.0, 0.0, "referral")
    _safe_notify(
        student_id,
        "Referral Created",
        f"A counsellor has created a {urgency}-urgency referral for you.",
        "referral",
    )
    write_audit(
        actor_id=user["id"],
        actor_role=user["role_type"],
        action="referral.create",
        target_type="referral",
        target_id=referral["id"],
        payload={
            "urgency": urgency,
            "student_id": student_id,
            "destination": destination,
            "follow_up_at": follow_up_at,
        },
        ip=request.client.host if request.client else None,
    )
    return referral


@app.patch("/api/counsellor/referrals/{referral_id}")
async def update_counsellor_referral(
    referral_id: str, data: dict, request: Request, user: dict = Depends(require_auth)
):
    if user["role_type"] not in ("counsellor", "school_admin", "admin"):
        raise HTTPException(403, "Counsellor or admin access required")
    status = data.get("status")
    notes = data.get("notes")
    if status and status not in (
        "open",
        "accepted",
        "in_progress",
        "completed",
        "declined",
        "cancelled",
    ):
        raise HTTPException(400, "Invalid status")
    existing = get_referral(referral_id)
    if not existing:
        raise HTTPException(404, "Referral not found")
    scoped = _require_institution_scope(user)
    if scoped and existing.get(
        "student_institution_id", existing.get("institution_id")
    ) not in (None, scoped):
        raise HTTPException(403, "Referral is outside your institution")
    if user["role_type"] == "counsellor" and existing["counsellor_id"] != user["id"]:
        raise HTTPException(403, "You do not own this referral")
    result = update_referral(
        referral_id,
        status=status,
        notes=notes,
        outcome=data.get("outcome"),
        follow_up_at=data.get("follow_up_at"),
        actor_id=user["id"],
        actor_role=user["role_type"],
        reason=data.get("reason"),
    )
    if not result:
        raise HTTPException(404, "Referral not found")
    if status and status != existing.get("status"):
        _safe_notify(
            existing["student_id"],
            "Referral Update",
            f"Your referral status has been updated to '{status}'.",
            "referral",
        )
    write_audit(
        actor_id=user["id"],
        actor_role=user["role_type"],
        action="referral.update",
        target_type="referral",
        target_id=referral_id,
        payload={"status": status, "notes": notes},
        ip=request.client.host if request.client else None,
    )
    return result


# ── Communications routes ────────────────────────────────────────────


@app.get("/api/counsellor/conversations")
async def get_counsellor_conversations(user: dict = Depends(require_auth)):
    _require_counsellor(user)
    conversations = get_conversations(user["id"])
    if user["role_type"] == "admin":
        return conversations
    return [c for c in conversations if _communication_allowed(user, c["other_id"])]


@app.get("/api/counsellor/conversations/{other_id}")
async def get_counsellor_conversation(
    other_id: str, user: dict = Depends(require_auth)
):
    _require_counsellor(user)
    _require_user_communication_access(user, other_id)
    mark_all_read(user["id"], other_id)
    return get_conversation(user["id"], other_id)


@app.post("/api/counsellor/messages")
async def send_counsellor_message(
    data: dict, request: Request, user: dict = Depends(require_auth)
):
    _require_counsellor(user)
    receiver_id = data.get("receiver_id")
    message = data.get("message", "").strip()
    if not receiver_id:
        raise HTTPException(400, "Receiver ID required")
    if not message:
        raise HTTPException(400, "Message cannot be empty")
    _require_user_communication_access(user, receiver_id)
    msg = send_message(user["id"], receiver_id, message)
    if should_notify(receiver_id, "message"):
        _safe_notify(
            receiver_id, "New Message", f"New message from {user['name']}", "message"
        )
    write_audit(
        user["id"],
        user["role_type"],
        "MESSAGE_SENT",
        "communication",
        msg["id"],
        payload={"receiver_id": receiver_id},
        ip=_client_ip(request),
    )
    return msg


# ── Dashboard ────────────────────────────────────────────────────────

# ── Appointment scheduling routes ────────────────────────────────────


def _appointment_actor_can_access(user: dict, appointment: dict) -> None:
    """Require an appointment participant or an administrator."""
    if user["role_type"] == "admin":
        return
    if user["id"] == appointment["student_id"]:
        return
    if user["id"] == appointment["counsellor_id"]:
        _require_counsellor_student_access(
            user, appointment["student_id"], require_consent=False
        )
        return
    raise HTTPException(403, "You do not have access to this appointment")


@app.get("/api/appointments")
async def get_my_appointments(
    status: str | None = None, user: dict = Depends(require_auth)
):
    if status and status not in {
        "REQUESTED",
        "CONFIRMED",
        "DECLINED",
        "CANCELLED",
        "COMPLETED",
        "NO_SHOW",
    }:
        raise HTTPException(400, "Invalid appointment status")
    if user["role_type"] == "admin":
        return list_appointments(None, status=status)
    return list_appointments(user["id"], status=status)


@app.post("/api/appointments", status_code=201)
async def create_new_appointment(
    data: dict, request: Request, user: dict = Depends(require_auth)
):
    if user["role_type"] not in ("counsellor", "school_admin", "admin"):
        raise HTTPException(403, "Only counsellors can schedule appointments")
    student_id = data.get("student_id")
    title = (data.get("title") or "Wellbeing check-in").strip()
    start_at = data.get("start_at")
    end_at = data.get("end_at")
    if not student_id or not start_at or not end_at:
        raise HTTPException(400, "student_id, start_at, and end_at are required")
    if not title or len(title) > 160:
        raise HTTPException(400, "Title must be between 1 and 160 characters")
    try:
        start = datetime.fromisoformat(start_at.replace("Z", "+00:00"))
        end = datetime.fromisoformat(end_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(400, "Invalid appointment date/time") from exc
    if start.tzinfo is None or end.tzinfo is None or end <= start:
        raise HTTPException(
            400, "Appointment end must be after its start and include a timezone"
        )
    if start <= datetime.now(timezone.utc):
        raise HTTPException(400, "Appointments must be scheduled in the future")
    student = get_user_by_id(student_id)
    if not student or student.get("role_type") != "student":
        raise HTTPException(404, "Student not found")
    counsellor_id = (
        user["id"] if user["role_type"] != "admin" else data.get("counsellor_id")
    )
    if not counsellor_id:
        raise HTTPException(400, "counsellor_id is required for admin scheduling")
    counsellor = get_user_by_id(counsellor_id)
    if not counsellor or counsellor.get("role_type") not in (
        "counsellor",
        "school_admin",
    ):
        raise HTTPException(404, "Counsellor not found")
    if user["role_type"] != "admin":
        _require_counsellor_student_access(user, student_id)
    else:
        _require_counsellor_student_access(
            counsellor, student_id, require_consent=False
        )
    try:
        appointment = create_appointment(
            student_id=student_id,
            counsellor_id=counsellor_id,
            created_by=user["id"],
            title=title,
            start_at=start.isoformat(),
            end_at=end.isoformat(),
            timezone_name=(data.get("timezone") or "UTC").strip(),
            mode=(data.get("mode") or "video").strip(),
            location=(data.get("location") or "").strip() or None,
            notes=(data.get("notes") or "").strip() or None,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    _safe_notify(
        student_id,
        "Appointment requested",
        f"{counsellor.get('name', 'Your counsellor')} proposed a wellbeing appointment.",
        "appointment",
    )
    write_audit(
        user["id"],
        user["role_type"],
        "APPOINTMENT_CREATED",
        "appointment",
        appointment["id"],
        payload={"student_id": student_id, "start_at": appointment["start_at"]},
        ip=_client_ip(request),
    )
    return appointment


@app.patch("/api/appointments/{appointment_id}/status")
async def change_appointment_status(
    appointment_id: str,
    data: dict,
    request: Request,
    user: dict = Depends(require_auth),
):
    appointment = get_appointment(appointment_id)
    if not appointment:
        raise HTTPException(404, "Appointment not found")
    _appointment_actor_can_access(user, appointment)
    status = data.get("status")
    current = appointment["status"]
    allowed = {
        "REQUESTED": {"CONFIRMED", "DECLINED", "CANCELLED"},
        "CONFIRMED": {"CANCELLED", "COMPLETED", "NO_SHOW"},
        "DECLINED": set(),
        "CANCELLED": set(),
        "COMPLETED": set(),
        "NO_SHOW": set(),
    }
    if status not in allowed.get(current, set()):
        raise HTTPException(409, f"Cannot change {current} appointment to {status}")
    if user["role_type"] != "admin":
        if user["id"] == appointment["student_id"] and status not in {
            "CONFIRMED",
            "DECLINED",
            "CANCELLED",
        }:
            raise HTTPException(
                403, "Students may only confirm, decline, or cancel appointments"
            )
        if user["id"] == appointment["counsellor_id"] and status not in {
            "CONFIRMED",
            "DECLINED",
            "CANCELLED",
            "COMPLETED",
            "NO_SHOW",
        }:
            raise HTTPException(
                403, "Counsellors may not use this appointment transition"
            )
    updated = update_appointment_status(
        appointment_id, status, (data.get("reason") or "").strip() or None
    )
    if not updated:
        raise HTTPException(404, "Appointment not found")
    recipient = (
        updated["student_id"]
        if user["id"] == updated["counsellor_id"]
        else updated["counsellor_id"]
    )
    _safe_notify(
        recipient,
        "Appointment updated",
        f"Appointment status: {status.lower().replace('_', ' ')}.",
        "appointment",
    )
    write_audit(
        user["id"],
        user["role_type"],
        "APPOINTMENT_STATUS_CHANGED",
        "appointment",
        appointment_id,
        payload={"from": current, "to": status, "reason": data.get("reason")},
        ip=_client_ip(request),
    )
    return updated


@app.get("/api/appointments/{appointment_id}")
async def get_one_appointment(appointment_id: str, user: dict = Depends(require_auth)):
    appointment = get_appointment(appointment_id)
    if not appointment:
        raise HTTPException(404, "Appointment not found")
    _appointment_actor_can_access(user, appointment)
    return appointment


@app.get("/api/counsellor/dashboard")
async def counsellor_dashboard(user: dict = Depends(require_auth)):
    if user["role_type"] not in ("counsellor", "admin"):
        raise HTTPException(403, "Counsellor or admin access required")
    is_admin = user["role_type"] == "admin"
    return get_counsellor_dashboard(user["id"], is_admin=is_admin)


# ── Notifications routes ─────────────────────────────────────────────


@app.get("/api/notifications")
async def get_user_notifications(user: dict = Depends(require_auth)):
    return {
        "notifications": get_notifications(user["id"]),
        **get_notification_summary(user["id"]),
    }


@app.post("/api/notifications/read")
async def mark_user_notification_read(data: dict, user: dict = Depends(require_auth)):
    nid = data.get("id")
    if nid:
        mark_notification_read(nid, user["id"])
    return {"ok": True}


# ── Admin routes ─────────────────────────────────────────────────────


@app.get("/api/admin/users")
async def admin_list_users(user: dict = Depends(require_auth)):
    if user["role_type"] != "admin":
        raise HTTPException(403, "Admin access required")
    return get_all_users()


@app.delete("/api/admin/users/{user_id}")
async def admin_permanently_delete_user(
    user_id: str,
    data: dict,
    request: Request,
    user: dict = Depends(require_auth),
):
    """Permanently remove a user and their owned records.

    The exact email is required as a deliberate destructive-action
    confirmation. Global admins cannot delete themselves or the final global
    administrator; audit history is retained for accountability.
    """
    if user["role_type"] != "admin":
        raise HTTPException(403, "Admin access required")
    if user_id == user["id"]:
        raise HTTPException(400, "You cannot permanently delete your own account")
    target = get_user_by_id(user_id)
    if not target:
        raise HTTPException(404, "User not found")
    if (data.get("confirmation") or "").strip().lower() != str(
        target.get("email") or ""
    ).strip().lower():
        raise HTTPException(
            400, "Type the user's exact email address to confirm permanent deletion"
        )
    if target.get("role_type") == "admin":
        remaining_admins = [
            u
            for u in get_all_users()
            if u.get("role_type") == "admin" and u.get("id") != user_id
        ]
        if not remaining_admins:
            raise HTTPException(409, "The final global administrator cannot be deleted")
    write_audit(
        user["id"],
        user["role_type"],
        "USER_PERMANENTLY_DELETED",
        "user",
        user_id,
        payload={"email": target.get("email"), "role_type": target.get("role_type")},
        ip=request.client.host if request.client else None,
    )
    deleted = permanently_delete_user(user_id)
    return {"ok": True, "deleted_user_id": deleted["id"] if deleted else user_id}


@app.get("/api/admin/individuals")
async def admin_list_individuals(user: dict = Depends(require_auth)):
    """List public consumer accounts separately from institution students."""
    if user["role_type"] != "admin":
        raise HTTPException(403, "Admin access required")
    individuals = get_individual_users(limit=1000)
    return {"individuals": individuals, "total": len(individuals)}


@app.post("/api/admin/broadcast")
async def admin_broadcast(
    data: dict, request: Request, user: dict = Depends(require_auth)
):
    if user["role_type"] != "admin":
        raise HTTPException(403, "Admin access required")
    title = (data.get("title") or "").strip()
    message = (data.get("message") or "").strip()
    target_role = data.get("target_role")  # None = all, or "student"/"counsellor"
    if not title or not message:
        raise HTTPException(400, "Title and message are required")
    users = get_all_users()
    if target_role:
        users = [u for u in users if u["role_type"] == target_role]
    sent = 0
    for u in users:
        if u["id"] != user["id"]:  # don't notify yourself
            _safe_notify(u["id"], title, message, "broadcast")
            sent += 1
    write_audit(
        actor_id=user["id"],
        actor_role=user["role_type"],
        action="broadcast.send",
        target_type="notification",
        payload={"title": title, "target_role": target_role, "recipients": sent},
        ip=request.client.host if request.client else None,
    )
    logger.info("Broadcast: admin=%s title=%r sent_to=%d", user["id"], title, sent)
    return {"ok": True, "sent": sent}


# ── User directory ──────────────────────────────────────────────────


@app.get("/api/users/directory")
async def get_user_directory(
    role: str | None = None, user: dict = Depends(require_auth)
):
    """List users by role for starting conversations.

    Any authenticated user may look up peers by name/id, but emails are only
    exposed to admins so the directory cannot be used to harvest the roster.
    """
    users = get_all_users()
    if role:
        users = [u for u in users if u["role_type"] == role]
    if user["role_type"] == "admin":
        return users
    return [
        {
            k: v
            for k, v in u.items()
            if k not in ("email", "password_hash", "dob", "parent_email")
        }
        for u in users
    ]


# ── Resources routes ─────────────────────────────────────────────────


@app.get("/api/resources")
async def get_resources(user: dict = Depends(require_auth)):
    return RESOURCES


@app.get("/api/resources/states")
async def get_state_resources(user: dict = Depends(require_auth)):
    return US_STATE_RESOURCES


@app.get("/api/resources/team")
async def get_team():
    return TEAM_MEMBERS


# ═════════════════════════════════════════════════════════════════════
# API v1 routes
# ═════════════════════════════════════════════════════════════════════


def _require_counsellor(user: dict) -> None:
    """Raise 403 unless the user holds any staff-level permission."""
    require_any_permission(
        user,
        {
            PERM_ANALYSIS_RUN,
            PERM_CONSENT_MANAGE,
            PERM_ROSTER_UPLOAD,
            PERM_STUDENTS_VIEW,
            PERM_DEMO_MANAGE,
        },
    )


def _require_institution_scope(
    user: dict, institution_id: str | None = None
) -> str | None:
    """Resolve institution scope from the authenticated principal.

    Platform admins may explicitly select a valid institution. All other
    staff derive scope from their account; a request-supplied institution ID
    can only narrow that scope, never broaden it.
    """
    if user.get("role_type") == "admin":
        if institution_id:
            institution = get_institution_by_id(institution_id)
            if not institution:
                raise HTTPException(404, "Institution not found")
            return institution_id
        return None
    if user.get("role_type") not in ("school_admin", "counsellor"):
        raise HTTPException(403, "Institution staff access required")
    account_institution = user.get("institution_id")
    if not account_institution:
        raise HTTPException(403, "Your account is not linked to an institution")
    if institution_id and institution_id != account_institution:
        raise HTTPException(403, "You cannot access another institution")
    institution = get_institution_by_id(account_institution)
    if not institution or (institution.get("status") or "ACTIVE") != "ACTIVE":
        raise HTTPException(403, "This institution is not active")
    return account_institution


def _require_institution_admin(
    user: dict, institution_id: str | None = None
) -> str | None:
    if user.get("role_type") not in ("admin", "school_admin"):
        raise HTTPException(403, "Institution administrator access required")
    return _require_institution_scope(user, institution_id)


def _require_counsellor_student_access(
    user: dict, student_id: str, *, require_consent: bool = True
) -> None:
    """Centralized counsellor→student authorization; deny on missing scope."""
    if user.get("role_type") == "admin":
        return
    _require_counsellor(user)
    from backend.database import has_active_assignment, get_user_by_id

    if not has_active_assignment(user["id"], student_id):
        raise HTTPException(403, "Student not assigned to you")
    counsellor_inst = user.get("institution_id")
    student = get_user_by_id(student_id)
    student_inst = student.get("institution_id") if student else None
    if (counsellor_inst or student_inst) and (
        not counsellor_inst or not student_inst or counsellor_inst != student_inst
    ):
        raise HTTPException(403, "Student not in your institution")
    if counsellor_inst and not has_active_assignment(
        user["id"], student_id, counsellor_inst
    ):
        raise HTTPException(403, "Assignment is not in your institution")
    if require_consent and not has_consent_relationship(student_id, user["id"]):
        raise HTTPException(403, "No active consent for this student")


def _require_user_communication_access(user: dict, other_id: str) -> dict:
    """Authorize direct communication without trusting a caller-supplied ID."""
    other = get_user_by_id(other_id)
    if not other:
        raise HTTPException(404, "Recipient not found")
    if other_id == user["id"]:
        raise HTTPException(400, "Cannot communicate with yourself")
    if user.get("role_type") == "admin" or other.get("role_type") == "admin":
        return other
    user_role = user.get("role_type")
    other_role = other.get("role_type")
    if user_role in ("counsellor", "school_admin") and other_role == "student":
        _require_counsellor_student_access(user, other_id)
        return other
    if other_role in ("counsellor", "school_admin") and user_role == "student":
        _require_counsellor_student_access(other, user["id"])
        return other
    user_is_parent = user_role == "parent" or user.get("user_category") == "parent"
    other_is_parent = other_role == "parent" or other.get("user_category") == "parent"
    if (
        user_is_parent
        and other_role == "student"
        and other.get("user_category") != "parent"
    ):
        if other.get("parent_guardian_id") != user["id"]:
            raise HTTPException(403, "Users are not permitted to communicate")
        return other
    if (
        other_is_parent
        and user_role == "student"
        and user.get("user_category") != "parent"
    ):
        if user.get("parent_guardian_id") != other["id"]:
            raise HTTPException(403, "Users are not permitted to communicate")
        return other
    raise HTTPException(403, "Users are not permitted to communicate")


def _communication_allowed(user: dict, other_id: str) -> bool:
    try:
        _require_user_communication_access(user, other_id)
        return True
    except HTTPException:
        return False


def _client_ip(request: Request) -> str:
    if os.getenv("TRUSTED_PROXY", "").strip().lower() in {"1", "true", "yes"}:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",", 1)[0].strip() or "unknown"
    return request.client.host if request.client else "unknown"


def _client_user_agent(request: Request) -> str | None:
    return request.headers.get("user-agent") or None


# ── Consent management ────────────────────────────────────────────────


@app.post("/api/v1/students/{student_id}/consent", status_code=201)
async def v1_create_and_dispatch_consent(
    student_id: str,
    data: dict,
    request: Request,
    user: dict = Depends(require_auth),
):
    _require_counsellor(user)
    student = get_user_by_id(student_id)
    if not student or student["role_type"] != "student":
        raise HTTPException(404, "Student not found")
    _require_counsellor_student_access(user, student_id, require_consent=False)

    recipient_email = data.get("recipient_email", "").strip()
    if not recipient_email:
        raise HTTPException(400, "recipient_email is required")

    recipient_role = data.get("recipient_role", "student")
    if recipient_role not in ("student", "parent"):
        raise HTTPException(400, "recipient_role must be 'student' or 'parent'")
    if (
        recipient_role == "student"
        and recipient_email.lower() != str(student.get("email") or "").lower()
    ):
        raise HTTPException(
            403, "Student consent must be addressed to the student account"
        )
    if recipient_role == "parent":
        parent_email = str(student.get("parent_email") or "").strip().lower()
        parent = get_user_by_email(recipient_email)
        if not parent_email or recipient_email.lower() != parent_email:
            raise HTTPException(
                403, "Parent consent must be addressed to the registered guardian"
            )
        if student.get("parent_guardian_id") and student.get(
            "parent_guardian_id"
        ) != parent.get("id"):
            raise HTTPException(
                403, "Parent consent recipient is not the linked guardian"
            )

    platforms = data.get("platforms", [])
    mode = data.get("mode", "ON_DEMAND")
    if mode not in ("ON_DEMAND", "CONTINUOUS"):
        raise HTTPException(400, "mode must be 'ON_DEMAND' or 'CONTINUOUS'")

    try:
        consent = create_consent(
            student_id=student_id,
            counsellor_id=user["id"],
            recipient_email=recipient_email,
            recipient_role=recipient_role,
            platforms=platforms,
            mode=mode,
        )
        consent = dispatch_consent(
            consent["id"], actor_id=user["id"], ip=_client_ip(request)
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        logger.error("create_consent error: %s", exc)
        raise HTTPException(500, "Failed to create consent")

    write_audit(
        user["id"],
        user["role_type"],
        "CONSENT_CREATED",
        "consent",
        consent["id"],
        payload={"student_id": student_id, "recipient_email": recipient_email},
        ip=_client_ip(request),
    )
    _safe_notify(
        student_id,
        "Consent Request Sent",
        "A consent request has been dispatched to your guardian/student.",
        "consent",
    )
    return consent


@app.get("/api/v1/consents")
async def v1_list_consents(
    status: str | None = None,
    search: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 50,
    offset: int = 0,
    user: dict = Depends(require_auth),
):
    _require_counsellor(user)
    rows, total = query_consents(
        user["id"],
        status=status,
        search=search,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    return {"consents": rows, "total": total}


@app.get("/api/v1/consents/export")
async def v1_export_consents(
    status: str | None = None,
    search: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    user: dict = Depends(require_auth),
):
    _require_counsellor(user)
    rows, _ = query_consents(
        user["id"],
        status=status,
        search=search,
        date_from=date_from,
        date_to=date_to,
        limit=100000,
    )
    csv = consents_to_csv(rows)
    filename = "mindguard-consents.csv"
    return Response(
        content=csv,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/v1/consents/{consent_id}")
async def v1_get_consent(
    consent_id: str,
    user: dict = Depends(require_auth),
):
    _require_counsellor(user)
    consent = get_consent_with_student(consent_id)
    if not consent:
        raise HTTPException(404, "Consent not found")
    if consent["counsellor_id"] != user["id"] and user["role_type"] != "admin":
        raise HTTPException(403, "Access denied")
    if user["role_type"] != "admin":
        _require_counsellor_student_access(
            user, consent["student_id"], require_consent=False
        )
    events = get_consent_events(consent_id)
    audit_log = get_audit_log_for_target("consent", consent_id)
    return {"consent": consent, "events": events, "audit_log": audit_log}


@app.post("/api/v1/consents/{consent_id}/dispatch")
async def v1_dispatch_consent(
    consent_id: str,
    request: Request,
    user: dict = Depends(require_auth),
):
    _require_counsellor(user)
    consent = get_consent_by_id(consent_id)
    if not consent:
        raise HTTPException(404, "Consent not found")
    if consent["counsellor_id"] != user["id"] and user["role_type"] != "admin":
        raise HTTPException(403, "Access denied")
    if user["role_type"] != "admin":
        _require_counsellor_student_access(
            user, consent["student_id"], require_consent=False
        )
    try:
        updated = dispatch_consent(
            consent_id, actor_id=user["id"], ip=_client_ip(request)
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        logger.error("dispatch_consent error: %s", exc)
        raise HTTPException(500, "Failed to dispatch consent")
    return updated


@app.post("/api/v1/consents/{consent_id}/remind")
async def v1_remind_consent(
    consent_id: str,
    request: Request,
    user: dict = Depends(require_auth),
):
    _require_counsellor(user)
    consent = get_consent_by_id(consent_id)
    if not consent:
        raise HTTPException(404, "Consent not found")
    if consent["counsellor_id"] != user["id"] and user["role_type"] != "admin":
        raise HTTPException(403, "Access denied")
    if user["role_type"] != "admin":
        _require_counsellor_student_access(
            user, consent["student_id"], require_consent=False
        )
    if consent["status"] not in ("PENDING", "VIEWED"):
        raise HTTPException(
            400, f"Cannot send reminder for consent in status {consent['status']}"
        )
    try:
        updated = remind_consent(
            consent_id, actor_id=user["id"], ip=_client_ip(request)
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        logger.error("remind_consent error: %s", exc)
        raise HTTPException(500, "Failed to send reminder")
    return {
        "ok": True,
        "message": "Reminder sent"
        if updated.get("email_sent")
        else "Reminder recorded but email was not sent",
        "email_sent": updated.get("email_sent", False),
        "email_error": updated.get("email_error", ""),
        "consent_url": updated.get("consent_url", ""),
    }


@app.post(
    "/api/v1/consents/{consent_id}/decision",
    responses={
        200: {"description": "Decision recorded on behalf of the recipient"},
        400: {"description": "Invalid decision value or consent state"},
        403: {"description": "Access denied"},
        404: {"description": "Consent not found"},
    },
)
async def v1_record_consent_decision(
    consent_id: str,
    data: dict,
    request: Request,
    user: dict = Depends(require_auth),
):
    """Record the consent decision from the tracker (paper/verbal consent).

    Lets a counsellor log the recipient's decision collected outside the
    portal. The outcome, signature name and actor are written to the immutable
    audit trail and a confirmation email is sent to the recipient.
    """
    _require_counsellor(user)
    consent = get_consent_by_id(consent_id)
    if not consent:
        raise HTTPException(404, "Consent not found")
    if consent["counsellor_id"] != user["id"] and user["role_type"] != "admin":
        raise HTTPException(403, "Access denied")
    if user["role_type"] != "admin":
        _require_counsellor_student_access(
            user, consent["student_id"], require_consent=False
        )
    decision = (data.get("decision") or "").strip().upper()
    if decision not in ("ACCEPTED", "DECLINED"):
        raise HTTPException(400, "decision must be 'ACCEPTED' or 'DECLINED'")
    signature_name = (data.get("signature_name") or "").strip() or None
    try:
        updated = record_consent_decision(
            consent_id,
            actor_id=user["id"],
            decision=decision,
            signature_name=signature_name,
            ip=_client_ip(request),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        logger.error("record_consent_decision error: %s", exc)
        raise HTTPException(500, "Failed to record decision")
    return {
        "ok": True,
        "status": updated["status"],
        "email_sent": bool(updated.get("email_sent"))
        if isinstance(updated, dict)
        else False,
        "consent_url": updated.get("consent_url", ""),
    }


@app.post("/api/v1/consents/{consent_id}/cancel")
async def v1_cancel_consent(
    consent_id: str,
    request: Request,
    user: dict = Depends(require_auth),
):
    _require_counsellor(user)
    consent = get_consent_by_id(consent_id)
    if not consent:
        raise HTTPException(404, "Consent not found")
    if consent["counsellor_id"] != user["id"] and user["role_type"] != "admin":
        raise HTTPException(403, "Access denied")
    if user["role_type"] != "admin":
        _require_counsellor_student_access(
            user, consent["student_id"], require_consent=False
        )
    if consent["status"] != "PENDING":
        raise HTTPException(
            400,
            f"Only PENDING consents can be cancelled (current: {consent['status']})",
        )
    try:
        from backend.database import update_consent_status

        updated = update_consent_status(consent_id, "DRAFT")
    except Exception as exc:
        logger.error("cancel_consent error: %s", exc)
        raise HTTPException(500, "Failed to cancel consent")
    write_audit(
        user["id"],
        user["role_type"],
        "CONSENT_CANCELLED",
        "consent",
        consent_id,
        ip=_client_ip(request),
    )
    return updated


# ── Consent portal (magic-link, no JWT required) ──────────────────────


@app.get("/api/v1/portal/consents/{token}")
async def v1_portal_get_consent(token: str, request: Request):
    consent = get_consent_by_token(token)
    if not consent:
        raise HTTPException(404, "Consent not found or link invalid")
    if not verify_consent_token(consent, token):
        raise HTTPException(404, "Consent not found or link invalid")
    if remaining_views(consent["id"]) <= 0:
        raise HTTPException(
            429,
            "This consent link has been opened too many times. Please contact your counsellor.",
        )
    # Validate magic token expiry
    expires = consent.get("magic_token_expires_at") or ""
    if expires and datetime.now(timezone.utc).isoformat() > expires:
        raise HTTPException(410, "This consent link has expired")
    if consent["status"] not in ("PENDING", "VIEWED", "ACCEPTED", "DECLINED"):
        raise HTTPException(410, "This consent link is no longer active")
    try:
        consent = record_view(
            consent["id"],
            ip=_client_ip(request),
            user_agent=_client_user_agent(request),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        logger.error("portal_get_consent error: %s", exc)
        raise HTTPException(500, "Failed to record view")
    # Strip sensitive fields before returning to unauthenticated recipients
    safe_keys = {
        "id",
        "student_id",
        "recipient_email",
        "recipient_role",
        "status",
        "platforms_json",
        "mode",
        "document_version",
        "dispatched_at",
        "viewed_at",
        "accepted_at",
        "declined_at",
        "expires_at",
        "created_at",
    }
    return {k: v for k, v in consent.items() if k in safe_keys}


@app.post("/api/v1/portal/consents/{token}/accept")
async def v1_portal_accept_consent(token: str, data: dict, request: Request):
    consent = get_consent_by_token(token)
    if not consent:
        raise HTTPException(404, "Consent not found or link invalid")
    if not verify_consent_token(consent, token):
        raise HTTPException(404, "Consent not found or link invalid")
    expires = consent.get("magic_token_expires_at") or ""
    if expires and datetime.now(timezone.utc).isoformat() > expires:
        raise HTTPException(410, "This consent link has expired")

    signature_name = (data.get("signature_name") or "").strip()
    if not signature_name:
        raise HTTPException(400, "signature_name is required")
    platforms = data.get("platforms")
    social_accounts = data.get("social_accounts")

    # Validate platforms and social accounts are within original consent scope
    import json as _json

    try:
        original = set(_json.loads(consent.get("platforms_json") or "[]"))
    except Exception:
        original = set()
    if platforms is not None:
        if not isinstance(platforms, list):
            raise HTTPException(400, "Invalid platforms format")
        submitted_set = set(platforms)
        extra = submitted_set - original
        if extra:
            logger.warning(
                "Consent %s: rejected platforms not in original request: %s",
                consent["id"],
                extra,
            )
            raise HTTPException(400, f"Invalid platforms: {', '.join(sorted(extra))}")
        requested = submitted_set
    else:
        requested = original
    if social_accounts:
        if not isinstance(social_accounts, dict):
            raise HTTPException(400, "Invalid social_accounts format")
        extra_sa = set(social_accounts.keys()) - requested
        if extra_sa:
            logger.warning(
                "Consent %s: rejected social platforms not in request: %s",
                consent["id"],
                extra_sa,
            )
            raise HTTPException(
                400, f"Invalid platforms: {', '.join(sorted(extra_sa))}"
            )

    try:
        updated = accept_consent(
            consent["id"],
            signature_name=signature_name,
            ip=_client_ip(request),
            platforms=platforms,
            user_agent=_client_user_agent(request),
            token=token,
            social_accounts=social_accounts,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        logger.error("portal_accept_consent error: %s", exc)
        raise HTTPException(500, "Failed to accept consent")
    return {
        "ok": True,
        "status": updated["status"],
        "guardian_account_available": updated.get("recipient_role") == "parent",
    }


@app.post("/api/v1/portal/consents/{token}/guardian-account")
async def create_guardian_account_from_consent(
    token: str, data: dict, request: Request
):
    """Create or link an optional guardian account after verified consent."""
    consent = get_consent_by_token(token)
    if not consent or not verify_consent_token(consent, token):
        raise HTTPException(404, "Consent not found or link invalid")
    if consent.get("recipient_role") != "parent" or consent.get("status") != "ACCEPTED":
        raise HTTPException(400, "Accept guardian consent before creating an account")
    password = data.get("password") or ""
    if len(password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    email = (consent.get("recipient_email") or "").strip().lower()
    guardian = get_user_by_email(email)
    if guardian:
        if (
            guardian.get("role_type") != "parent"
            and guardian.get("user_category") != "parent"
        ):
            raise HTTPException(
                409,
                "This verified email already belongs to another account. Sign in with that account to continue.",
            )
        if not guardian.get("password_hash"):
            update_user_password(guardian["id"], hash_password(password))
            update_user_status(guardian["id"], "approved")
    else:
        guardian = create_user(
            email,
            data.get("name") or "Parent or guardian",
            hash_password(password),
            role_type="parent",
        )
        update_user_status(guardian["id"], "approved")
        update_user_onboarding(guardian["id"], "parent")
        guardian = get_user_by_id(guardian["id"])
    link_parent_guardian(consent["student_id"], guardian["id"])
    write_audit(
        guardian["id"],
        "parent",
        "GUARDIAN_ACCOUNT_LINKED",
        "consent",
        consent["id"],
        ip=_client_ip(request),
    )
    fresh = get_user_by_id(guardian["id"])
    return {
        "ok": True,
        "access_token": create_access_token(fresh["id"], fresh["role_type"]),
        "user": {
            "id": fresh["id"],
            "email": fresh["email"],
            "name": fresh["name"],
            "role_type": fresh["role_type"],
            "user_category": _auth_user_category(fresh),
            "institution_id": None,
        },
    }


@app.get("/api/guardian/consents")
async def guardian_consents(user: dict = Depends(require_auth)):
    if user.get("role_type") != "parent" and user.get("user_category") != "parent":
        raise HTTPException(403, "Guardian account required")
    from backend.database import get_db

    conn = get_db()
    rows = conn.execute(
        "SELECT c.id, c.status, c.accepted_at, c.revoked_at, c.expires_at, c.recipient_role, "
        "s.name AS student_name, i.name AS institution_name "
        "FROM consents c JOIN users s ON s.id = c.student_id "
        "LEFT JOIN institutions i ON i.id = s.institution_id "
        "WHERE s.parent_guardian_id = ? AND c.recipient_role = 'parent' ORDER BY c.created_at DESC",
        (user["id"],),
    ).fetchall()
    conn.close()
    return {"consents": [dict(row) for row in rows]}


@app.post("/api/guardian/consents/{consent_id}/revoke")
async def guardian_revoke_consent(
    consent_id: str, request: Request, user: dict = Depends(require_auth)
):
    if user.get("role_type") != "parent" and user.get("user_category") != "parent":
        raise HTTPException(403, "Guardian account required")
    consent = get_consent_by_id(consent_id)
    if not consent or consent.get("recipient_role") != "parent":
        raise HTTPException(404, "Consent not found")
    student = get_user_by_id(consent["student_id"])
    if not student or student.get("parent_guardian_id") != user["id"]:
        raise HTTPException(403, "This consent is not linked to your guardian account")
    updated = revoke_consent(
        consent_id, ip=_client_ip(request), user_agent=_client_user_agent(request)
    )
    write_audit(
        user["id"],
        "parent",
        "GUARDIAN_CONSENT_REVOKED",
        "consent",
        consent_id,
        ip=_client_ip(request),
    )
    return {"ok": True, "status": updated["status"]}


@app.post("/api/v1/portal/consents/{token}/decline")
async def v1_portal_decline_consent(token: str, request: Request):
    consent = get_consent_by_token(token)
    if not consent:
        raise HTTPException(404, "Consent not found or link invalid")
    if not verify_consent_token(consent, token):
        raise HTTPException(404, "Consent not found or link invalid")
    expires = consent.get("magic_token_expires_at") or ""
    if expires and datetime.now(timezone.utc).isoformat() > expires:
        raise HTTPException(410, "This consent link has expired")
    try:
        updated = decline_consent(
            consent["id"],
            ip=_client_ip(request),
            user_agent=_client_user_agent(request),
            token=token,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        logger.error("portal_decline_consent error: %s", exc)
        raise HTTPException(500, "Failed to decline consent")
    return {"ok": True, "status": updated["status"]}


@app.post("/api/v1/portal/consents/{token}/revoke")
async def v1_portal_revoke_consent(token: str, request: Request):
    consent = get_consent_by_token(token)
    if not consent:
        raise HTTPException(404, "Consent not found or link invalid")
    if not verify_consent_token(consent, token):
        raise HTTPException(404, "Consent not found or link invalid")
    try:
        updated = revoke_consent(
            consent["id"],
            ip=_client_ip(request),
            user_agent=_client_user_agent(request),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        logger.error("portal_revoke_consent error: %s", exc)
        raise HTTPException(500, "Failed to revoke consent")
    return {"ok": True, "status": updated["status"]}


# ── Account linking ───────────────────────────────────────────────────


@app.get("/api/v1/students/{student_id}/accounts")
async def v1_list_accounts(student_id: str, user: dict = Depends(require_auth)):
    student = get_user_by_id(student_id)
    if not student or student["role_type"] != "student":
        raise HTTPException(404, "Student not found")
    _require_counsellor_student_access(user, student_id)
    accounts = get_linked_accounts(student_id)
    return {"accounts": accounts, "total": len(accounts)}


@app.post("/api/v1/students/{student_id}/accounts", status_code=201)
async def v1_create_account(
    student_id: str,
    data: dict,
    request: Request,
    user: dict = Depends(require_auth),
):
    student = get_user_by_id(student_id)
    if not student or student["role_type"] != "student":
        raise HTTPException(404, "Student not found")
    _require_counsellor_student_access(user, student_id)

    platform = (data.get("platform") or "").strip().lower()
    if not platform:
        raise HTTPException(400, "platform is required")

    mode = data.get("mode", "handle")
    if mode not in ("oauth", "handle"):
        raise HTTPException(400, "mode must be 'oauth' or 'handle'")

    handle = (data.get("handle") or "").strip() or None
    consent_id = data.get("consent_id")
    if consent_id:
        linked_consent = get_consent_by_id(consent_id)
        if (
            not linked_consent
            or linked_consent.get("student_id") != student_id
            or (
                user["role_type"] != "admin"
                and linked_consent.get("counsellor_id") != user["id"]
            )
        ):
            raise HTTPException(
                403, "Consent does not belong to this student and counsellor"
            )

    try:
        account = create_linked_account(student_id, consent_id, platform, mode, handle)
    except Exception as exc:
        logger.error("create_linked_account error: %s", exc)
        raise HTTPException(500, "Failed to link account")

    write_audit(
        user["id"],
        user["role_type"],
        "ACCOUNT_LINKED",
        "linked_account",
        account["id"],
        payload={"student_id": student_id, "platform": platform},
        ip=_client_ip(request),
    )
    return account


@app.delete("/api/v1/students/{student_id}/accounts/{account_id}")
async def v1_delete_account(
    student_id: str,
    account_id: str,
    request: Request,
    user: dict = Depends(require_auth),
):
    student = get_user_by_id(student_id)
    if not student or student["role_type"] != "student":
        raise HTTPException(404, "Student not found")
    _require_counsellor_student_access(user, student_id)

    ok = revoke_linked_account(account_id, student_id=student_id)
    if not ok:
        raise HTTPException(404, "Linked account not found")

    write_audit(
        user["id"],
        user["role_type"],
        "ACCOUNT_REVOKED",
        "linked_account",
        account_id,
        payload={"student_id": student_id},
        ip=_client_ip(request),
    )
    return {"ok": True}


# ── Alert queue ───────────────────────────────────────────────────────


@app.get("/api/v1/alerts")
async def v1_list_alerts(
    status: str = "OPEN",
    institution_id: str | None = None,
    user: dict = Depends(require_auth),
):
    _require_counsellor(user)
    scoped = _require_institution_scope(user, institution_id)
    valid_statuses = {
        "OPEN",
        "ACKNOWLEDGED",
        "ESCALATED",
        "IN_PROGRESS",
        "CLOSED",
        "FALSE_POSITIVE",
    }
    filter_status = status.upper() if status.upper() in valid_statuses else None
    alerts = get_alerts(
        None if user["role_type"] in ("admin", "school_admin") else user["id"],
        status=filter_status,
        institution_id=scoped,
    )
    return {"alerts": alerts, "total": len(alerts)}


_VALID_DISPOSITIONS = {"REACH_OUT", "SCHEDULE_CHECKIN", "ESCALATE", "DISMISS"}


@app.post("/api/v1/alerts/{alert_id}/disposition")
async def v1_dispose_alert(
    alert_id: str,
    data: dict,
    request: Request,
    user: dict = Depends(require_auth),
):
    _require_counsellor(user)
    action = (data.get("action") or "").strip().upper()
    if action not in _VALID_DISPOSITIONS:
        raise HTTPException(
            400, f"action must be one of: {', '.join(sorted(_VALID_DISPOSITIONS))}"
        )

    reason_code = (data.get("reason_code") or "").strip()
    reason_note = (data.get("reason_note") or "").strip()
    alert = get_alert_by_id(alert_id)
    if not alert:
        raise HTTPException(404, "Alert not found")
    if user["role_type"] == "admin":
        pass
    elif user["role_type"] == "school_admin":
        scoped = _require_institution_scope(user)
        student = get_user_by_id(alert["student_id"])
        if not student or student.get("institution_id") != scoped:
            raise HTTPException(403, "Alert is outside your institution")
    elif alert.get("counsellor_id") != user["id"]:
        raise HTTPException(403, "You do not own this alert")

    try:
        workflow_status = {
            "DISMISS": "FALSE_POSITIVE",
            "ESCALATE": "ESCALATED",
            "REACH_OUT": "IN_PROGRESS",
            "SCHEDULE_CHECKIN": "IN_PROGRESS",
        }[action]
        result = transition_alert(
            alert_id, workflow_status, user["id"], reason_note or reason_code
        )
    except Exception as exc:
        logger.error("dispose_alert error: %s", exc)
        raise HTTPException(500, "Failed to dispose alert")

    if not result:
        raise HTTPException(404, "Alert not found")

    write_audit(
        user["id"],
        user["role_type"],
        "ALERT_DISPOSITIONED",
        "alert",
        alert_id,
        payload={"action": action, "reason_code": reason_code},
        ip=_client_ip(request),
    )
    return result


# ── Risk timeline ─────────────────────────────────────────────────────


@app.get("/api/v1/students/{student_id}/timeline")
async def v1_student_timeline(student_id: str, user: dict = Depends(require_auth)):
    student = get_user_by_id(student_id)
    if not student or student["role_type"] != "student":
        raise HTTPException(404, "Student not found")
    _require_counsellor_student_access(user, student_id)

    history = get_rolling_risk_history(student_id)
    alerts = get_alerts(
        None if user.get("role_type") == "admin" else user["id"],
        status=None,
        institution_id=user.get("institution_id")
        if user.get("role_type") != "admin"
        else None,
    )
    student_alerts = [a for a in alerts if a["student_id"] == student_id]

    return {
        "student_id": student_id,
        "student_name": student["name"],
        "rolling_risk_history": history,
        "alert_markers": [
            {
                "id": a["id"],
                "fired_at": a["fired_at"],
                "risk_score": a["risk_score"],
                "platform": a["platform"],
                "status": a["status"],
                "disposition": a["disposition"],
            }
            for a in student_alerts
        ],
    }


# ── Notes ─────────────────────────────────────────────────────────────


@app.get("/api/v1/students/{student_id}/notes")
async def v1_list_notes(student_id: str, user: dict = Depends(require_auth)):
    student = get_user_by_id(student_id)
    if not student or student["role_type"] != "student":
        raise HTTPException(404, "Student not found")
    _require_counsellor_student_access(user, student_id)
    notes = get_notes(student_id)
    return {"notes": notes, "total": len(notes)}


@app.post("/api/v1/students/{student_id}/notes", status_code=201)
async def v1_create_note(
    student_id: str,
    data: dict,
    request: Request,
    user: dict = Depends(require_auth),
):
    student = get_user_by_id(student_id)
    if not student or student["role_type"] != "student":
        raise HTTPException(404, "Student not found")
    _require_counsellor_student_access(user, student_id)

    body = (data.get("body") or "").strip()
    if not body:
        raise HTTPException(400, "Note body cannot be empty")

    try:
        note = create_note(student_id=student_id, author_id=user["id"], body=body)
    except Exception as exc:
        logger.error("create_note error: %s", exc)
        raise HTTPException(500, "Failed to create note")

    write_audit(
        user["id"],
        user["role_type"],
        "NOTE_CREATED",
        "note",
        note["id"],
        payload={"student_id": student_id},
        ip=_client_ip(request),
    )
    return note


# ── Audit log ─────────────────────────────────────────────────────────


@app.get("/api/v1/audit")
async def v1_audit_log(limit: int = 100, user: dict = Depends(require_auth)):
    _require_counsellor(user)
    if limit < 1 or limit > 1000:
        raise HTTPException(400, "limit must be between 1 and 1000")
    entries = get_audit_log(user["id"], limit=limit)
    return {"entries": entries, "total": len(entries)}


# ── Roster & school-admin (Delivery Brief §5) ─────────────────────────


@app.post("/api/v1/admin/roster/upload")
async def v1_admin_roster_upload(
    institution_id: str,
    file: UploadFile = File(...),
    user: dict = Depends(require_auth),
):
    require_permission(user, PERM_ROSTER_UPLOAD)
    _require_institution_admin(user, institution_id)
    inst = get_institution_by_id(institution_id)
    if not inst:
        raise HTTPException(404, "Institution not found")
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Uploaded file is empty")
    if len(raw) > 50 * 1024 * 1024:
        raise HTTPException(413, "File too large (max 50 MB)")
    try:
        minor_age = int(inst.get("minor_age_threshold") or 18)
    except (TypeError, ValueError):
        minor_age = 18
    summary = upsert_roster(
        institution_id, raw, user["id"], minor_age_threshold=minor_age
    )
    write_audit(
        user["id"],
        user["role_type"],
        "ROSTER_UPLOAD",
        "institution",
        institution_id,
        payload={
            "created": summary["created"],
            "updated": summary["updated"],
            "errors": len(summary["errors"]),
            "total": summary["total"],
        },
    )
    return summary


@app.post("/api/v1/admin/roster/commit")
async def v1_admin_roster_commit(
    institution_id: str,
    file: UploadFile = File(...),
    request: Request = None,
    user: dict = Depends(require_auth),
):
    """Roster upload + consent dispatch in one action (Delivery Brief §2.5).

    Upserts the CSV rows, then creates and dispatches a signed consent request
    for every student that lacks a live consent — routed per §2.4 (adult ->
    student; minor -> parent, plus an informational courtesy copy to the student).
    """
    require_permission(user, PERM_ROSTER_UPLOAD)
    _require_institution_admin(user, institution_id)
    inst = get_institution_by_id(institution_id)
    if not inst:
        raise HTTPException(404, "Institution not found")
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Uploaded file is empty")
    if len(raw) > 50 * 1024 * 1024:
        raise HTTPException(413, "File too large (max 50 MB)")
    try:
        minor_age = int(inst.get("minor_age_threshold") or 18)
    except (TypeError, ValueError):
        minor_age = 18
    summary = upsert_roster(
        institution_id, raw, user["id"], minor_age_threshold=minor_age
    )
    student_ids = summary.get("student_ids") or []
    students = [s for s in (get_student_by_id(i) for i in student_ids) if s]
    try:
        dispatch = dispatch_consents_for_students(
            students, user["id"], ip=_client_ip(request)
        )
    except Exception:
        # Roster ingestion is already committed at this point. Keep the
        # imported students visible and return a structured dispatch failure
        # instead of turning the whole operation into an opaque HTTP 500.
        logger.exception(
            "Roster consent dispatch failed institution=%s", institution_id
        )
        dispatch = {
            "checked": len(students),
            "created": 0,
            "dispatched": 0,
            "email_queued": 0,
            "courtesy_queued": 0,
            "skipped_live": 0,
            "skipped_no_parent": 0,
            "users_created": 0,
            "routing_errors": [
                {
                    "student_id": "batch",
                    "reason": "Consent dispatch failed; retry from the student onboarding page.",
                }
            ],
        }
    write_audit(
        user["id"],
        user["role_type"],
        "ROSTER_COMMIT",
        "institution",
        institution_id,
        payload={
            "created": summary["created"],
            "updated": summary["updated"],
            "errors": len(summary["errors"]),
            "total": summary["total"],
            "consents_dispatched": dispatch["dispatched"],
            "consents_queued": dispatch["email_queued"],
            "skipped_no_parent": dispatch["skipped_no_parent"],
        },
    )
    return {"roster": summary, "dispatch": dispatch}


@app.get("/api/v1/admin/roster-conflicts")
async def v1_admin_roster_conflict(student_id: str, user: dict = Depends(require_auth)):
    """Find the existing roster record blocking a school-ID import."""
    if user.get("role_type") != "admin":
        raise HTTPException(403, "Only global admins can resolve roster conflicts")
    normalized_id = (student_id or "").strip()
    if not normalized_id:
        raise HTTPException(400, "student_id is required")
    student = get_student_by_student_id_hash(hash_student_id(normalized_id))
    if not student:
        raise HTTPException(
            404, "No active roster record was found for this student ID"
        )
    institution = get_institution_by_id(student.get("institution_id")) or {}
    return {
        "id": student["id"],
        "student_id": normalized_id,
        "name": decrypt_pii(student.get("first_name_encrypted") or ""),
        "email": decrypt_pii(student.get("email_encrypted") or ""),
        "institution": {
            "id": institution.get("id"),
            "name": institution.get("name") or "Unknown institution",
        },
        "has_linked_account": bool(student.get("user_id")),
    }


@app.post("/api/v1/admin/roster-conflicts/purge")
async def v1_admin_purge_roster_conflict(
    data: dict, request: Request, user: dict = Depends(require_auth)
):
    """Permanently remove a duplicate roster record after explicit confirmation."""
    if user.get("role_type") != "admin":
        raise HTTPException(403, "Only global admins can resolve roster conflicts")
    student_id = (data.get("student_id") or "").strip()
    if not student_id or data.get("confirmation") != student_id:
        raise HTTPException(400, "Type the exact student ID to confirm removal")
    student = get_student_by_student_id_hash(hash_student_id(student_id))
    if not student:
        raise HTTPException(
            404, "No active roster record was found for this student ID"
        )
    removed = purge_roster_student(student["id"])
    if not removed:
        raise HTTPException(404, "Roster record was already removed")
    write_audit(
        user["id"],
        user["role_type"],
        "ROSTER_CONFLICT_PURGED",
        "student",
        student["id"],
        payload={
            "student_id_hash": student["student_id_hash"],
            "institution_id": student.get("institution_id"),
            "linked_account_preserved": bool(student.get("user_id")),
        },
        ip=_client_ip(request),
    )
    return {
        "ok": True,
        "student_id": student_id,
        "linked_account_preserved": bool(student.get("user_id")),
    }


@app.get("/api/v1/admin/students")
async def v1_admin_list_students(
    institution_id: str | None = None,
    limit: int = 200,
    offset: int = 0,
    user: dict = Depends(require_auth),
):
    require_permission(user, PERM_STUDENTS_VIEW)
    institution_id = _require_institution_scope(user, institution_id)
    limit = max(1, min(limit, 1000))
    offset = max(0, offset)
    rows = list_students(institution_id=institution_id, limit=limit, offset=offset)
    out = []
    for s in rows:
        consent = None
        if s.get("current_consent_id"):
            consent = get_consent_by_id(s["current_consent_id"])
        out.append(
            {
                "id": s["id"],
                "student_id_hash": s["student_id_hash"],
                "name": decrypt_pii(s["first_name_encrypted"]),
                "email": decrypt_pii(s["email_encrypted"]),
                "is_minor": bool(s["is_minor"]),
                "grade_level": s["grade_level"],
                "consent_status": consent["status"] if consent else None,
            }
        )
    return {"students": out, "total": len(out)}


@app.get("/api/admin/available-students")
async def available_students(user: dict = Depends(require_auth)):
    """List approved students not assigned to any counsellor."""
    if user["role_type"] != "admin":
        raise HTTPException(403, "Admin access required")
    from backend.database import get_db

    conn = get_db()
    # Only institution-managed students are eligible for assignment.
    all_students = [s for s in get_students(limit=10000) if s["status"] == "approved"]
    assigned_ids = set()
    # Get all active assignments to find which students are already assigned
    rows = conn.execute(
        "SELECT DISTINCT student_id FROM counsellor_student_assignments WHERE active = 1"
    ).fetchall()
    assigned_ids = {r["student_id"] for r in rows}
    out = []
    for s in all_students:
        if s["id"] not in assigned_ids:
            out.append(
                {
                    "id": s["id"],
                    "email": s["email"],
                    "name": s["name"],
                    "role_type": s["role_type"],
                    "status": s["status"],
                }
            )
    conn.close()
    return {"students": out, "total": len(out)}


@app.get("/api/v1/admin/institutions")
async def v1_admin_list_institutions(user: dict = Depends(require_auth)):
    require_any_permission(user, {PERM_ROSTER_UPLOAD, PERM_STUDENTS_VIEW})
    scoped = _require_institution_scope(user)
    insts = list_institutions()
    if scoped:
        insts = [i for i in insts if i["id"] == scoped]
    return {
        "institutions": [
            {
                "id": i["id"],
                "name": i["name"],
                "type": i.get("type"),
                "minor_age_threshold": i.get("minor_age_threshold", 18),
                "consent_reminder_days": i.get("consent_reminder_days", "[3,7]"),
                "consent_expiry_days": i.get("consent_expiry_days", 30),
                "status": i.get("status") or "PROVISIONING",
            }
            for i in insts
        ]
    }


@app.post("/api/v1/admin/institutions", status_code=201)
async def v1_admin_create_institution(
    data: dict,
    request: Request,
    user: dict = Depends(require_auth),
):
    if user.get("role_type") != "admin":
        raise HTTPException(403, "Only global admins can create institutions")
    name = (data.get("name") or "").strip()
    inst_type = (data.get("type") or "university").strip().lower()
    if not name:
        raise HTTPException(400, "Institution name is required")
    if len(name) > 200:
        raise HTTPException(400, "Institution name is too long")
    institution = create_institution(name, inst_type, created_by=user["id"])
    write_audit(
        user["id"],
        user["role_type"],
        "INSTITUTION_CREATED",
        "institution",
        institution["id"],
        payload={"type": inst_type},
        ip=_client_ip(request),
    )
    return institution


@app.patch("/api/v1/admin/institutions/{institution_id}")
async def v1_admin_update_institution(
    institution_id: str,
    data: dict,
    request: Request,
    user: dict = Depends(require_auth),
):
    if user.get("role_type") != "admin":
        raise HTTPException(403, "Only global admins can change institution lifecycle")
    institution = get_institution_by_id(institution_id)
    if not institution:
        raise HTTPException(404, "Institution not found")
    status = data.get("status")
    if status and status not in (
        "PROVISIONING",
        "ACTIVE",
        "READY",
        "SUSPENDED",
        "ARCHIVED",
    ):
        raise HTTPException(400, "Invalid institution status")
    updates = {key: data[key] for key in ("name", "type", "status") if key in data}
    updated = update_institution(institution_id, **updates)
    write_audit(
        user["id"],
        user["role_type"],
        "INSTITUTION_UPDATED",
        "institution",
        institution_id,
        payload={"fields": sorted(updates)},
        ip=_client_ip(request),
    )
    return updated


@app.get("/api/institution/me")
async def institution_workspace(user: dict = Depends(require_auth)):
    institution_id = _require_institution_scope(user)
    if not institution_id:
        raise HTTPException(400, "Global admins must select an institution context")
    institution = get_institution_by_id(institution_id)
    students = list_students(institution_id=institution_id, limit=1000)
    from backend.database import get_db

    conn = get_db()
    staff_count = conn.execute(
        "SELECT COUNT(*) FROM users WHERE institution_id = ? AND role_type IN ('counsellor', 'school_admin') AND status = 'approved'",
        (institution_id,),
    ).fetchone()[0]
    assignment_count = conn.execute(
        "SELECT COUNT(*) FROM counsellor_student_assignments WHERE institution_id = ? AND active = 1",
        (institution_id,),
    ).fetchone()[0]
    conn.close()
    return {
        "institution": institution,
        "counts": {
            "students": len(students),
            "staff": staff_count,
            "active_assignments": assignment_count,
        },
    }


@app.get("/api/institution/settings")
async def get_institution_settings(user: dict = Depends(require_auth)):
    institution_id = _require_institution_admin(user)
    if not institution_id:
        raise HTTPException(400, "An institution context is required")
    return get_institution_by_id(institution_id)


@app.patch("/api/institution/settings")
async def patch_institution_settings(
    data: dict, request: Request, user: dict = Depends(require_auth)
):
    institution_id = _require_institution_admin(user)
    if not institution_id:
        raise HTTPException(400, "An institution context is required")
    allowed = {
        "name",
        "type",
        "retention_days",
        "alert_threshold",
        "confidence_floor",
        "minor_age_threshold",
        "consent_template_id",
        "consent_reminder_days",
        "consent_expiry_days",
    }
    updates = {key: data[key] for key in allowed if key in data}
    if "retention_days" in updates and (
        not isinstance(updates["retention_days"], int)
        or not 1 <= updates["retention_days"] <= 3650
    ):
        raise HTTPException(400, "retention_days must be between 1 and 3650")
    if "alert_threshold" in updates and (
        not isinstance(updates["alert_threshold"], (int, float))
        or not 0 <= updates["alert_threshold"] <= 1
    ):
        raise HTTPException(400, "alert_threshold must be between 0 and 1")
    if "confidence_floor" in updates and (
        not isinstance(updates["confidence_floor"], (int, float))
        or not 0 <= updates["confidence_floor"] <= 1
    ):
        raise HTTPException(400, "confidence_floor must be between 0 and 1")
    if "consent_expiry_days" in updates and (
        not isinstance(updates["consent_expiry_days"], int)
        or not 1 <= updates["consent_expiry_days"] <= 365
    ):
        raise HTTPException(400, "consent_expiry_days must be between 1 and 365")
    if "consent_reminder_days" in updates:
        reminders = updates["consent_reminder_days"]
        if not isinstance(reminders, list) or any(
            not isinstance(day, int) or day < 1 for day in reminders
        ):
            raise HTTPException(
                400, "consent_reminder_days must be a list of positive integers"
            )
        updates["consent_reminder_days"] = json.dumps(reminders)
    updated = update_institution(institution_id, **updates)
    write_audit(
        user["id"],
        user["role_type"],
        "INSTITUTION_SETTINGS_UPDATED",
        "institution",
        institution_id,
        payload={"fields": sorted(updates)},
        ip=_client_ip(request),
    )
    return updated


@app.get("/api/institution/staff")
async def list_institution_staff(user: dict = Depends(require_auth)):
    institution_id = _require_institution_scope(user)
    if not institution_id:
        raise HTTPException(400, "Global admins must select an institution context")
    from backend.database import get_db

    conn = get_db()
    rows = conn.execute(
        "SELECT u.id, u.email, u.name, u.role_type, u.status, u.institution_id, u.created_at, u.invitation_token_hash, u.profile_completed_at, u.phone, u.country, u.address, u.professional_title, u.qualification, u.emergency_contact, u.max_caseload, "
        "COUNT(a.id) AS active_assignment_count FROM users u "
        "LEFT JOIN counsellor_student_assignments a ON a.counsellor_id = u.id AND a.active = 1 "
        "WHERE u.institution_id = ? AND u.role_type IN ('counsellor', 'school_admin') "
        "GROUP BY u.id ORDER BY u.name COLLATE NOCASE",
        (institution_id,),
    ).fetchall()
    conn.close()
    return [
        {
            **dict(row),
            "invitation_pending": bool(row["invitation_token_hash"]),
            "profile_completed": bool(row["profile_completed_at"]),
            "active_assignment_count": int(row["active_assignment_count"] or 0),
            "max_caseload": row["max_caseload"],
            "availability": (
                "unavailable"
                if row["role_type"] != "counsellor"
                or row["status"] not in ("approved", "active")
                or not row["profile_completed_at"]
                else "at_capacity"
                if row["max_caseload"] is not None
                and int(row["active_assignment_count"] or 0) >= row["max_caseload"]
                else "available"
            ),
            "profile": {
                key: decrypt_pii(row[key])
                if isinstance(row[key], str) and row[key].startswith("gcm1:")
                else (row[key] or "")
                for key in (
                    "phone",
                    "country",
                    "address",
                    "professional_title",
                    "qualification",
                    "emergency_contact",
                )
            },
        }
        for row in rows
    ]


@app.get("/api/institution/consents")
async def list_institution_consents(
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    user: dict = Depends(require_auth),
):
    institution_id = _require_institution_scope(user)
    if not institution_id:
        raise HTTPException(400, "An institution context is required")
    if limit < 1 or limit > 1000 or offset < 0:
        raise HTTPException(400, "Invalid pagination")
    from backend.database import get_db

    conn = get_db()
    clauses = ["u.institution_id = ?"]
    params: list[Any] = [institution_id]
    if user.get("role_type") == "counsellor":
        clauses.append("c.counsellor_id = ?")
        params.append(user["id"])
    if status:
        clauses.append("c.status = ?")
        params.append(status)
    where = " AND ".join(clauses)
    total = conn.execute(
        f"SELECT COUNT(*) FROM consents c JOIN users u ON u.id = c.student_id WHERE {where}",
        params,
    ).fetchone()[0]
    rows = conn.execute(
        f"SELECT c.*, u.name AS student_name, u.email AS student_email "
        f"FROM consents c JOIN users u ON u.id = c.student_id WHERE {where} "
        "ORDER BY c.created_at DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    ).fetchall()
    conn.close()
    return {"consents": [dict(row) for row in rows], "total": total}


@app.get("/api/institution/assignments")
async def list_institution_assignments(user: dict = Depends(require_auth)):
    institution_id = _require_institution_scope(user)
    if not institution_id:
        raise HTTPException(400, "An institution context is required")
    from backend.database import get_db

    conn = get_db()
    rows = conn.execute(
        "SELECT a.*, c.name AS counsellor_name, c.email AS counsellor_email, "
        "s.name AS student_name, s.email AS student_email "
        "FROM counsellor_student_assignments a "
        "JOIN users c ON c.id = a.counsellor_id JOIN users s ON s.id = a.student_id "
        "WHERE a.institution_id = ? AND a.active = 1 ORDER BY a.assigned_at DESC",
        (institution_id,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


@app.get("/api/institution/assignments/history")
async def list_institution_assignment_history(user: dict = Depends(require_auth)):
    institution_id = _require_institution_scope(user)
    if not institution_id:
        raise HTTPException(400, "An institution context is required")
    from backend.database import get_db

    conn = get_db()
    rows = conn.execute(
        "SELECT a.*, c.name AS counsellor_name, s.name AS student_name "
        "FROM counsellor_student_assignments a JOIN users c ON c.id = a.counsellor_id "
        "JOIN users s ON s.id = a.student_id WHERE a.institution_id = ? "
        "ORDER BY a.assigned_at DESC LIMIT 500",
        (institution_id,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


@app.get("/api/institution/assignable")
async def list_institution_assignable(user: dict = Depends(require_auth)):
    institution_id = _require_institution_admin(user)
    if not institution_id:
        raise HTTPException(400, "An institution context is required")
    from backend.database import get_db

    conn = get_db()
    counsellors = conn.execute(
        "SELECT u.id, u.name, u.email, u.status, u.profile_completed_at, u.max_caseload, COUNT(a.id) AS active_assignment_count FROM users u "
        "LEFT JOIN counsellor_student_assignments a ON a.counsellor_id = u.id AND a.active = 1 "
        "WHERE u.institution_id = ? AND u.role_type = 'counsellor' GROUP BY u.id ORDER BY u.name COLLATE NOCASE",
        (institution_id,),
    ).fetchall()
    students = conn.execute(
        "SELECT s.id AS roster_id, s.user_id, s.first_name_encrypted, s.email_encrypted, s.is_minor, s.current_consent_id, "
        "u.status AS account_status, u.invitation_token_hash, a.id AS assignment_id, a.counsellor_id, c.name AS counsellor_name "
        "FROM students s LEFT JOIN users u ON u.id = s.user_id "
        "LEFT JOIN counsellor_student_assignments a ON a.student_id = s.user_id AND a.institution_id = ? AND a.active = 1 "
        "LEFT JOIN users c ON c.id = a.counsellor_id "
        "WHERE s.institution_id = ? AND s.deleted_at IS NULL AND s.archived_at IS NULL ORDER BY s.created_at DESC",
        (institution_id, institution_id),
    ).fetchall()
    conn.close()
    student_items = []
    for row in students:
        consent = (
            get_consent_by_id(row["current_consent_id"])
            if row["current_consent_id"]
            else None
        )
        if not row["user_id"]:
            access_status = "account_link_pending"
        elif row["is_minor"] and (not consent or consent.get("status") != "ACCEPTED"):
            access_status = "guardian_consent_pending"
        elif (
            not row["current_consent_id"]
            or not consent
            or consent.get("status") != "ACCEPTED"
        ):
            access_status = "student_consent_pending"
        else:
            access_status = "ready"
        student_items.append(
            {
                "id": row["roster_id"],
                "account_id": row["user_id"],
                "name": decrypt_pii(row["first_name_encrypted"]),
                "email": decrypt_pii(row["email_encrypted"]),
                "is_minor": bool(row["is_minor"]),
                "status": row["account_status"] or "imported",
                "assignment_id": row["assignment_id"],
                "counsellor_id": row["counsellor_id"],
                "counsellor_name": row["counsellor_name"],
                "access_status": access_status,
            }
        )
    counsellor_items = []
    for row in counsellors:
        item = dict(row)
        item["availability"] = (
            "unavailable"
            if item["status"] not in ("approved", "active")
            or not item["profile_completed_at"]
            else (
                "at_capacity"
                if item["max_caseload"] is not None
                and item["active_assignment_count"] >= item["max_caseload"]
                else "available"
            )
        )
        counsellor_items.append(item)
    return {"counsellors": counsellor_items, "students": student_items}


@app.post("/api/institution/assignments")
async def create_institution_assignment(
    data: dict, request: Request, user: dict = Depends(require_auth)
):
    institution_id = _require_institution_admin(user)
    if not institution_id:
        raise HTTPException(400, "An institution context is required")
    counsellor_id = data.get("counsellor_id")
    student_id = data.get("student_id")
    counsellor = get_user_by_id(counsellor_id) if counsellor_id else None
    roster_student = get_student_by_id(student_id) if student_id else None
    if (
        not counsellor
        or counsellor.get("role_type") != "counsellor"
        or counsellor.get("institution_id") != institution_id
    ):
        raise HTTPException(400, "Counsellor is not in this institution")
    if counsellor.get("status") not in ("approved", "active") or not counsellor.get(
        "profile_completed_at"
    ):
        raise HTTPException(
            400, "Counsellor must be active and have a complete profile"
        )
    max_caseload = counsellor.get("max_caseload")
    if max_caseload is not None:
        from backend.database import get_db

        conn = get_db()
        current_load = conn.execute(
            "SELECT COUNT(*) FROM counsellor_student_assignments WHERE counsellor_id = ? AND active = 1",
            (counsellor_id,),
        ).fetchone()[0]
        conn.close()
        if current_load >= int(max_caseload):
            raise HTTPException(
                409, "Counsellor has reached their active-student limit"
            )
    if (
        not roster_student
        or roster_student.get("institution_id") != institution_id
        or roster_student.get("archived_at")
        or roster_student.get("deleted_at")
    ):
        raise HTTPException(400, "Student is not in this institution")
    # Assignment is roster-driven. Reconcile a missing account on demand so a
    # valid roster student is never hidden merely because a prior import did
    # not finish creating its invitation/account link.
    if not roster_student.get("user_id"):
        dispatch_consents_for_students(
            [roster_student], user["id"], ip=_client_ip(request)
        )
        roster_student = get_student_by_id(roster_student["id"])
    if not roster_student or not roster_student.get("user_id"):
        raise HTTPException(
            409,
            "Student account could not be prepared; resend the student invitation and try again",
        )
    assignment = assign_student_to_counsellor(
        counsellor_id, roster_student["user_id"], institution_id, user["id"]
    )
    write_audit(
        user["id"],
        user["role_type"],
        "STUDENT_ASSIGNED",
        "student",
        roster_student["id"],
        payload={"counsellor_id": counsellor_id, "institution_id": institution_id},
        ip=_client_ip(request),
    )
    return {"ok": True, "assignment": assignment}


@app.delete("/api/institution/assignments/{assignment_id}")
async def delete_institution_assignment(
    assignment_id: str, request: Request, user: dict = Depends(require_auth)
):
    institution_id = _require_institution_admin(user)
    assignment = get_assignment(assignment_id)
    if not assignment or assignment.get("institution_id") != institution_id:
        raise HTTPException(404, "Assignment not found")
    unassign_student_from_counsellor(assignment_id)
    write_audit(
        user["id"],
        user["role_type"],
        "STUDENT_UNASSIGNED",
        "user",
        assignment["student_id"],
        payload={
            "counsellor_id": assignment["counsellor_id"],
            "institution_id": institution_id,
        },
        ip=_client_ip(request),
    )
    return {"ok": True}


@app.get("/api/institution/audit")
async def list_institution_audit(limit: int = 100, user: dict = Depends(require_auth)):
    institution_id = _require_institution_scope(user)
    if not institution_id:
        raise HTTPException(400, "An institution context is required")
    if limit < 1 or limit > 1000:
        raise HTTPException(400, "limit must be between 1 and 1000")
    from backend.database import get_db

    conn = get_db()
    rows = conn.execute(
        "SELECT a.* FROM audit_log a JOIN users u ON u.id = a.actor_id "
        "WHERE u.institution_id = ? ORDER BY a.occurred_at DESC LIMIT ?",
        (institution_id, limit),
    ).fetchall()
    conn.close()
    return {"entries": [dict(row) for row in rows], "total": len(rows)}


@app.post("/api/institution/students/{student_id}/archive")
async def archive_institution_student(
    student_id: str, request: Request, user: dict = Depends(require_auth)
):
    institution_id = _require_institution_admin(user)
    if not institution_id:
        raise HTTPException(400, "An institution context is required")
    student = get_student_by_id(student_id)
    if not student:
        student = get_student_by_user_id(student_id)
    if not student or student.get("institution_id") != institution_id:
        raise HTTPException(404, "Student not found")
    if student.get("user_id"):
        from backend.database import get_db

        conn = get_db()
        assignments = conn.execute(
            "SELECT id FROM counsellor_student_assignments WHERE student_id = ? AND active = 1",
            (student["user_id"],),
        ).fetchall()
        conn.close()
        for assignment in assignments:
            unassign_student_from_counsellor(assignment["id"])
    if not archive_student(student["id"]):
        raise HTTPException(404, "Student not found")
    write_audit(
        user["id"],
        user["role_type"],
        "STUDENT_ARCHIVED",
        "student",
        student["id"],
        payload={"institution_id": institution_id},
        ip=_client_ip(request),
    )
    return {"ok": True, "student_id": student["id"], "archived": True}


@app.get("/api/admin/institution-archives")
async def list_archived_institution_students(
    institution_id: str | None = None, user: dict = Depends(require_auth)
):
    if user.get("role_type") != "admin":
        raise HTTPException(403, "Global administrator access required")
    from backend.database import get_db

    conn = get_db()
    clauses = ["s.archived_at IS NOT NULL", "s.deleted_at IS NULL"]
    params: list[Any] = []
    if institution_id:
        clauses.append("s.institution_id = ?")
        params.append(institution_id)
    rows = conn.execute(
        "SELECT s.id, s.institution_id, s.archived_at, s.created_at, s.is_minor, s.user_id, "
        "s.first_name_encrypted, s.email_encrypted, i.name AS institution_name, u.status AS account_status "
        "FROM students s LEFT JOIN institutions i ON i.id = s.institution_id "
        "LEFT JOIN users u ON u.id = s.user_id WHERE "
        + " AND ".join(clauses)
        + " ORDER BY s.archived_at DESC",
        params,
    ).fetchall()
    conn.close()
    return [
        {
            "id": row["id"],
            "institution_id": row["institution_id"],
            "institution_name": row["institution_name"],
            "archived_at": row["archived_at"],
            "is_minor": bool(row["is_minor"]),
            "account_status": row["account_status"],
            "name": decrypt_pii(row["first_name_encrypted"]),
            "email": decrypt_pii(row["email_encrypted"]),
        }
        for row in rows
    ]


@app.post("/api/admin/institution-archives/{student_id}/restore")
async def restore_archived_institution_student(
    student_id: str, data: dict, request: Request, user: dict = Depends(require_auth)
):
    if user.get("role_type") != "admin":
        raise HTTPException(403, "Global administrator access required")
    if data.get("confirmation") != "RESTORE":
        raise HTTPException(400, "confirmation must be RESTORE")
    from backend.database import get_db

    conn = get_db()
    row = conn.execute(
        "SELECT * FROM students WHERE id = ? AND archived_at IS NOT NULL AND deleted_at IS NULL",
        (student_id,),
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Archived student not found")
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE students SET archived_at = NULL, updated_at = ? WHERE id = ?",
        (now, student_id),
    )
    if row["user_id"]:
        conn.execute(
            "UPDATE users SET status = 'approved' WHERE id = ?", (row["user_id"],)
        )
    conn.commit()
    conn.close()
    write_audit(
        user["id"],
        "admin",
        "ARCHIVED_STUDENT_RESTORED",
        "student",
        student_id,
        ip=_client_ip(request),
    )
    return {"ok": True}


@app.post("/api/institution/students", status_code=201)
async def create_institution_student(
    data: dict, request: Request, user: dict = Depends(require_auth)
):
    """Manual intake using the same validation and consent dispatch as CSV."""
    institution_id = _require_institution_admin(user)
    fields = {
        "student_id": (data.get("student_id") or "").strip(),
        "student_first_name": (data.get("student_first_name") or "").strip(),
        "last_name": (data.get("last_name") or "").strip(),
        "student_email": (data.get("student_email") or "").strip().lower(),
        "date_of_birth": (data.get("date_of_birth") or "").strip(),
        "grade_level": (data.get("grade_level") or "").strip(),
        "parent_first_name": (data.get("parent_first_name") or "").strip(),
        "parent_email": (data.get("parent_email") or "").strip().lower(),
    }
    if not all(
        fields[key]
        for key in (
            "student_id",
            "student_first_name",
            "student_email",
            "date_of_birth",
        )
    ):
        raise HTTPException(
            400, "Student ID, first name, email, and date of birth are required"
        )
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", fields["student_email"]):
        raise HTTPException(400, "A valid student email is required")
    import csv as _csv
    import io as _io

    buffer = _io.StringIO()
    writer = _csv.DictWriter(buffer, fieldnames=list(fields))
    writer.writeheader()
    writer.writerow(fields)
    inst = get_institution_by_id(institution_id) or {}
    summary = upsert_roster(
        institution_id,
        buffer.getvalue().encode(),
        user["id"],
        minor_age_threshold=int(inst.get("minor_age_threshold") or 18),
    )
    if summary.get("parse_error") or summary.get("errors"):
        detail = summary.get("parse_error") or summary["errors"][0].get("error")
        raise HTTPException(400, detail)
    students = [
        s
        for s in (get_student_by_id(sid) for sid in summary.get("student_ids", []))
        if s
    ]
    dispatch = dispatch_consents_for_students(
        students, user["id"], ip=_client_ip(request)
    )
    write_audit(
        user["id"],
        user["role_type"],
        "STUDENT_MANUALLY_CREATED",
        "institution",
        institution_id,
        payload={"student_ids": summary.get("student_ids", [])},
        ip=_client_ip(request),
    )
    return {"roster": summary, "dispatch": dispatch}


@app.patch("/api/institution/students/{student_id}")
async def update_institution_student(
    student_id: str, data: dict, request: Request, user: dict = Depends(require_auth)
):
    institution_id = _require_institution_admin(user)
    student = get_student_by_id(student_id)
    if not student or student.get("institution_id") != institution_id:
        raise HTTPException(404, "Student not found")
    updates: dict[str, Any] = {}
    if "student_first_name" in data:
        name = (data.get("student_first_name") or "").strip()
        if not name:
            raise HTTPException(400, "Student first name cannot be blank")
        updates["first_name_encrypted"] = encrypt_pii(name)
    if "student_email" in data:
        email = (data.get("student_email") or "").strip().lower()
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            raise HTTPException(400, "Invalid student email")
        existing = get_user_by_email(email)
        if existing and existing.get("id") != student.get("user_id"):
            raise HTTPException(409, "This email already belongs to another account")
        updates["email_encrypted"] = encrypt_pii(email)
    if "grade_level" in data:
        updates["grade_level"] = (data.get("grade_level") or "").strip() or None
    if "parent_email" in data:
        email = (data.get("parent_email") or "").strip().lower()
        if email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            raise HTTPException(400, "Invalid parent email")
        updates["parent_email_encrypted"] = encrypt_pii(email) if email else None
    if "parent_first_name" in data:
        name = (data.get("parent_first_name") or "").strip()
        updates["parent_first_name_encrypted"] = encrypt_pii(name) if name else None
    updated = update_student(student_id, **updates)
    if student.get("user_id") and (
        "student_first_name" in data or "student_email" in data
    ):
        from backend.database import get_db

        conn = get_db()
        fields, params = [], []
        if "student_first_name" in data:
            fields.append("name = ?")
            params.append((data.get("student_first_name") or "").strip())
        if "student_email" in data:
            fields.append("email = ?")
            params.append((data.get("student_email") or "").strip().lower())
        params.append(student["user_id"])
        conn.execute(f"UPDATE users SET {', '.join(fields)} WHERE id = ?", params)
        conn.commit()
        conn.close()
    write_audit(
        user["id"],
        user["role_type"],
        "STUDENT_ROSTER_UPDATED",
        "student",
        student_id,
        payload={"fields": sorted(updates)},
        ip=_client_ip(request),
    )
    return {"student": updated}


@app.post("/api/institution/students/{student_id}/dispatch-consent")
async def dispatch_institution_student_consent(
    student_id: str, request: Request, user: dict = Depends(require_auth)
):
    institution_id = _require_institution_admin(user)
    student = get_student_by_id(student_id)
    if not student or student.get("institution_id") != institution_id:
        raise HTTPException(404, "Student not found")
    result = dispatch_consents_for_students(
        [student], user["id"], ip=_client_ip(request)
    )
    return result


@app.post("/api/institution/students/{student_id}/remind-consent")
async def remind_institution_student_consent(
    student_id: str, request: Request, user: dict = Depends(require_auth)
):
    institution_id = _require_institution_admin(user)
    student = get_student_by_id(student_id)
    if not student or student.get("institution_id") != institution_id:
        raise HTTPException(404, "Student not found")
    consent = (
        get_consent_by_id(student["current_consent_id"])
        if student.get("current_consent_id")
        else None
    )
    if not consent:
        raise HTTPException(
            400, "No consent request exists yet; send the initial request first"
        )
    try:
        result = remind_consent(
            consent["id"], actor_id=user["id"], ip=_client_ip(request)
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    write_audit(
        user["id"],
        user["role_type"],
        "INSTITUTION_CONSENT_REMINDER_SENT",
        "consent",
        consent["id"],
        ip=_client_ip(request),
    )
    return {
        "ok": True,
        "email_sent": result.get("email_sent", False),
        "email_error": result.get("email_error"),
    }


@app.post("/api/institution/students/{student_id}/continue-independently")
async def continue_student_independently(
    student_id: str, request: Request, user: dict = Depends(require_auth)
):
    institution_id = _require_institution_admin(user)
    student = get_student_by_id(student_id)
    if (
        not student
        or student.get("institution_id") != institution_id
        or student.get("is_minor")
    ):
        raise HTTPException(
            400, "Only an adult institution student can continue independently"
        )
    if not student.get("archived_at") or not student.get("user_id"):
        raise HTTPException(400, "Archive the student before enabling independent use")
    from backend.database import get_db

    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE counsellor_student_assignments SET active = 0, unassigned_at = ? WHERE student_id = ? AND active = 1",
        (now, student["user_id"]),
    )
    # Institutional consent cannot travel into personal use. Revoke it and
    # require the adult to make a fresh, personal decision after the exit.
    conn.execute(
        "UPDATE consents SET status = 'REVOKED', revoked_at = ?, updated_at = ? "
        "WHERE student_id = ? AND status IN ('ACCEPTED', 'PENDING', 'VIEWED', 'RENEWAL_DUE')",
        (now, now, student["user_id"]),
    )
    conn.execute(
        "UPDATE users SET institution_id = NULL, user_category = 'adult', onboarding_completed_at = NULL, status = 'approved' WHERE id = ?",
        (student["user_id"],),
    )
    conn.execute(
        "UPDATE students SET current_consent_id = NULL WHERE id = ?", (student_id,)
    )
    conn.commit()
    conn.close()
    write_audit(
        user["id"],
        user["role_type"],
        "STUDENT_CONTINUED_INDEPENDENTLY",
        "student",
        student_id,
        ip=_client_ip(request),
    )
    return {"ok": True, "requires_personal_onboarding": True}


@app.get("/api/institution/students/status")
async def institution_student_status(user: dict = Depends(require_auth)):
    institution_id = _require_institution_scope(user)
    if not institution_id:
        raise HTTPException(400, "An institution context is required")
    from backend.database import get_db

    conn = get_db()
    rows = conn.execute(
        "SELECT s.*, u.id AS account_id, u.name AS account_name, u.email AS account_email, "
        "u.status AS account_status, u.invitation_token_hash, a.counsellor_id, c.name AS counsellor_name "
        "FROM students s LEFT JOIN users u ON u.id = s.user_id "
        "LEFT JOIN counsellor_student_assignments a ON a.student_id = u.id AND a.active = 1 "
        "LEFT JOIN users c ON c.id = a.counsellor_id "
        "WHERE s.institution_id = ? AND s.deleted_at IS NULL AND s.archived_at IS NULL "
        "ORDER BY s.created_at DESC",
        (institution_id,),
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        consent = (
            get_consent_by_id(row["current_consent_id"])
            if row["current_consent_id"]
            else None
        )
        invitation_pending = bool(row["invitation_token_hash"])
        if not row["account_id"]:
            state = "imported"
        elif invitation_pending:
            state = "invitation_pending"
        elif row["is_minor"] and (not consent or consent.get("status") != "ACCEPTED"):
            state = "parent_consent_pending"
        elif not row["counsellor_id"]:
            state = "ready_for_assignment"
        else:
            state = "assigned"
        result.append(
            {
                "id": row["id"],
                "account_id": row["account_id"],
                "name": decrypt_pii(row["first_name_encrypted"]),
                "email": decrypt_pii(row["email_encrypted"]),
                "is_minor": bool(row["is_minor"]),
                "guardian_details_present": bool(row["parent_email_encrypted"]),
                "grade_level": row["grade_level"],
                "account_status": row["account_status"],
                "consent_status": consent.get("status") if consent else None,
                "consent_recipient": consent.get("recipient_role") if consent else None,
                "consent_recipient_email": consent.get("recipient_email")
                if consent
                else None,
                "consent_reminders_sent": int(consent.get("reminders_sent") or 0)
                if consent
                else 0,
                "consent_dispatched_at": consent.get("dispatched_at")
                if consent
                else None,
                "counsellor_id": row["counsellor_id"],
                "counsellor_name": row["counsellor_name"],
                "invitation_pending": invitation_pending,
                "access_status": "ready"
                if consent and consent.get("status") == "ACCEPTED"
                else (
                    "guardian_consent_pending"
                    if row["is_minor"]
                    else "student_consent_pending"
                ),
                "onboarding_state": state,
            }
        )
    return result


@app.get("/api/institution/student-home")
async def institution_student_home(user: dict = Depends(require_auth)):
    """Safe, student-facing status for an institution-managed account."""
    if user.get("role_type") != "student":
        raise HTTPException(403, "Student account required")
    student = get_student_by_user_id(user["id"])
    if not student or student.get("archived_at") or student.get("deleted_at"):
        raise HTTPException(404, "This account is not an active institution student")
    institution = get_institution_by_id(student["institution_id"]) or {}
    consent = (
        get_consent_by_id(student["current_consent_id"])
        if student.get("current_consent_id")
        else None
    )
    from backend.database import get_db

    conn = get_db()
    assignment = conn.execute(
        "SELECT c.name FROM counsellor_student_assignments a "
        "JOIN users c ON c.id = a.counsellor_id "
        "WHERE a.student_id = ? AND a.active = 1 LIMIT 1",
        (user["id"],),
    ).fetchone()
    conn.close()
    consent_accepted = bool(consent and consent.get("status") == "ACCEPTED")
    is_minor = bool(student.get("is_minor"))
    if consent_accepted:
        access_status = "ready"
    elif is_minor:
        access_status = "guardian_consent_pending"
    else:
        access_status = "student_consent_pending"
    return {
        "institution_name": institution.get("name") or "Your institution",
        "is_minor": is_minor,
        "consent_status": consent.get("status") if consent else None,
        "guardian_details_present": bool(student.get("parent_email_encrypted")),
        "access_status": access_status,
        "assigned_counsellor_name": assignment["name"] if assignment else None,
        "support_active": bool(consent_accepted and assignment),
    }


@app.post("/api/institution/students/{student_id}/resend-invite")
async def resend_student_invite(
    student_id: str, request: Request, user: dict = Depends(require_auth)
):
    institution_id = _require_institution_admin(user)
    student = get_student_by_id(student_id)
    if (
        not student
        or student.get("institution_id") != institution_id
        or not student.get("user_id")
    ):
        raise HTTPException(404, "Student account not found")
    account = get_user_by_id(student["user_id"])
    if not account or account.get("password_hash"):
        raise HTTPException(400, "Student has already activated an account")
    token_value = secrets.token_urlsafe(32)
    set_user_invitation(
        account["id"],
        hash_token(token_value),
        (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
    )
    institution = get_institution_by_id(institution_id) or {}
    base = (
        os.getenv("APP_BASE_URL")
        or os.getenv("FRONTEND_URL")
        or "http://localhost:5173"
    ).rstrip("/")
    invite_url = f"{base}/invite?token={token_value}"
    send_html_email(
        account["email"],
        "Complete your MindGuard student account",
        f'<p>You have been invited to {institution.get("name") or "MindGuard"}.</p><p><a href="{invite_url}">Activate your account</a></p>',
        related_type="student_invitation",
        related_id=account["id"],
        metadata={"institution_id": institution_id, "resent": True},
    )
    write_audit(
        user["id"],
        user["role_type"],
        "STUDENT_INVITE_RESENT",
        "user",
        account["id"],
        payload={"institution_id": institution_id},
        ip=_client_ip(request),
    )
    return {"ok": True}


@app.post("/api/institution/retention/run")
async def run_institution_retention(
    request: Request, user: dict = Depends(require_auth)
):
    institution_id = _require_institution_admin(user)
    if not institution_id:
        raise HTTPException(400, "An institution context is required")
    result = await asyncio.to_thread(run_retention_cleanup, institution_id)
    write_audit(
        user["id"],
        user["role_type"],
        "RETENTION_CLEANUP_RUN",
        "institution",
        institution_id,
        payload=result,
        ip=_client_ip(request),
    )
    return result


@app.post("/api/institution/staff", status_code=201)
async def invite_institution_staff(
    data: dict, request: Request, user: dict = Depends(require_auth)
):
    institution_id = _require_institution_admin(user, data.get("institution_id"))
    if not institution_id:
        raise HTTPException(400, "An institution context is required")
    role_type = (data.get("role_type") or "counsellor").strip().lower()
    if role_type not in ("counsellor", "school_admin"):
        raise HTTPException(400, "role_type must be counsellor or school_admin")
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    if not name or not email or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise HTTPException(400, "A valid name and email are required")
    existing = get_user_by_email(email)
    if existing:
        raise HTTPException(409, "A user with this email already exists")
    placeholder_hash = hash_password(secrets.token_urlsafe(32))
    staff = create_user(
        email,
        name,
        placeholder_hash,
        role_type=role_type,
        institution_id=institution_id,
    )
    from backend.services.crypto import hash_token

    token = secrets.token_urlsafe(32)
    set_user_invitation(
        staff["id"],
        hash_token(token),
        (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
    )
    institution = get_institution_by_id(institution_id) or {}
    base = os.getenv("APP_BASE_URL", "https://app.mindguardai.me").rstrip("/")
    invite_url = f"{base}/invite?token={token}"
    context = {
        "counsellor_name": name,
        "staff_role": role_type,
        "institution_name": institution.get("name") or "MindGuard",
        "invite_url": invite_url,
        "setup_url": invite_url,
        "support_email": os.getenv("DEMO_NOTIFY_EMAIL", "support@mindguard.ai"),
        "withdraw_url": f"{base}/privacy",
        "privacy_url": f"{base}/privacy",
        "contact_url": f"{base}/contact",
    }
    subject, body = counsellor_invitation_notification(context)
    email_sent, email_error = send_html_email(
        email,
        subject,
        body,
        related_type="institution_staff_invitation",
        related_id=staff["id"],
        metadata={"role_type": role_type, "institution_id": institution_id},
    )
    write_audit(
        user["id"],
        user["role_type"],
        "INSTITUTION_STAFF_INVITED",
        "user",
        staff["id"],
        payload={
            "role_type": role_type,
            "institution_id": institution_id,
            "email_sent": email_sent,
        },
        ip=_client_ip(request),
    )
    return {
        "staff": {
            **staff,
            "status": "pending",
            "institution_id": institution_id,
            "role_type": role_type,
        },
        "email_sent": email_sent,
        "email_error": email_error or None,
    }


@app.patch("/api/institution/staff/{staff_id}")
async def update_institution_staff(
    staff_id: str, data: dict, request: Request, user: dict = Depends(require_auth)
):
    institution_id = _require_institution_admin(user)
    if not institution_id:
        raise HTTPException(400, "An institution context is required")
    staff = get_user_by_id(staff_id)
    if (
        not staff
        or staff.get("institution_id") != institution_id
        or staff.get("role_type") not in ("counsellor", "school_admin")
    ):
        raise HTTPException(404, "Staff member not found")
    new_status = data.get("status", staff.get("status"))
    if new_status not in ("approved", "suspended", "revoked", "pending", "invited"):
        raise HTTPException(400, "Invalid staff status")
    if "max_caseload" in data:
        maximum = data.get("max_caseload")
        if maximum is not None and (
            not isinstance(maximum, int) or maximum < 1 or maximum > 1000
        ):
            raise HTTPException(
                400, "max_caseload must be a whole number from 1 to 1000"
            )
        if staff.get("role_type") != "counsellor":
            raise HTTPException(400, "Only counsellors can have a caseload limit")
        from backend.database import get_db

        conn = get_db()
        conn.execute(
            "UPDATE users SET max_caseload = ? WHERE id = ?", (maximum, staff_id)
        )
        conn.commit()
        conn.close()
    update_user_status(staff_id, new_status)
    if new_status in ("suspended", "revoked"):
        from backend.database import get_db

        conn = get_db()
        assignments = conn.execute(
            "SELECT id FROM counsellor_student_assignments WHERE counsellor_id = ? AND active = 1",
            (staff_id,),
        ).fetchall()
        conn.close()
        for assignment in assignments:
            unassign_student_from_counsellor(assignment["id"])
    updated = get_user_by_id(staff_id)
    write_audit(
        user["id"],
        user["role_type"],
        "INSTITUTION_STAFF_STATUS_CHANGED",
        "user",
        staff_id,
        payload={"status": new_status, "institution_id": institution_id},
        ip=_client_ip(request),
    )
    return updated


@app.post("/api/institution/staff/{staff_id}/resend-invite")
async def resend_institution_staff_invite(
    staff_id: str, request: Request, user: dict = Depends(require_auth)
):
    institution_id = _require_institution_admin(user)
    staff = get_user_by_id(staff_id)
    if (
        not staff
        or staff.get("institution_id") != institution_id
        or staff.get("role_type") not in ("counsellor", "school_admin")
    ):
        raise HTTPException(404, "Staff member not found")
    if staff.get("status") == "approved" and not staff.get("invitation_token_hash"):
        raise HTTPException(400, "Staff member has already activated their account")
    token = secrets.token_urlsafe(32)
    set_user_invitation(
        staff_id,
        hash_token(token),
        (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
    )
    email_sent, email_error = _staff_invitation_email(staff, token, institution_id)
    write_audit(
        user["id"],
        user["role_type"],
        "INSTITUTION_STAFF_INVITE_RESENT",
        "user",
        staff_id,
        payload={"institution_id": institution_id, "email_sent": email_sent},
        ip=_client_ip(request),
    )
    return {"ok": True, "email_sent": email_sent, "email_error": email_error or None}


# ── Consent maintenance (manual trigger) ──────────────────────────────


@app.post("/api/v1/admin/consents/run-maintenance")
async def v1_admin_run_consent_maintenance(user: dict = Depends(require_auth)):
    require_permission(user, PERM_CONSENT_MANAGE)
    expired = process_expired_consents()
    reminders = process_consent_reminders()
    return {"expired": expired, "reminders": reminders}


# ── Demo request pipeline (Delivery Brief §6) ─────────────────────────


@app.post("/api/v1/demo-requests", status_code=201)
async def v1_demo_request_create(data: DemoRequestCreate, request: Request):
    client_ip = _client_ip(request)

    # Honeypot (Brief §5.5/§13.2): bots fill the hidden field — silently
    # "succeed" without creating a row so scrapers can't learn the rule.
    if data.website:
        logger.info("demo-request honeypot tripped from %s", client_ip)
        return {"id": "", "status": "new", "warning": None}

    if not await verify_recaptcha_token(data.recaptcha_token):
        raise HTTPException(400, "Unable to verify you're human. Please try again.")

    _check_rate_limit(f"demo:{client_ip}", max_requests=5, window=3600)
    if not data.consent_to_contact:
        raise HTTPException(
            400, "Consent to contact is required to submit a demo request"
        )
    try:
        demo = create_demo_request(
            full_name=data.full_name.strip(),
            work_email=data.work_email.strip().lower(),
            organisation=data.organisation.strip(),
            organisation_type=data.organisation_type,
            role_title=data.role_title,
            country=data.country,
            student_count_range=data.student_count_range,
            message=data.message,
            heard_about_us=data.heard_about_us,
            consent_to_contact=data.consent_to_contact,
        )
    except Exception as exc:
        logger.error("demo_request_create error: %s", exc)
        raise HTTPException(500, "Failed to submit demo request")

    ctx = demo_email_context(demo)
    ok, err = send_html_email(
        data.work_email.strip().lower(),
        *demo_request_confirmation(ctx),
        related_type="demo_request",
        related_id=demo["id"],
        metadata={"event": "confirmation"},
    )
    if not ok:
        logger.warning(
            "demo confirmation email failed for %s: %s", data.work_email, err
        )

    notify_to = DEMO_NOTIFY_EMAIL.strip()
    if notify_to:
        ok, err = send_html_email(
            notify_to,
            *demo_request_notification(ctx),
            related_type="demo_request",
            related_id=demo["id"],
            metadata={"event": "notification"},
        )
        if not ok:
            logger.warning("demo notification email failed to %s: %s", notify_to, err)

    write_audit(
        None,
        "public",
        "DEMO_REQUEST_CREATED",
        "demo_request",
        demo["id"],
        ip=client_ip,
    )

    def _composio_demo_fastlane():
        try:
            from backend.services.composio_fastlane import trigger_demo_fastlane

            trigger_demo_fastlane(demo)
        except Exception as e:
            logger.warning("composio demo fastlane failed for %s: %s", demo["id"], e)

    try:
        import asyncio as _asyncio

        try:
            _asyncio.get_running_loop().create_task(
                _asyncio.to_thread(_composio_demo_fastlane)
            )
        except RuntimeError:
            _composio_demo_fastlane()
    except Exception:
        pass

    return {
        "id": demo["id"],
        "status": demo["status"],
        "warning": work_email_warning(data.work_email, data.organisation_type),
    }


def _demo_calendar_url(demo: dict) -> str:
    start = datetime.fromisoformat(demo["meeting_at"].replace("Z", "+00:00"))
    end = start + timedelta(minutes=30)
    dates = f"{start.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}/{end.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    details = f"MindGuard institution onboarding meeting. Join: {demo.get('meeting_url') or ''}"
    return "https://calendar.google.com/calendar/render?" + urlencode(
        {
            "action": "TEMPLATE",
            "text": f"MindGuard onboarding — {demo.get('organisation') or 'Institution'}",
            "dates": dates,
            "details": details,
            "location": demo.get("meeting_url") or "",
        }
    )


@app.post("/api/v1/admin/demo-requests/{demo_request_id}/schedule")
async def v1_admin_schedule_demo(
    demo_request_id: str,
    data: dict,
    request: Request,
    user: dict = Depends(require_auth),
):
    if user.get("role_type") != "admin":
        raise HTTPException(403, "Only global admins can schedule demos")
    demo = get_demo_request(demo_request_id)
    if not demo:
        raise HTTPException(404, "Demo request not found")
    meeting_at = (data.get("meeting_at") or "").strip()
    meeting_url = (data.get("meeting_url") or "").strip()
    if not meeting_at or not meeting_url:
        raise HTTPException(400, "Meeting date and meeting link are required")
    try:
        datetime.fromisoformat(meeting_at.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(400, "meeting_at must be a valid ISO date")

    from backend.services.crypto import hash_token

    response_token = secrets.token_urlsafe(32)
    updated = update_demo_request(
        demo_request_id,
        status="demo_scheduled",
        meeting_at=meeting_at,
        meeting_url=meeting_url,
        meeting_response="PENDING",
        meeting_response_token_hash=hash_token(response_token),
        meeting_response_note=None,
    )
    updated = updated or demo
    public_base = os.getenv("PUBLIC_SITE_URL", "https://mindguardai.me").rstrip("/")
    accept_url = f"{public_base}/demo/respond?token={response_token}&action=accept"
    reschedule_url = (
        f"{public_base}/demo/respond?token={response_token}&action=reschedule"
    )
    calendar_url = _demo_calendar_url(updated)
    recipient = html_lib.escape(updated.get("work_email") or "")
    name = html_lib.escape(updated.get("full_name") or "there")
    organisation = html_lib.escape(updated.get("organisation") or "MindGuard")
    body = f"""
    <p>Hello {name},</p>
    <p>Your MindGuard onboarding meeting for <strong>{organisation}</strong> has been proposed.</p>
    <p><strong>When:</strong> {html_lib.escape(meeting_at)}<br><strong>Join:</strong> <a href="{html_lib.escape(meeting_url)}">{html_lib.escape(meeting_url)}</a></p>
    <p><a href="{html_lib.escape(calendar_url)}">Add to Google Calendar</a></p>
    <p><a href="{html_lib.escape(accept_url)}">Accept this time</a> &nbsp; | &nbsp; <a href="{html_lib.escape(reschedule_url)}">Request a different time</a></p>
    <p>If you request a change, our team will contact you to agree another slot.</p>
    """
    email_sent, email_error = send_html_email(
        recipient,
        "MindGuard onboarding meeting invitation",
        body,
        related_type="demo_meeting_invitation",
        related_id=demo_request_id,
        metadata={"meeting_at": meeting_at, "meeting_url": meeting_url},
    )
    write_audit(
        user["id"],
        user["role_type"],
        "DEMO_MEETING_SCHEDULED",
        "demo_request",
        demo_request_id,
        payload={"meeting_at": meeting_at, "email_sent": email_sent},
        ip=_client_ip(request),
    )
    return {
        "demo_request": updated,
        "calendar_url": calendar_url,
        "email_sent": email_sent,
        "email_error": email_error or None,
    }


@app.get("/api/v1/demo-requests/respond")
async def demo_meeting_response_details(token: str):
    from backend.services.crypto import hash_token

    demo = get_demo_request_by_response_token(hash_token(token))
    if not demo:
        raise HTTPException(404, "This meeting invitation is no longer valid")
    return {
        "full_name": demo.get("full_name"),
        "organisation": demo.get("organisation"),
        "meeting_at": demo.get("meeting_at"),
        "meeting_url": demo.get("meeting_url"),
        "meeting_response": demo.get("meeting_response"),
    }


@app.post("/api/v1/demo-requests/respond")
async def respond_to_demo_meeting(token: str, data: dict, request: Request):
    from backend.services.crypto import hash_token

    demo = get_demo_request_by_response_token(hash_token(token))
    if not demo:
        raise HTTPException(404, "This meeting invitation is no longer valid")
    action = (data.get("action") or "").strip().lower()
    if action not in ("accept", "reschedule"):
        raise HTTPException(400, "action must be accept or reschedule")
    response = "ACCEPTED" if action == "accept" else "RESCHEDULE_REQUESTED"
    note = (data.get("note") or "").strip()[:2000] or None
    updated = update_demo_request(
        demo["id"],
        meeting_response=response,
        meeting_response_note=note,
    )
    write_audit(
        None,
        "public",
        "DEMO_MEETING_RESPONSE",
        "demo_request",
        demo["id"],
        payload={"response": response, "has_note": bool(note)},
        ip=_client_ip(request),
    )
    if response == "RESCHEDULE_REQUESTED" and DEMO_NOTIFY_EMAIL:
        send_html_email(
            DEMO_NOTIFY_EMAIL,
            "MindGuard demo reschedule requested",
            f"The requester for {html_lib.escape(demo.get('organisation') or 'an institution')} requested a new meeting time.<br><br>{html_lib.escape(note or 'No reason provided.')}",
            related_type="demo_meeting_reschedule",
            related_id=demo["id"],
        )
    return {"ok": True, "meeting_response": response, "demo_request": updated}


@app.get("/api/v1/admin/demo-requests")
async def v1_admin_list_demo_requests(
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    user: dict = Depends(require_auth),
):
    require_permission(user, PERM_DEMO_MANAGE)
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    rows = list_demo_requests(status=status, limit=limit, offset=offset)
    return {"demo_requests": rows, "total": len(rows)}


@app.patch("/api/v1/admin/demo-requests/{demo_request_id}")
async def v1_admin_update_demo_request(
    demo_request_id: str,
    data: DemoRequestUpdate,
    request: Request,
    user: dict = Depends(require_auth),
):
    require_permission(user, PERM_DEMO_MANAGE)
    existing = get_demo_request(demo_request_id)
    if not existing:
        raise HTTPException(404, "Demo request not found")
    updated = update_demo_request(
        demo_request_id, **data.model_dump(exclude_unset=True)
    )
    write_audit(
        user["id"],
        user["role_type"],
        "DEMO_REQUEST_UPDATED",
        "demo_request",
        demo_request_id,
        payload={k: v for k, v in data.model_dump(exclude_unset=True).items()},
        ip=_client_ip(request),
    )
    return updated


@app.post("/api/v1/admin/demo-requests/{demo_request_id}/convert", status_code=201)
async def v1_admin_convert_demo_request(
    demo_request_id: str,
    request: Request,
    user: dict = Depends(require_auth),
):
    """Convert a qualified lead into a provisioned institution and school-admin invite."""
    if user.get("role_type") != "admin":
        raise HTTPException(403, "Only global admins can provision institutions")
    demo = get_demo_request(demo_request_id)
    if not demo:
        raise HTTPException(404, "Demo request not found")
    if demo.get("institution_id"):
        raise HTTPException(
            409, "This demo request is already linked to an institution"
        )
    requester_email = (demo.get("work_email") or "").strip().lower()
    existing = get_user_by_email(requester_email) if requester_email else None
    if existing:
        raise HTTPException(
            409, "The requester email already belongs to an account; provision manually"
        )

    institution = create_institution(
        demo.get("organisation") or "New MindGuard institution",
        demo.get("organisation_type") or "other",
        created_by=user["id"],
    )
    staff = create_user(
        requester_email,
        demo.get("full_name") or "Institution administrator",
        hash_password(secrets.token_urlsafe(32)),
        role_type="school_admin",
        institution_id=institution["id"],
    )
    from backend.services.crypto import hash_token

    token = secrets.token_urlsafe(32)
    set_user_invitation(
        staff["id"],
        hash_token(token),
        (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
    )
    base = os.getenv("APP_BASE_URL", "https://app.mindguardai.me").rstrip("/")
    invite_url = f"{base}/invite?token={token}"
    context = {
        "counsellor_name": staff["name"],
        "staff_role": "school_admin",
        "institution_name": institution["name"],
        "invite_url": invite_url,
        "setup_url": invite_url,
        "support_email": os.getenv("DEMO_NOTIFY_EMAIL", "support@mindguard.ai"),
        "withdraw_url": f"{base}/privacy",
        "privacy_url": f"{base}/privacy",
        "contact_url": f"{base}/contact",
    }
    subject, body = counsellor_invitation_notification(context)
    email_sent, email_error = send_html_email(
        requester_email,
        subject,
        body,
        related_type="institution_admin_invitation",
        related_id=staff["id"],
        metadata={
            "institution_id": institution["id"],
            "demo_request_id": demo_request_id,
        },
    )
    converted_at = datetime.now(timezone.utc).isoformat()
    updated = update_demo_request(
        demo_request_id,
        status="institution_provisioning",
        institution_id=institution["id"],
        converted_by=user["id"],
        converted_at=converted_at,
    )
    write_audit(
        user["id"],
        user["role_type"],
        "DEMO_REQUEST_CONVERTED",
        "demo_request",
        demo_request_id,
        payload={
            "institution_id": institution["id"],
            "staff_id": staff["id"],
            "email_sent": email_sent,
        },
        ip=_client_ip(request),
    )
    write_audit(
        user["id"],
        user["role_type"],
        "INSTITUTION_PROVISIONED_FROM_DEMO",
        "institution",
        institution["id"],
        payload={"demo_request_id": demo_request_id, "staff_id": staff["id"]},
        ip=_client_ip(request),
    )
    return {
        "demo_request": updated,
        "institution": institution,
        "staff": {
            "id": staff["id"],
            "email": staff["email"],
            "name": staff["name"],
            "role_type": staff["role_type"],
        },
        "email_sent": email_sent,
        "email_error": email_error or None,
    }


@app.get("/api/v1/admin/audit")
async def v1_admin_audit_log(
    action: str | None = None,
    limit: int = 100,
    user: dict = Depends(require_auth),
):
    require_permission(user, PERM_AUDIT_VIEW)
    limit = max(1, min(limit, 1000))
    entries = get_all_audit_log(limit=limit, action=action)
    return {"entries": entries, "total": len(entries)}


# ── ESP webhooks (Delivery Brief §6/§9.4) ─────────────────────────────


@app.post("/webhooks/email/resend")
async def v1_resend_webhook(request: Request):
    """Resend (Svix-format) webhook: signature-verified, idempotent delivery events.

    Records bounces/complaints/deliveries into ``email_events`` so the consent
    tracker and demo-request panel can surface the latest delivery outcome.
    """
    raw = (await request.body()).decode("utf-8", errors="replace")
    try:
        summary = handle_webhook(
            raw,
            dict(request.headers),
            RESEND_WEBHOOK_SECRET,
            WEBHOOK_TOLERANCE_SECONDS,
        )
    except ValueError:
        raise HTTPException(401, "Invalid webhook signature")
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON body")
    return summary


# ── Rolling risk trigger ──────────────────────────────────────────────


@app.post(
    "/api/v1/students/{student_id}/analyze",
    responses={
        200: {"description": "Rolling risk computed and persisted"},
        403: {
            "description": "Analysis is consent-gated: no active (accepted, non-expired) consent on record"
        },
        404: {"description": "Student not found"},
        503: {"description": "Analysis service temporarily unavailable"},
    },
)
async def v1_student_analyze(
    student_id: str,
    data: dict,
    request: Request,
    user: dict = Depends(require_auth),
):
    _check_analysis_rate_limit(user["id"])
    student = get_user_by_id(student_id)
    if not student or student["role_type"] != "student":
        raise HTTPException(404, "Student not found")
    _require_counsellor_student_access(user, student_id)
    requested_platform = (data.get("platform") or "").strip()
    if not requested_platform:
        raise HTTPException(
            400,
            "platform is required and must be a verified account claimed by this student.",
        )
    from backend.services.platform_registry import normalize_platform

    requested_platform = (
        normalize_platform(requested_platform) or requested_platform.lower()
    )
    account = get_social_account(student_id, requested_platform)
    if not account:
        raise HTTPException(403, "The student has not claimed this social account.")
    if account.get("verification_status") != "verified":
        raise HTTPException(
            403,
            "This account is not ownership-verified. Ask the student to complete account verification before analysis.",
        )
    # The client must not be able to switch the analysis target by supplying a
    # different handle. The target is always the student's verified account.
    data["platform"] = requested_platform
    if requested_platform or data.get("platforms"):
        from backend.services.consent_gate import get_active_consent

        consent = get_active_consent(student_id)
        if consent:
            try:
                import json as _json

                consented = set(_json.loads(consent.get("platforms_json") or "[]"))
            except Exception:
                consented = set()
            if requested_platform and requested_platform not in consented:
                raise HTTPException(
                    400,
                    f"Platform {requested_platform} not in consented platforms: {', '.join(sorted(consented)) if consented else 'none'}",
                )
            if data.get("platforms"):
                req_set = set(
                    data.get("platforms")
                    if isinstance(data.get("platforms"), list)
                    else []
                )
                extra = req_set - consented
                if extra:
                    raise HTTPException(
                        400, f"Invalid platforms: {', '.join(sorted(extra))}"
                    )

    try:
        result = run_consented_student_analysis(
            student_id=student_id,
            posts=data.get("posts"),
            platform=requested_platform,
            actor=user,
            ip=_client_ip(request),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise inference_http_error(exc)

    try:
        sess = create_analysis_session(
            student_id=student_id,
            counsellor_id=user["id"],
            institution_id=student.get("institution_id") or user.get("institution_id"),
            consent_id=result.get("risk_record", {}).get("consent_id")
            if isinstance(result.get("risk_record"), dict)
            else None,
            analysis_type="counsellor_student",
            platforms=[requested_platform],
            findings={"posts": data.get("posts"), "result": result},
            risk_score=result.get("rolling_score"),
            insights=f"Rolling risk {result.get('rolling_score'):.2f} on {data.get('platform')}"
            if result.get("rolling_score") is not None
            else None,
        )
        result["session_id"] = sess["id"]
    except Exception as e:
        logger.warning("analysis session persist failed: %s", e)

    return result


# ═════════════════════════════════════════════════════════════════════
# Group routes (counsellor-only)
# ═════════════════════════════════════════════════════════════════════


@app.get("/api/v1/groups")
async def v1_list_groups(user: dict = Depends(require_auth)):
    if user["role_type"] not in ("counsellor", "admin"):
        raise HTTPException(403, "Counsellor or admin access required")
    groups = get_groups_for_user(user["id"])
    result = []
    for g in groups:
        unread = get_group_unread_count(g["id"], user["id"])
        result.append(
            {
                "id": g["id"],
                "name": g["name"],
                "description": g["description"],
                "avatar_url": g["avatar_url"],
                "created_by": g["created_by"],
                "is_active": bool(g["is_active"]),
                "member_count": g["member_count"],
                "unread_count": unread,
                "created_at": g["created_at"],
                "updated_at": g["updated_at"],
            }
        )
    return {"groups": result, "total": len(result)}


@app.post("/api/v1/groups", status_code=201)
async def v1_create_group(req: CreateGroupRequest, user: dict = Depends(require_auth)):
    if user["role_type"] not in ("counsellor", "admin"):
        raise HTTPException(403, "Counsellor or admin access required")
    try:
        group = create_group(req.name, req.description, user["id"])
        add_group_member(group["id"], user["id"], role="admin")
        for mid in req.member_ids:
            member_user = get_user_by_id(mid)
            if member_user and member_user["role_type"] == "student":
                if user["role_type"] != "admin":
                    _require_counsellor_student_access(user, mid)
                add_group_member(group["id"], mid, role="member")
                _safe_notify(
                    mid,
                    "Group Invitation",
                    f"You have been added to the group '{req.name}' by {user['name']}.",
                    "system",
                )
        members = get_group_members(group["id"])
        return {
            **group,
            "is_active": True,
            "member_count": len(members),
            "members": [
                {
                    "id": m["id"],
                    "user_id": m["user_id"],
                    "name": m["name"],
                    "email": m["email"],
                    "role": m["role"],
                    "joined_at": m["joined_at"],
                }
                for m in members
            ],
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("create_group error: %s", exc)
        raise HTTPException(500, "Failed to create group")


@app.get("/api/v1/groups/{group_id}")
async def v1_get_group(group_id: str, user: dict = Depends(require_auth)):
    if user["role_type"] not in ("counsellor", "admin"):
        raise HTTPException(403, "Counsellor or admin access required")
    group = get_group_by_id(group_id)
    if not group:
        raise HTTPException(404, "Group not found")
    if not is_group_member(group_id, user["id"]):
        raise HTTPException(403, "You are not a member of this group")
    members = get_group_members(group_id)
    return {
        **group,
        "is_active": bool(group["is_active"]),
        "member_count": len(members),
        "members": [
            {
                "id": m["id"],
                "user_id": m["user_id"],
                "name": m["name"],
                "email": m["email"],
                "role": m["role"],
                "joined_at": m["joined_at"],
            }
            for m in members
        ],
    }


@app.patch("/api/v1/groups/{group_id}")
async def v1_update_group(
    group_id: str, req: UpdateGroupRequest, user: dict = Depends(require_auth)
):
    if user["role_type"] not in ("counsellor", "admin"):
        raise HTTPException(403, "Counsellor or admin access required")
    group = get_group_by_id(group_id)
    if not group:
        raise HTTPException(404, "Group not found")
    if group["created_by"] != user["id"] and user["role_type"] != "admin":
        raise HTTPException(403, "Only the group creator can update this group")
    updated = update_group(group_id, name=req.name, description=req.description)
    if not updated:
        raise HTTPException(404, "Group not found")
    return {**updated, "is_active": bool(updated["is_active"])}


@app.delete("/api/v1/groups/{group_id}")
async def v1_delete_group(group_id: str, user: dict = Depends(require_auth)):
    if user["role_type"] not in ("counsellor", "admin"):
        raise HTTPException(403, "Counsellor or admin access required")
    group = get_group_by_id(group_id)
    if not group:
        raise HTTPException(404, "Group not found")
    if group["created_by"] != user["id"] and user["role_type"] != "admin":
        raise HTTPException(403, "Only the group creator can delete this group")
    ok = delete_group(group_id)
    if not ok:
        raise HTTPException(404, "Group not found")
    return {"ok": True}


@app.post("/api/v1/groups/{group_id}/members", status_code=201)
async def v1_add_group_members(
    group_id: str, data: dict, user: dict = Depends(require_auth)
):
    if user["role_type"] not in ("counsellor", "admin"):
        raise HTTPException(403, "Counsellor or admin access required")
    group = get_group_by_id(group_id)
    if not group:
        raise HTTPException(404, "Group not found")
    if not is_group_member(group_id, user["id"]):
        raise HTTPException(403, "You are not a member of this group")
    user_ids = data.get("user_ids", [])
    if not isinstance(user_ids, list) or not user_ids:
        raise HTTPException(400, "user_ids must be a non-empty list")
    added = []
    for uid in user_ids:
        member_user = get_user_by_id(uid)
        if member_user and member_user["role_type"] == "student":
            if user["role_type"] != "admin":
                _require_counsellor_student_access(user, uid)
            result = add_group_member(group_id, uid, role="member")
            if result:
                added.append(result)
                _safe_notify(
                    uid,
                    "Group Invitation",
                    f"You have been added to the group '{group['name']}' by {user['name']}.",
                    "system",
                )
    return {"added": len(added), "members": added}


@app.delete("/api/v1/groups/{group_id}/members/{user_id}")
async def v1_remove_group_member(
    group_id: str, user_id: str, user: dict = Depends(require_auth)
):
    if user["role_type"] not in ("counsellor", "admin"):
        raise HTTPException(403, "Counsellor or admin access required")
    group = get_group_by_id(group_id)
    if not group:
        raise HTTPException(404, "Group not found")
    if not is_group_member(group_id, user["id"]) and user["role_type"] != "admin":
        raise HTTPException(403, "You are not a member of this group")
    if user_id == group["created_by"] and user["role_type"] != "admin":
        raise HTTPException(400, "Cannot remove the group creator")
    ok = remove_group_member(group_id, user_id)
    if not ok:
        raise HTTPException(404, "Member not found")
    return {"ok": True}


@app.get("/api/v1/groups/{group_id}/messages")
async def v1_get_group_messages(
    group_id: str,
    limit: int = 50,
    before_id: str | None = None,
    user: dict = Depends(require_auth),
):
    group = get_group_by_id(group_id)
    if not group:
        raise HTTPException(404, "Group not found")
    if not is_group_member(group_id, user["id"]):
        raise HTTPException(403, "You are not a member of this group")
    messages = get_group_messages(group_id, limit=limit, before_id=before_id)
    return {"messages": messages, "total": len(messages)}


@app.post("/api/v1/groups/{group_id}/messages", status_code=201)
async def v1_send_group_message(
    group_id: str,
    req: GroupMessageRequest,
    request: Request,
    user: dict = Depends(require_auth),
):
    group = get_group_by_id(group_id)
    if not group:
        raise HTTPException(404, "Group not found")
    if not is_group_member(group_id, user["id"]):
        raise HTTPException(403, "You are not a member of this group")
    msg = send_group_message(group_id, user["id"], req.message)
    # Notify other group members
    members = get_group_members(group_id)
    for m in members:
        if m["user_id"] != user["id"] and should_notify(
            m["user_id"], "group_message", group_id
        ):
            _safe_notify(
                m["user_id"],
                f"Group: {group['name']}",
                f"{user['name']}: {req.message[:120]}{'...' if len(req.message) > 120 else ''}",
                "group_message",
            )
    msg["sender_name"] = user["name"]
    return msg


@app.post("/api/v1/groups/{group_id}/read")
async def v1_mark_group_read(group_id: str, user: dict = Depends(require_auth)):
    if not is_group_member(group_id, user["id"]):
        raise HTTPException(403, "You are not a member of this group")
    mark_all_group_messages_read(group_id, user["id"])
    return {"ok": True}


# ═════════════════════════════════════════════════════════════════════
# General messaging routes (any authenticated user)
# ═════════════════════════════════════════════════════════════════════


@app.get("/api/messages/conversations")
async def get_my_conversations(user: dict = Depends(require_auth)):
    conversations = get_conversations(user["id"])
    if user.get("role_type") != "admin":
        conversations = [
            c for c in conversations if _communication_allowed(user, c["other_id"])
        ]
    # Also fetch group previews
    groups = get_groups_for_user(user["id"])
    group_previews = []
    for g in groups:
        msgs = get_group_messages(g["id"], limit=1)
        last_msg = msgs[-1] if msgs else None
        unread = get_group_unread_count(g["id"], user["id"])
        group_previews.append(
            {
                "type": "group",
                "group_id": g["id"],
                "name": g["name"],
                "avatar_url": g.get("avatar_url", ""),
                "member_count": g["member_count"],
                "last_message": last_msg["message"] if last_msg else "",
                "last_time": last_msg["created_at"] if last_msg else "",
                "last_sender": last_msg["sender_name"] if last_msg else "",
                "unread": unread,
            }
        )
    return {"direct": conversations, "groups": group_previews}


@app.post("/api/messages/send")
async def send_message_any(
    data: dict, request: Request, user: dict = Depends(require_auth)
):
    receiver_id = data.get("receiver_id")
    message = data.get("message", "").strip()
    if not receiver_id:
        raise HTTPException(400, "Receiver ID required")
    if not message:
        raise HTTPException(400, "Message cannot be empty")
    _require_user_communication_access(user, receiver_id)
    msg = send_message(user["id"], receiver_id, message)
    if should_notify(receiver_id, "message"):
        _safe_notify(
            receiver_id, "New Message", f"New message from {user['name']}", "message"
        )
    write_audit(
        user["id"],
        user["role_type"],
        "MESSAGE_SENT",
        "communication",
        msg["id"],
        payload={"receiver_id": receiver_id},
        ip=_client_ip(request),
    )
    return msg


@app.get("/api/messages/conversations/{other_id}")
async def get_conversation_any(other_id: str, user: dict = Depends(require_auth)):
    _require_user_communication_access(user, other_id)
    mark_all_read(user["id"], other_id)
    return get_conversation(user["id"], other_id)


@app.post("/api/messages/read")
async def mark_message_read(data: dict, user: dict = Depends(require_auth)):
    message_id = data.get("message_id")
    if message_id:
        if not mark_read(message_id, user["id"]):
            raise HTTPException(404, "Message not found")
    return {"ok": True}


@app.post("/api/messages/read-all/{other_id}")
async def mark_all_read_with(other_id: str, user: dict = Depends(require_auth)):
    _require_user_communication_access(user, other_id)
    mark_all_read(user["id"], other_id)
    return {"ok": True}


# ═════════════════════════════════════════════════════════════════════
# Notification preference routes
# ═════════════════════════════════════════════════════════════════════


@app.get("/api/notifications/preferences")
async def get_my_notification_preferences(user: dict = Depends(require_auth)):
    prefs = get_notification_preferences(user["id"])
    return {"preferences": prefs}


@app.put("/api/notifications/preferences/mute-group")
async def toggle_group_mute(req: MuteGroupRequest, user: dict = Depends(require_auth)):
    prefs = get_notification_preferences(user["id"])
    group_pref = next((p for p in prefs if p["type"] == "group_message"), None)
    muted = list(group_pref["muted_groups"]) if group_pref else []
    if req.muted and req.group_id not in muted:
        muted.append(req.group_id)
    elif not req.muted and req.group_id in muted:
        muted.remove(req.group_id)
    set_notification_preference(user["id"], "group_message", muted_groups=muted)
    return {"muted_groups": muted}


@app.put("/api/notifications/preferences/{notify_type}")
async def update_notification_preference(
    notify_type: str,
    req: UpdateNotificationPreferenceRequest,
    user: dict = Depends(require_auth),
):
    if notify_type not in NOTIFICATION_TYPES:
        raise HTTPException(
            400,
            f"Invalid notification type. Must be one of: {', '.join(sorted(NOTIFICATION_TYPES))}",
        )
    pref = set_notification_preference(
        user["id"],
        notify_type,
        enabled=req.enabled,
        muted_groups=req.muted_groups,
    )
    return pref


@app.get("/api/config")
async def get_frontend_config():
    return {
        "supabase_url": SUPABASE_URL or "",
        "supabase_anon_key": SUPABASE_ANON_KEY or "",
    }


_frontend_dir = os.getenv("FRONTEND_DIR", "")
if _frontend_dir and Path(_frontend_dir).is_dir():
    app.mount("/", SPAStaticFiles(directory=_frontend_dir, html=True), name="frontend")
    logger.info("Serving frontend from %s", _frontend_dir)

if __name__ == "__main__":
    import uvicorn

    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8000"))
    reload = os.getenv("API_RELOAD", "false").lower() == "true"
    uvicorn.run("backend.main:app", host=host, port=port, reload=reload)
