"""Feature-gated realtime grounding companion with role-aware escalation."""

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend.auth import require_auth
from backend.database import consume_rate_limit, create_notification, get_db, write_audit
from backend.services.crypto import decrypt_pii, encrypt_pii

router = APIRouter(prefix="/api/v1/voice", tags=["voice-support"])

CRISIS_PATTERN = re.compile(
    r"\b(kill myself|suicide|end my life|want to die|going to die|hurt myself|self[- ]harm|"
    r"cannot stay safe|can't stay safe|in immediate danger|someone will hurt me)\b",
    re.IGNORECASE,
)
CONSENT_NOTICE_VERSION = "voice-v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _enabled(name: str, default: bool = False) -> bool:
    return os.getenv(name, "true" if default else "false").strip().lower() in {"1", "true", "yes", "on"}


def _launch_ready() -> bool:
    return all(_enabled(name) for name in ("VOICE_CLINICAL_REVIEW_COMPLETE", "VOICE_CHILD_SAFEGUARDING_REVIEW_COMPLETE", "VOICE_PRIVACY_REVIEW_COMPLETE", "VOICE_ACCESSIBILITY_REVIEW_COMPLETE"))


def _max_session_seconds() -> int:
    """Keep grounding sessions short even if an environment value is mis-set."""
    try:
        configured = int(os.getenv("VOICE_MAX_SESSION_SECONDS", "900"))
    except (TypeError, ValueError):
        configured = 900
    return max(60, min(configured, 900))


def _safety_salt() -> str | None:
    salt = os.getenv("VOICE_SAFETY_SALT", "").strip()
    return salt if len(salt) >= 32 else None


class VoiceSessionCreate(BaseModel):
    accepted_notice: bool
    exercise: str = Field(default="grounding", pattern=r"^(grounding|breathing|orientation|supportive_conversation)$")


class VoiceSafetyEvent(BaseModel):
    transcript_segment: str = Field(min_length=1, max_length=4000)
    client_flagged_urgent: bool = False


class VoiceClose(BaseModel):
    summary: str = Field(default="", max_length=2000)
    exercise: str | None = Field(default=None, max_length=80)


def _session_for_user(conn, session_id: str, user_id: str):
    row = conn.execute("SELECT * FROM voice_support_sessions WHERE id=? AND user_id=?", (session_id, user_id)).fetchone()
    if not row:
        raise HTTPException(404, "Voice support session not found")
    return row


def _care_recipient(conn, user: dict) -> tuple[str | None, str]:
    role = str(user.get("role_type") or "").lower()
    category = str(user.get("user_category") or "").lower()
    if role == "workplace_employee":
        row = conn.execute(
            "SELECT c.provider_id FROM workplace_support_cases c "
            "JOIN workplace_memberships m ON m.company_id=c.company_id AND m.user_id=c.user_id AND m.status='active' AND m.withdrawn_at IS NULL "
            "JOIN institutions i ON i.id=c.company_id AND i.type='company' AND i.status='ACTIVE' "
            "JOIN workplace_providers p ON p.company_id=c.company_id AND p.provider_id=c.provider_id AND p.status='active' "
            "JOIN workplace_provider_credentials pc ON pc.provider_id=c.provider_id AND pc.status='verified' "
            "JOIN users provider ON provider.id=c.provider_id AND provider.status IN ('approved','active') "
            "WHERE c.user_id=? AND c.status IN ('open','active') AND c.withdrawn_at IS NULL ORDER BY c.created_at DESC LIMIT 1",
            (user["id"],),
        ).fetchone()
        return (row["provider_id"], "workplace_provider") if row else (None, "none")
    if role in {"student"} or category in {"institution_managed", "adult"}:
        row = conn.execute(
            "SELECT a.counsellor_id FROM counsellor_student_assignments a "
            "JOIN users care ON care.id=a.counsellor_id AND care.role_type='counsellor' "
            "AND lower(COALESCE(care.status,'')) IN ('approved','active') "
            "WHERE a.student_id=? AND a.active=1 ORDER BY a.assigned_at DESC LIMIT 1",
            (user["id"],),
        ).fetchone()
        return (row["counsellor_id"], "assigned_counsellor") if row else (None, "none")
    return None, "none"


def _instructions(minor: bool, recipient_available: bool) -> str:
    audience = "a young person" if minor else "an adult"
    handoff = "An authorized care professional can receive a safety alert." if recipient_available else "No care professional is currently connected; never imply that an alert was delivered."
    child_help = " For child-protection or psychosocial support in Kenya, mention the toll-free Child Helpline 116; for immediate danger, direct the user to emergency services first." if minor else ""
    return (
        "You are MindGuard's English-language AI grounding companion speaking with " + audience + ". "
        "State that you are an AI, not a counsellor or emergency service. Use short, warm sentences and offer paced breathing, 5-4-3-2-1 grounding, orientation, and encouragement to contact a trusted person. "
        "Never diagnose, prescribe, analyze social media, encourage dependence, promise secrecy, or claim emergency help was sent. "
        "If the user mentions suicide, self-harm, immediate danger, abuse, or inability to stay safe, stop ordinary coaching, encourage immediate human help, and direct them to Kenya emergency numbers 999, 112, or 911 or the nearest health facility. "
        + child_help
        + " "
        + handoff
    )


def _urgent_fallback_message(minor: bool) -> str:
    message = "MindGuard could not notify a care professional. Call Kenya emergency services on 999, 112, or 911, contact a trusted person, or go to the nearest health facility now."
    if minor:
        message += " For child-protection or psychosocial support, you can also call the toll-free Child Helpline on 116."
    return message


def _is_minor(conn, user: dict) -> bool:
    category = str(user.get("user_category") or "").lower()
    if category == "minor":
        return True
    if category not in {"institution_managed", "student"}:
        return False
    try:
        from backend.database import get_student_by_user_id
        roster = get_student_by_user_id(user["id"])
        return bool(roster and roster.get("is_minor"))
    except Exception:
        return False


@router.get("/availability")
async def voice_availability(user: dict = Depends(require_auth)):
    conn = get_db(); recipient, kind = _care_recipient(conn, user); minor = _is_minor(conn, user); conn.close()
    configuration_blockers = []
    if not os.getenv("OPENAI_API_KEY", "").strip():
        configuration_blockers.append("OpenAI Realtime provider is not configured")
    if not _safety_salt():
        configuration_blockers.append("A private safety-identifier salt of at least 32 characters is not configured")
    return {
        "enabled": _enabled("VOICE_SUPPORT_ENABLED"),
        "review_gate_ready": _launch_ready(),
        "configuration_ready": not configuration_blockers,
        "configuration_blockers": configuration_blockers,
        "care_recipient_available": bool(recipient),
        "care_recipient_type": kind,
        "is_minor": minor,
        "language": "English",
        "stores_audio": False,
        "summary_retention_days": int(os.getenv("VOICE_SUMMARY_RETENTION_DAYS", "30")),
    }


@router.post("/sessions", status_code=201)
async def create_voice_session(data: VoiceSessionCreate, request: Request, user: dict = Depends(require_auth)):
    if not _enabled("VOICE_SUPPORT_ENABLED"):
        raise HTTPException(503, "Voice support is not enabled for this environment")
    if not _launch_ready():
        raise HTTPException(503, "Voice support is awaiting clinical, safeguarding, privacy, and accessibility review")
    if not data.accepted_notice:
        raise HTTPException(400, "Accept the voice-support notice before starting")
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    safety_salt = _safety_salt()
    if not api_key or not safety_salt:
        raise HTTPException(503, "Voice support provider and privacy-preserving safety identifier are not fully configured")
    daily_limit = int(os.getenv("VOICE_DAILY_SESSION_LIMIT", "5"))
    if not consume_rate_limit(f"voice-session:{user['id']}", daily_limit, 86400):
        raise HTTPException(429, "Daily voice-support session limit reached")
    max_duration = _max_session_seconds()
    conn = get_db()
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()
    conn.execute(
        "UPDATE voice_support_sessions SET status='expired', ended_at=COALESCE(ended_at,?), updated_at=? "
        "WHERE user_id=? AND status='active' AND active_expires_at<=?",
        (now, now, user["id"], now),
    )
    active = conn.execute(
        "SELECT id FROM voice_support_sessions WHERE user_id=? AND status='active' AND active_expires_at>? LIMIT 1",
        (user["id"], now),
    ).fetchone()
    if active:
        conn.commit()
        conn.close()
        raise HTTPException(409, "End your current voice-support session before starting another")
    recipient, recipient_type = _care_recipient(conn, user)
    minor = _is_minor(conn, user)
    conn.commit()
    conn.close()
    safety_id = hashlib.sha256((str(user["id"]) + safety_salt).encode()).hexdigest()
    model = os.getenv("OPENAI_REALTIME_MODEL", "gpt-realtime-2.1")
    payload = {
        "session": {
            "type": "realtime",
            "model": model,
            "instructions": _instructions(minor, bool(recipient)),
            "audio": {
                "input": {"transcription": {"model": os.getenv("OPENAI_TRANSCRIPTION_MODEL", "gpt-4o-mini-transcribe")}},
                "output": {"voice": os.getenv("OPENAI_REALTIME_VOICE", "marin")},
            },
        }
    }
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                "https://api.openai.com/v1/realtime/client_secrets",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "OpenAI-Safety-Identifier": safety_id},
                json=payload,
            )
        if response.status_code >= 400:
            raise HTTPException(503, "Unable to start voice support right now")
        secret = response.json()
    except httpx.HTTPError:
        raise HTTPException(503, "Unable to reach the voice support provider")
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()
    retention = int(os.getenv("VOICE_SUMMARY_RETENTION_DAYS", "30"))
    if retention < 1 or retention > 365:
        retention = 30
    session_id = str(uuid.uuid4())
    provider_session_id = secret.get("id") or secret.get("session", {}).get("id")
    conn = get_db()
    conn.execute(
        "INSERT INTO voice_support_sessions (id,user_id,provider_session_id,status,consented_at,consent_version,exercise,safety_outcome,alert_recipient_id,active_expires_at,expires_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (session_id, user["id"], provider_session_id, "active", now, CONSENT_NOTICE_VERSION, data.exercise, "none", recipient, (now_dt + timedelta(seconds=max_duration)).isoformat(), (now_dt + timedelta(days=retention)).isoformat(), now, now),
    )
    conn.commit(); conn.close()
    write_audit(user["id"], user["role_type"], "VOICE_SESSION_STARTED", "voice_session", session_id, payload={"exercise": data.exercise, "care_recipient_type": recipient_type, "audio_stored": False}, ip=request.client.host if request.client else None)
    return {"session_id": session_id, "client_secret": secret.get("value") or secret.get("client_secret", {}).get("value"), "expires_at": secret.get("expires_at"), "model": model, "consent_version": CONSENT_NOTICE_VERSION, "care_recipient_available": bool(recipient), "care_recipient_type": recipient_type, "max_duration_seconds": max_duration}


@router.post("/sessions/{session_id}/safety-event")
async def voice_safety_event(session_id: str, data: VoiceSafetyEvent, request: Request, user: dict = Depends(require_auth)):
    conn = get_db()
    row = _session_for_user(conn, session_id, user["id"])
    if row["status"] == "active" and row["active_expires_at"] <= _now():
        now = _now()
        conn.execute("UPDATE voice_support_sessions SET status='expired',ended_at=COALESCE(ended_at,?),updated_at=? WHERE id=?", (now, now, session_id))
        conn.commit()
        conn.close()
        raise HTTPException(410, "The voice-support session time limit has ended")
    minor = _is_minor(conn, user)
    urgent = data.client_flagged_urgent or bool(CRISIS_PATTERN.search(data.transcript_segment))
    if not urgent:
        conn.close()
        return {"urgent": False}
    if row["status"] != "active":
        conn.close()
        raise HTTPException(409, "This voice-support session is no longer active")
    if row["safety_outcome"] == "urgent":
        delivery = row["alert_delivery_status"] or "no_authorized_recipient"
        conn.close()
        return {"urgent": True, "delivery_status": delivery, "message": "An in-app alert was sent to your authorized care professional." if delivery in {"delivered", "acknowledged"} else _urgent_fallback_message(minor)}
    # Re-resolve at alert time. An assignment or workplace sharing relationship
    # may have been withdrawn since the voice session began.
    recipient, _recipient_type = _care_recipient(conn, user)
    delivery = "no_authorized_recipient"
    if recipient:
        try:
            create_notification(recipient, "Urgent voice-support follow-up", "A person in your authorized care scope may need immediate human follow-up. Open the alert queue; no audio recording was retained.", "crisis")
            delivery = "delivered"
        except Exception:
            delivery = "failed"
    now = _now()
    conn.execute("UPDATE voice_support_sessions SET safety_outcome='urgent', alert_recipient_id=?, alert_delivery_status=?, updated_at=? WHERE id=?", (recipient, delivery, now, session_id))
    conn.commit(); conn.close()
    write_audit(user["id"], user["role_type"], "VOICE_SAFETY_ESCALATION", "voice_session", session_id, payload={"delivery_status": delivery, "recipient_present": bool(recipient), "transcript_stored": False}, ip=request.client.host if request.client else None)
    return {"urgent": True, "delivery_status": delivery, "message": "An in-app alert was sent to your authorized care professional." if delivery == "delivered" else _urgent_fallback_message(minor)}


@router.post("/sessions/{session_id}/close")
async def close_voice_session(session_id: str, data: VoiceClose, request: Request, user: dict = Depends(require_auth)):
    conn = get_db(); row = _session_for_user(conn, session_id, user["id"])
    now = _now()
    if row["status"] == "expired" or row["active_expires_at"] <= now:
        conn.execute("UPDATE voice_support_sessions SET status='expired',summary_encrypted=NULL,ended_at=COALESCE(ended_at,?),updated_at=? WHERE id=?", (now, now, session_id))
        conn.commit(); conn.close()
        raise HTTPException(410, "The voice-support session time limit has ended; no summary was saved")
    summary = data.summary.strip()
    conn.execute("UPDATE voice_support_sessions SET status='closed', summary_encrypted=?, exercise=COALESCE(?,exercise), ended_at=?, updated_at=? WHERE id=?", (encrypt_pii(summary) if summary else None, data.exercise, now, now, session_id))
    conn.commit(); conn.close()
    write_audit(user["id"], user["role_type"], "VOICE_SESSION_CLOSED", "voice_session", session_id, payload={"summary_saved": bool(summary), "audio_stored": False, "transcript_stored": False}, ip=request.client.host if request.client else None)
    return {"ok": True}


@router.get("/sessions")
async def own_voice_sessions(user: dict = Depends(require_auth)):
    conn = get_db()
    rows = conn.execute("SELECT id,status,exercise,summary_encrypted,safety_outcome,alert_delivery_status,created_at,ended_at FROM voice_support_sessions WHERE user_id=? AND expires_at>? ORDER BY created_at DESC LIMIT 30", (user["id"], _now())).fetchall()
    conn.close()
    return [{"id": row["id"], "status": row["status"], "exercise": row["exercise"], "summary": decrypt_pii(row["summary_encrypted"]) if row["summary_encrypted"] else None, "safety_outcome": row["safety_outcome"], "alert_delivery_status": row["alert_delivery_status"], "created_at": row["created_at"], "ended_at": row["ended_at"]} for row in rows]


@router.post("/alerts/{session_id}/acknowledge")
async def acknowledge_voice_alert(session_id: str, user: dict = Depends(require_auth)):
    conn = get_db()
    row = conn.execute("SELECT s.id,s.user_id,u.role_type,u.user_category FROM voice_support_sessions s JOIN users u ON u.id=s.user_id WHERE s.id=? AND s.alert_recipient_id=? AND s.alert_delivery_status='delivered'", (session_id, user["id"])).fetchone()
    if not row or _care_recipient(conn, {"id": row["user_id"], "role_type": row["role_type"], "user_category": row["user_category"]})[0] != user["id"]:
        conn.close(); raise HTTPException(404, "Voice safety alert not found")
    now = _now()
    conn.execute("UPDATE voice_support_sessions SET alert_delivery_status='acknowledged', alert_acknowledged_at=?, updated_at=? WHERE id=?", (now, now, session_id))
    conn.commit(); conn.close()
    write_audit(user["id"], user["role_type"], "VOICE_ALERT_ACKNOWLEDGED", "voice_session", session_id)
    return {"ok": True}


@router.get("/alerts")
async def voice_alerts_for_recipient(user: dict = Depends(require_auth)):
    if user.get("role_type") not in {"counsellor", "school_admin", "workplace_provider", "admin"}:
        raise HTTPException(403, "Care-team access required")
    conn = get_db()
    rows = conn.execute("SELECT s.id,s.user_id AS subject_user_id,u.name AS subject_name,u.role_type,u.user_category,s.status,s.safety_outcome,s.alert_delivery_status,s.alert_acknowledged_at,s.created_at,s.updated_at FROM voice_support_sessions s JOIN users u ON u.id=s.user_id WHERE s.alert_recipient_id=? AND s.safety_outcome='urgent' ORDER BY s.updated_at DESC LIMIT 100", (user["id"],)).fetchall()
    conn.close()
    visible = []
    for row in rows:
        conn = get_db()
        current_recipient, _kind = _care_recipient(
            conn,
            {"id": row["subject_user_id"], "role_type": row["role_type"], "user_category": row["user_category"]},
        )
        conn.close()
        if current_recipient == user["id"]:
            visible.append({key: row[key] for key in ("id", "subject_user_id", "subject_name", "status", "safety_outcome", "alert_delivery_status", "alert_acknowledged_at", "created_at", "updated_at")})
    return visible


def purge_expired_voice_summaries() -> int:
    conn = get_db(); now = _now()
    rows = conn.execute("SELECT id FROM voice_support_sessions WHERE expires_at<=? AND summary_encrypted IS NOT NULL", (now,)).fetchall()
    conn.execute("UPDATE voice_support_sessions SET summary_encrypted=NULL, status=CASE WHEN status='active' THEN 'expired' ELSE status END, updated_at=? WHERE expires_at<=?", (now, now))
    conn.commit(); conn.close()
    return len(rows)
