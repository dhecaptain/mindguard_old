"""Feature-gated realtime grounding companion with role-aware escalation."""

import asyncio
import hashlib
import json
import logging
import os
import re
import time
import uuid
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.auth import require_auth
from backend.database import consume_rate_limit, create_notification, get_db, write_audit
from backend.services.crypto import decrypt_pii, encrypt_pii
from backend.secrets_manager import get_secret
from backend.services.voice_realtime import OpenAIRealtimeProvider, VoiceProviderError
from backend.services.voice_actions import CONFIRM_REQUIRED, SHARE_REQUIRED, ACTION_SENSITIVITY, NAVIGATION_TARGETS, voice_tool_definitions
from backend.services.voice_safety import (
    DISTRESS,
    HEIGHTENED_CONCERN,
    NORMAL,
    POTENTIAL_IMMEDIATE_DANGER,
    classify_voice_text,
)

router = APIRouter(prefix="/api/v1/voice", tags=["voice-support"])
logger = logging.getLogger(__name__)

CONSENT_NOTICE_VERSION = "voice-v2"
_voice_worker_id = str(uuid.uuid4())
_voice_monitor_tasks: set[asyncio.Task] = set()


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
    salt = get_secret("VOICE_SAFETY_SALT").strip()
    return salt if len(salt) >= 32 else None


def _server_side_controls_ready() -> bool:
    background_disabled = os.getenv("MINDGUARD_DISABLE_BACKGROUND_TASKS", "").strip().lower() in {"1", "true", "yes"}
    return _enabled("VOICE_SERVER_SIDE_CONTROLS_ENABLED") and not background_disabled


class VoiceSessionCreate(BaseModel):
    accepted_notice: bool
    exercise: str = Field(default="general_support", pattern=r"^(general_support|grounding|breathing|orientation|supportive_conversation)$")


class VoiceWebrtcOffer(BaseModel):
    sdp: str = Field(min_length=100, max_length=180000)


class VoiceClose(BaseModel):
    model_config = ConfigDict(extra="forbid")
    exercise: str | None = Field(default=None, max_length=80)


class VoiceActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal[
        "get_my_current_support",
        "get_my_upcoming_appointments",
        "get_my_available_providers",
        "navigate",
        "prepare_for_appointment",
        "propose_workplace_checkin",
        "propose_human_support",
        "propose_private_summary",
        "propose_summary_share",
    ]
    payload: dict[str, object] = Field(default_factory=dict)


class VoiceActionConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed: bool


def _session_for_user(conn, session_id: str, user_id: str):
    row = conn.execute("SELECT * FROM voice_support_sessions WHERE id=? AND user_id=?", (session_id, user_id)).fetchone()
    if not row:
        raise HTTPException(404, "Voice support session not found")
    return row


def _active_voice_session(session_id: str, user: dict):
    if not _enabled("VOICE_SUPPORT_ENABLED") or not _server_side_controls_ready():
        raise HTTPException(503, "Voice actions are not enabled")
    conn = get_db()
    try:
        row = _session_for_user(conn, session_id, user["id"])
    except HTTPException:
        conn.close()
        raise
    now = _now()
    if row["status"] != "active":
        conn.close()
        raise HTTPException(409, "Voice actions require an active voice session")
    if not row["sideband_connected_at"]:
        conn.close()
        raise HTTPException(409, "Voice actions are waiting for server-side controls")
    if row["active_expires_at"] <= now:
        conn.execute(
            "UPDATE voice_support_sessions SET status='ending',pending_action_id=NULL,"
            "pending_action_type=NULL,pending_action_payload_encrypted=NULL,"
            "pending_action_expires_at=NULL,pending_action_source=NULL,pending_action_confirmation_prompt=NULL,"
            "pending_action_prompted_at=NULL,pending_action_state='expired',updated_at=? "
            "WHERE id=? AND status='active'",
            (now, session_id),
        )
        conn.commit()
        conn.close()
        raise HTTPException(410, "The voice session expired; pending actions were discarded")
    return conn, row


def _workplace_employee(user: dict) -> bool:
    return user.get("role_type") == "workplace_employee"


def _publish_voice_navigation(session_id: str, user_id: str, route_id: str) -> dict:
    event_id = str(uuid.uuid4())
    now = _now()
    conn = get_db()
    updated = conn.execute(
        "UPDATE voice_support_sessions SET navigation_event_id=?,navigation_route_id=?,navigation_created_at=?,updated_at=? "
        "WHERE id=? AND user_id=? AND status='active' AND active_expires_at>?",
        (event_id, route_id, now, now, session_id, user_id, now),
    )
    conn.commit()
    conn.close()
    return {"result": "SUCCESS", "navigation_event_id": event_id, "route_id": route_id} if updated.rowcount == 1 else {
        "result": "FAILED", "message": "This voice session has ended; I did not open a page."
    }


async def _safe_appointments(user: dict) -> list[dict]:
    now = datetime.now(timezone.utc)
    if _workplace_employee(user):
        from backend.routes.workplace import employee_workplace_appointments

        appointments = await employee_workplace_appointments(user)
        result = []
        for item in appointments:
            try:
                starts = datetime.fromisoformat(item["starts_at"].replace("Z", "+00:00"))
            except (ValueError, TypeError, AttributeError):
                continue
            if starts >= now and item["status"] == "scheduled":
                result.append(
                    {
                        "id": item["id"],
                        "starts_at": item["starts_at"],
                        "status": item["status"],
                        "provider_name": item["provider_name"],
                        "mode": item["mode"],
                    }
                )
        return result[:20]
    if user.get("role_type") != "student":
        raise HTTPException(403, "Appointments are not available for this account")
    from backend.database import list_appointments

    appointments = list_appointments(user["id"])
    result = []
    for item in appointments:
        try:
            starts = datetime.fromisoformat(item["start_at"].replace("Z", "+00:00"))
        except (ValueError, TypeError, AttributeError):
            continue
        if item.get("student_id") == user["id"] and starts >= now and item["status"] in {"REQUESTED", "CONFIRMED"}:
            result.append(
                {
                    "id": item["id"],
                    "starts_at": item["start_at"],
                    "ends_at": item["end_at"],
                    "status": item["status"],
                    "title": item["title"],
                    "provider_name": item["counsellor_name"] if item["student_id"] == user["id"] else item["student_name"],
                    "mode": item["mode"],
                }
            )
    return result[:20]


async def _current_support(user: dict) -> dict:
    if _workplace_employee(user):
        from backend.routes.workplace import own_workplace_support_requests

        cases = await own_workplace_support_requests(user)
        return {
            "state": "active" if any(item["status"] in {"open", "active"} for item in cases) else "none",
            "cases": [
                {
                    "case_id": item["id"],
                    "status": item["status"],
                    "created_at": item["created_at"],
                }
                for item in cases
            ],
        }
    if user.get("role_type") != "student":
        raise HTTPException(403, "Support information is not available for this account")
    conn = get_db()
    recipient, kind = _care_recipient(conn, user)
    name = None
    if recipient:
        row = conn.execute("SELECT name FROM users WHERE id=? AND status IN ('approved','active')", (recipient,)).fetchone()
        name = row["name"] if row else None
    conn.close()
    return {"state": "connected" if recipient and name else "none", "provider_name": name, "relationship": kind if name else "none"}


def _prepare_pending_action(
    session_id: str,
    user: dict,
    action: str,
    payload: dict,
    *,
    source: str,
    confirmation_prompt: str,
) -> dict:
    if action not in ACTION_SENSITIVITY:
        raise HTTPException(400, "This Voice action is not available")
    conn, row = _active_voice_session(session_id, user)
    if row["pending_action_id"]:
        conn.close()
        raise HTTPException(409, "Finish or cancel the pending Voice action first")
    action_id = str(uuid.uuid4())
    expiry = min(
        datetime.fromisoformat(row["active_expires_at"]),
        datetime.now(timezone.utc) + timedelta(minutes=5),
    ).isoformat()
    updated = conn.execute(
        "UPDATE voice_support_sessions SET pending_action_id=?,pending_action_type=?,"
        "pending_action_payload_encrypted=?,pending_action_expires_at=?,pending_action_state='awaiting_confirmation',"
        "pending_action_source=?,pending_action_confirmation_prompt=?,pending_action_prompted_at=NULL,updated_at=? "
        "WHERE id=? AND user_id=? AND status='active' AND pending_action_id IS NULL",
        (
            action_id, action, encrypt_pii(json.dumps(payload)), expiry, source,
            encrypt_pii(confirmation_prompt), _now(), session_id, user["id"],
        ),
    )
    if updated.rowcount != 1:
        conn.close()
        raise HTTPException(409, "Unable to start the pending Voice action")
    conn.commit()
    conn.close()
    write_audit(
        user["id"], user["role_type"], "VOICE_ACTION_PROPOSED", "voice_session", session_id,
        payload={"action": action, "source": source},
    )
    return {
        "result": "CONFIRMATION_REQUIRED",
        "pending_action_id": action_id,
        "sensitivity": ACTION_SENSITIVITY[action],
        "expires_at": expiry,
        "action": action,
        "confirmation_prompt": confirmation_prompt,
    }


def _finish_voice_action(session_id: str, action_id: str, state: str) -> None:
    conn = get_db()
    conn.execute(
        "UPDATE voice_support_sessions SET pending_action_id=NULL,pending_action_type=NULL,"
        "pending_action_payload_encrypted=NULL,pending_action_expires_at=NULL,"
        "pending_action_source=NULL,pending_action_confirmation_prompt=NULL,pending_action_prompted_at=NULL,"
        "pending_action_state=?,updated_at=? WHERE id=? AND pending_action_id=?",
        (state, _now(), session_id, action_id),
    )
    conn.commit()
    conn.close()


@router.post("/sessions/{session_id}/actions")
async def voice_action(session_id: str, data: VoiceActionRequest, user: dict = Depends(require_auth)):
    return await _voice_action_impl(session_id, data, user, source="ui")


async def _voice_action_impl(session_id: str, data: VoiceActionRequest, user: dict, *, source: str) -> dict:
    """Execute read-only allowlisted actions or stage a confirmed action."""
    conn, _session = _active_voice_session(session_id, user)
    conn.close()
    payload = data.payload

    if data.action == "get_my_current_support":
        try:
            value = await _current_support(user)
        except HTTPException as exc:
            return {"result": "NOT_ALLOWED" if exc.status_code == 403 else "FAILED", "message": "I couldn't access your support information right now."}
        write_audit(user["id"], user["role_type"], "VOICE_SUPPORT_STATUS_ACCESSED", "voice_session", session_id, payload={"voice_action": True})
        return {"result": "SUCCESS", "support": value}

    if data.action == "get_my_upcoming_appointments":
        try:
            appointments = await _safe_appointments(user)
        except HTTPException as exc:
            return {"result": "NOT_ALLOWED" if exc.status_code == 403 else "FAILED", "message": "I couldn't access your appointments right now."}
        write_audit(user["id"], user["role_type"], "VOICE_APPOINTMENTS_ACCESSED", "voice_session", session_id, payload={"count": len(appointments)})
        return {"result": "SUCCESS", "appointments": appointments}

    if data.action == "get_my_available_providers":
        if not _workplace_employee(user):
            return {"result": "PROVIDER_UNAVAILABLE", "providers": []}
        from backend.routes.workplace import available_providers

        try:
            providers = await available_providers(user)
        except HTTPException:
            return {"result": "PROVIDER_UNAVAILABLE", "providers": []}
        return {"result": "SUCCESS" if providers else "PROVIDER_UNAVAILABLE", "providers": providers}

    if data.action == "navigate":
        if set(payload) != {"target"} or not isinstance(payload.get("target"), str) or payload["target"] not in NAVIGATION_TARGETS:
            return {"result": "NOT_ALLOWED", "message": "That MindGuard destination isn't available."}
        if payload["target"] == "workplace_space" and not _workplace_employee(user):
            return {"result": "NOT_ALLOWED", "message": "That MindGuard destination isn't available for this account."}
        route_id = NAVIGATION_TARGETS[payload["target"]]
        if _workplace_employee(user) and payload["target"] == "checkins":
            route_id = "workplace-checkins"
        if _workplace_employee(user) and payload["target"] == "support":
            route_id = "workplace-support"
        if source == "voice":
            return _publish_voice_navigation(session_id, user["id"], route_id)
        return {"result": "SUCCESS", "navigation_target": payload["target"], "route_id": route_id}

    if data.action == "prepare_for_appointment":
        if set(payload) != {"appointment_id"} or not isinstance(payload.get("appointment_id"), str):
            return {"result": "NOT_FOUND", "message": "Choose one of your upcoming appointments first."}
        try:
            appointment = next((item for item in await _safe_appointments(user) if item["id"] == payload["appointment_id"]), None)
        except HTTPException:
            appointment = None
        if not appointment:
            return {"result": "NOT_FOUND", "message": "That upcoming appointment isn't available."}
        return {
            "result": "SUCCESS",
            "appointment": appointment,
            "preparation_prompts": [
                "What has changed since you last spoke?",
                "What has been difficult, and what has helped?",
                "What would you like to ask or remember?",
            ],
            "saved": False,
        }

    if data.action == "propose_workplace_checkin":
        if not _workplace_employee(user):
            return {"result": "NOT_ALLOWED", "message": "A private check-in is not available for this account type."}
        if set(payload) != {"mood", "stress", "support_access"} or any(type(payload.get(key)) is not int or not 1 <= payload[key] <= 5 for key in ("mood", "stress", "support_access")):
            return {"result": "FAILED", "message": "Check-in answers must use the current 1-to-5 MindGuard options."}
        from backend.routes.workplace import CheckinCreate, _employee

        try:
            _employee(user)
            CheckinCreate(**payload)
        except HTTPException:
            return {"result": "WORKPLACE_UNAVAILABLE", "message": "Your workplace check-in isn't available right now."}
        return _prepare_pending_action(
            session_id, user, data.action, payload, source=source,
            confirmation_prompt="Would you like to save these answers as a private workplace check-in?",
        )

    if data.action == "propose_human_support":
        if _workplace_employee(user):
            expected = {"provider_id"} if source == "voice" else {"provider_id", "share_latest_checkin"}
            if set(payload) != expected or not isinstance(payload.get("provider_id"), str):
                return {"result": "CONSENT_REQUIRED", "message": "Choose an available provider and complete the separate check-in sharing consent."}
            if source != "voice" and payload.get("share_latest_checkin") is not True:
                return {"result": "CONSENT_REQUIRED", "message": "Choose an available provider and explicitly choose whether to share your latest check-in."}
            from backend.routes.workplace import available_providers, own_workplace_support_requests

            try:
                selected_provider = next((item for item in await available_providers(user) if item["id"] == payload["provider_id"]), None)
                if not selected_provider:
                    return {"result": "PROVIDER_UNAVAILABLE", "message": "That provider is not currently available."}
                existing = await own_workplace_support_requests(user)
            except HTTPException:
                return {"result": "WORKPLACE_UNAVAILABLE", "message": "Workplace support isn't available right now."}
            active = next((item for item in existing if item["status"] in {"open", "active"}), None)
            if active:
                return {"result": "SUCCESS", "already_active": True, "case_id": active["id"], "message": "You already have an active support request."}
            if source == "voice":
                return _prepare_pending_action(
                    session_id, user, data.action,
                    {"provider_id": payload["provider_id"], "share_latest_checkin": False},
                    source=source,
                    confirmation_prompt=(
                        f"Would you like to share your latest workplace check-in with {selected_provider['name']} "
                        "as part of this support request? Nothing will be sent yet."
                    ),
                ) | {"sensitivity": "SHARE_REQUIRED"}
            return _prepare_pending_action(
                session_id, user, data.action, payload, source=source,
                confirmation_prompt=(
                    f"Would you like to request support from {selected_provider['name']} and "
                    "share your latest workplace check-in?"
                ),
            ) | {"sensitivity": "SHARE_REQUIRED"}
        if user.get("role_type") != "student" or payload:
            return {"result": "NOT_ALLOWED", "message": "Support requests aren't available for this account."}
        conn = get_db()
        recipient, _kind = _care_recipient(conn, user)
        provider = conn.execute("SELECT name FROM users WHERE id=? AND role_type='counsellor' AND status IN ('approved','active')", (recipient,)).fetchone() if recipient else None
        conn.close()
        if not recipient or not provider:
            return {"result": "PROVIDER_UNAVAILABLE", "message": "No assigned counsellor is currently available for a support request."}
        return _prepare_pending_action(
            session_id, user, data.action, {"provider_id": recipient}, source=source,
            confirmation_prompt=(
                f"Would you like me to send a support request to your assigned counsellor, "
                f"{provider['name']}? No voice transcript or summary will be included."
            ),
        )

    if data.action == "propose_private_summary":
        if set(payload) != {"summary"} or not isinstance(payload.get("summary"), str) or not payload["summary"].strip() or len(payload["summary"]) > 2000:
            return {"result": "FAILED", "message": "Enter a private note of up to 2,000 characters to review."}
        return _prepare_pending_action(
            session_id, user, data.action, {"summary": payload["summary"].strip()}, source=source,
            confirmation_prompt=(
                "Here is the private note I prepared for you: " + payload["summary"].strip() + ". "
                "Would you like to save this note privately to your MindGuard account? "
                "It will not be shared with a provider or employer."
            ),
        )

    if data.action == "propose_summary_share":
        if not _workplace_employee(user) or set(payload) != {"case_id"} or not isinstance(payload.get("case_id"), str):
            return {"result": "NOT_ALLOWED", "message": "Summary sharing is available only through your own active workplace support case."}
        conn = get_db()
        stored = conn.execute("SELECT summary_encrypted FROM voice_support_sessions WHERE id=? AND user_id=?", (session_id, user["id"])).fetchone()
        conn.close()
        if not stored or not stored["summary_encrypted"]:
            return {"result": "NOT_FOUND", "message": "Save a private note before choosing to share it."}
        from backend.routes.workplace import own_workplace_support_requests

        try:
            case = next((item for item in await own_workplace_support_requests(user) if item["id"] == payload["case_id"] and item["status"] in {"open", "active"}), None)
        except HTTPException:
            case = None
        if not case:
            return {"result": "NOT_FOUND", "message": "That active support case isn't available."}
        return _prepare_pending_action(
            session_id, user, data.action, {"case_id": case["id"]}, source=source,
            confirmation_prompt=(
                "Would you like to share your saved private note with this provider? "
                "Only this note will be shared, not the conversation or audio."
            ),
        ) | {"sensitivity": "SHARE_REQUIRED"}

    return {"result": "NOT_ALLOWED", "message": "That Voice action isn't available."}


@router.post("/sessions/{session_id}/actions/{action_id}/confirm")
async def confirm_voice_action(session_id: str, action_id: str, data: VoiceActionConfirmation, request: Request, user: dict = Depends(require_auth)):
    return await _confirm_voice_action_impl(session_id, action_id, data, user)


async def _confirm_voice_action_impl(session_id: str, action_id: str, data: VoiceActionConfirmation, user: dict) -> dict:
    conn, row = _active_voice_session(session_id, user)
    now = _now()
    if row["pending_action_id"] != action_id or row["pending_action_state"] != "awaiting_confirmation":
        conn.close()
        return {"result": "NOT_FOUND", "message": "That pending Voice action is no longer available."}
    if not row["pending_action_expires_at"] or row["pending_action_expires_at"] <= now:
        conn.close()
        _finish_voice_action(session_id, action_id, "expired")
        return {"result": "FAILED", "message": "That confirmation expired. Please request the action again."}
    if not data.confirmed:
        conn.close()
        _finish_voice_action(session_id, action_id, "cancelled")
        return {"result": "SUCCESS", "cancelled": True, "message": "Nothing was changed or shared."}
    action = row["pending_action_type"]
    try:
        payload = json.loads(decrypt_pii(row["pending_action_payload_encrypted"]))
    except (TypeError, ValueError, RuntimeError):
        conn.close()
        _finish_voice_action(session_id, action_id, "failed")
        return {"result": "FAILED", "message": "I couldn't complete that action right now."}
    if (
        data.confirmed and action == "propose_human_support" and _workplace_employee(user)
        and row["pending_action_source"] == "voice" and payload.get("share_latest_checkin") is False
    ):
        from backend.routes.workplace import available_providers

        try:
            provider = next((item for item in await available_providers(user) if item["id"] == payload.get("provider_id")), None)
        except HTTPException:
            provider = None
        if not provider:
            conn.close()
            _finish_voice_action(session_id, action_id, "failed")
            return {"result": "PROVIDER_UNAVAILABLE", "message": "That provider is no longer available. No support request was sent."}
        followup_prompt = (
            f"Would you like me to send the support request to {provider['name']} and share your latest workplace check-in? "
            "This is the final confirmation; nothing has been sent yet."
        )
        changed = conn.execute(
            "UPDATE voice_support_sessions SET pending_action_payload_encrypted=?,pending_action_confirmation_prompt=?,"
            "pending_action_prompted_at=NULL,updated_at=? WHERE id=? AND user_id=? AND pending_action_id=? "
            "AND pending_action_state='awaiting_confirmation' AND status='active' AND active_expires_at>?",
            (encrypt_pii(json.dumps(payload | {"share_latest_checkin": True})), encrypt_pii(followup_prompt), now, session_id, user["id"], action_id, now),
        )
        conn.commit()
        conn.close()
        if changed.rowcount != 1:
            return {"result": "FAILED", "message": "That action is no longer waiting for confirmation."}
        return {
            "result": "CONFIRMATION_REQUIRED", "pending_action_id": action_id,
            "action": action, "stage": "final_confirmation", "sensitivity": SHARE_REQUIRED,
            "confirmation_prompt": followup_prompt,
        }
    claimed = conn.execute(
        "UPDATE voice_support_sessions SET pending_action_state='executing',updated_at=? "
        "WHERE id=? AND user_id=? AND pending_action_id=? AND pending_action_state='awaiting_confirmation' "
        "AND status='active' AND active_expires_at>?",
        (now, session_id, user["id"], action_id, now),
    )
    if claimed.rowcount != 1:
        conn.close()
        return {"result": "FAILED", "message": "That action is no longer waiting for confirmation."}
    conn.commit()
    conn.close()

    try:
        if action == "propose_workplace_checkin":
            if not _workplace_employee(user):
                raise HTTPException(403, "Action not allowed")
            from backend.routes.workplace import CheckinCreate, _store_workplace_checkin

            saved = _store_workplace_checkin(CheckinCreate(**payload), user, origin="voice")
            write_audit(user["id"], user["role_type"], "VOICE_CHECKIN_CONFIRMED", "voice_session", session_id, payload={"origin": "voice", "private": True})
            result = {"result": "SUCCESS", "checkin": {"saved": bool(saved.get("saved")), "visibility": saved.get("visibility")}, "message": "Your check-in was saved privately. It wasn't shared."}
        elif action == "propose_human_support":
            provider_id = payload.get("provider_id")
            if _workplace_employee(user):
                from backend.routes.workplace import SupportRequest, own_workplace_support_requests, request_provider_support

                existing = await own_workplace_support_requests(user)
                active = next((item for item in existing if item["status"] in {"open", "active"}), None)
                if active:
                    result = {"result": "SUCCESS", "already_active": True, "case_id": active["id"], "message": "Your existing support request remains active; no duplicate case was created."}
                else:
                    from backend.routes.workplace import available_providers

                    if not any(item["id"] == provider_id for item in await available_providers(user)):
                        raise HTTPException(404, "Provider unavailable")
                    created = await request_provider_support(SupportRequest(provider_id=provider_id, share_latest_checkin=True), user)
                    write_audit(user["id"], user["role_type"], "VOICE_SUPPORT_REQUEST_CONFIRMED", "voice_session", session_id, payload={"case_id": created["case_id"], "latest_checkin_shared": True})
                    result = {"result": "SUCCESS", "case_id": created["case_id"], "message": "Your support request was sent to the selected provider, and your latest workplace check-in was shared with your permission."}
            else:
                if user.get("role_type") != "student":
                    raise HTTPException(403, "Action not allowed")
                conn = get_db()
                recipient, _kind = _care_recipient(conn, user)
                provider = conn.execute("SELECT name FROM users WHERE id=? AND role_type='counsellor' AND status IN ('approved','active')", (recipient,)).fetchone() if recipient else None
                conn.close()
                if not provider_id or recipient != provider_id or not provider:
                    raise HTTPException(404, "Assigned care relationship unavailable")
                from backend.database import create_notification, send_message

                sent = send_message(user["id"], recipient, "I would like to request human support. Please contact me through MindGuard when you are available.")
                create_notification(recipient, "Support request", "A person you are authorized to support requested contact through MindGuard.", "message")
                write_audit(user["id"], user["role_type"], "VOICE_SUPPORT_REQUEST_CONFIRMED", "voice_session", session_id, payload={"message_id": sent["id"], "summary_shared": False})
                result = {"result": "SUCCESS", "message": "Your assigned counsellor received your request. No voice transcript or summary was included."}
        elif action == "propose_private_summary":
            conn = get_db()
            changed = conn.execute("UPDATE voice_support_sessions SET summary_encrypted=?,summary_saved_at=?,updated_at=? WHERE id=? AND user_id=? AND status='active' AND active_expires_at>?", (encrypt_pii(payload["summary"]), now, now, session_id, user["id"], now))
            conn.commit()
            conn.close()
            if not changed.rowcount:
                raise HTTPException(410, "Voice session expired")
            write_audit(user["id"], user["role_type"], "VOICE_SUMMARY_SAVED", "voice_session", session_id, payload={"private": True, "shared": False})
            result = {"result": "SUCCESS", "message": "Your note was saved privately. It wasn't shared."}
        elif action == "propose_summary_share":
            if not _workplace_employee(user):
                raise HTTPException(403, "Action not allowed")
            from backend.routes.workplace import WorkplaceMessageCreate, own_workplace_support_requests, send_employee_workplace_message

            current_case = next((item for item in await own_workplace_support_requests(user) if item["id"] == payload["case_id"] and item["status"] in {"open", "active"}), None)
            conn = get_db()
            current_session = conn.execute("SELECT summary_encrypted FROM voice_support_sessions WHERE id=? AND user_id=? AND status='active'", (session_id, user["id"])).fetchone()
            conn.close()
            if not current_case or not current_session or not current_session["summary_encrypted"]:
                raise HTTPException(404, "The saved note or support case is no longer available")
            content = decrypt_pii(current_session["summary_encrypted"])
            await send_employee_workplace_message(WorkplaceMessageCreate(case_id=payload["case_id"], message=content), user)
            write_audit(user["id"], user["role_type"], "VOICE_SUMMARY_SHARED", "voice_session", session_id, payload={"case_id": payload["case_id"], "summary_reference": "encrypted_voice_session_note", "transcript_shared": False, "audio_shared": False})
            result = {"result": "SUCCESS", "message": "Only your approved note was shared with the provider through your support case."}
        else:
            raise HTTPException(400, "Action unavailable")
        _finish_voice_action(session_id, action_id, "completed")
        return result
    except HTTPException as exc:
        _finish_voice_action(session_id, action_id, "failed")
        code = "NOT_ALLOWED" if exc.status_code == 403 else "NOT_FOUND" if exc.status_code == 404 else "WORKPLACE_UNAVAILABLE" if exc.status_code in {409, 410} else "FAILED"
        message = "That action isn't available for this account." if code == "NOT_ALLOWED" else "I couldn't complete that action right now. Your note was not shared." if action == "propose_summary_share" else "I couldn't complete that action right now."
        return {"result": code, "message": message}
    except Exception:
        logger.warning("Voice action failed for session %s and action %s", session_id, action, exc_info=False)
        _finish_voice_action(session_id, action_id, "failed")
        return {"result": "FAILED", "message": "I couldn't complete that action right now. You can continue the conversation."}


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
        "You are MindGuard's English-language AI wellbeing companion speaking with " + audience + ". "
        "You are not a therapist, counsellor, doctor, diagnostic system, or emergency service. Listen, reflect specifically on what the person said, help organize overwhelming thoughts, offer a short grounding exercise when useful, and help them find MindGuard support options. "
        "Keep spoken replies concise, warm, respectful, and non-judgmental. Ask one useful question at a time. The person may decline exercises, change topic, pause, interrupt, or end the session. Do not diagnose, prescribe, encourage dependence, promise secrecy, expose other users' information, or claim an action or alert occurred unless the application confirms it. "
        "Use the supplied MindGuard functions when a person naturally asks for an available action; do not wait for exact phrases or use keyword rules. Never invent account facts: report only data in a successful function result, and state briefly when a lookup or action failed. You may request an action, but the application alone authorizes it. Never claim an action succeeded before its result says SUCCESS. Do not request or use arbitrary URLs, APIs, or tools. "
        "Read-only lookups may be requested when relevant. Navigation may only use the supplied approved targets. Appointment preparation is private and must not be saved or shared unless the person separately asks. "
        "For workplace check-ins, gather only the existing mood, stress-manageability, and perceived-support ratings from 1 to 5. Ask conversationally for an explicit rating for each; never infer or calculate ratings from what the person says. Stage the check-in only once all three explicit ratings are known, repeat the returned confirmation question, and wait for a clear answer. "
        "For support requests, preserve provider eligibility and choice. For workplace users, offer returned eligible providers, ask which one they choose, then start the support flow with only that provider ID. The application—not you—will ask a separate check-in sharing consent question and then a distinct final request confirmation. Never put consent into tool arguments or infer it from the initial request. For non-workplace users, use only their assigned counsellor. Never send a transcript or private note with a support request. "
        "A private summary is only a concise draft of topics and concerns the user expressed, useful observations, and actions the user decided to take. Distinguish user statements from assistant suggestions. Do not diagnose. Read the draft back to the user before asking whether to save it. Saving requires a separate clear confirmation; provider sharing requires its own separate consent and confirmation. Never conflate GENERATE, SAVE, and SHARE. "
        "When a persistent action is staged, repeat the exact confirmation question supplied by the application and stop to wait. Do not treat the initial request as consent or confirmation. Only a clear, immediate yes/no to the current question can resolve it; if the user changes topic or the response is unclear, do not act. Cancellation means nothing was saved or shared. "
        "If the user mentions suicide, self-harm, immediate danger, abuse, or inability to stay safe, stop ordinary coaching, encourage immediate human help, and direct them to Kenya emergency numbers 999, 112, or 911 or the nearest health facility. "
        + child_help
        + " "
        + handoff
        + " Safety monitoring and safety-state instructions take precedence over ordinary actions. If an action fails or is blocked, do not retry by another path or imply success; continue supportively."
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


def _status_for_client(row) -> dict:
    return {
        "status": row["status"],
        "safety_state": row["safety_outcome"],
        "alert_delivery_status": row["alert_delivery_status"],
        "max_duration_seconds": _max_session_seconds(),
    }


def _mark_session_ending(session_id: str, *, final_status: str = "completed", reason: str | None = None) -> None:
    conn = get_db()
    now = _now()
    row = conn.execute("SELECT s.started_at,s.created_at,s.user_id,u.role_type FROM voice_support_sessions s JOIN users u ON u.id=s.user_id WHERE s.id=?", (session_id,)).fetchone()
    if row:
        started = row["started_at"] or row["created_at"]
        try:
            duration = max(0, int((datetime.fromisoformat(now) - datetime.fromisoformat(started)).total_seconds()))
        except (ValueError, TypeError):
            duration = None
        updated = conn.execute(
            "UPDATE voice_support_sessions SET status=?,ended_at=COALESCE(ended_at,?),duration_seconds=COALESCE(duration_seconds,?),failure_reason=?,client_secret_encrypted=NULL,sideband_worker_id=NULL,sideband_lease_until=NULL,pending_action_id=NULL,pending_action_type=NULL,pending_action_payload_encrypted=NULL,pending_action_expires_at=NULL,pending_action_source=NULL,pending_action_confirmation_prompt=NULL,pending_action_prompted_at=NULL,pending_action_state='expired',updated_at=? WHERE id=? AND status NOT IN ('completed','failed','expired')",
            (final_status, now, duration, reason, now, session_id),
        )
        conn.commit()
        if updated.rowcount:
            action = "VOICE_SESSION_FAILED" if final_status == "failed" else "VOICE_SESSION_COMPLETED"
            write_audit(row["user_id"], row["role_type"], action, "voice_session", session_id, payload={"status": final_status, "duration_seconds": duration, "failure_reason": reason, "audio_stored": False, "transcript_stored": False})
    conn.close()


def _release_sideband_lease(session_id: str) -> None:
    conn = get_db()
    retry_at = (datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat()
    conn.execute(
        "UPDATE voice_support_sessions SET sideband_worker_id=NULL,sideband_lease_until=?,updated_at=? WHERE id=? AND sideband_worker_id=?",
        (retry_at, _now(), session_id, _voice_worker_id),
    )
    conn.commit()
    conn.close()


def _claim_sideband_session() -> dict | None:
    conn = get_db()
    now = _now()
    lease_until = (datetime.now(timezone.utc) + timedelta(seconds=25)).isoformat()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT id,user_id,provider_call_id,status,active_expires_at FROM voice_support_sessions "
            "WHERE status IN ('active','ending') AND provider_call_id IS NOT NULL "
            "AND (sideband_lease_until IS NULL OR sideband_lease_until<=?) ORDER BY created_at LIMIT 1",
            (now,),
        ).fetchone()
        if not row:
            conn.commit()
            return None
        conn.execute(
            "UPDATE voice_support_sessions SET sideband_worker_id=?,sideband_lease_until=?,updated_at=? WHERE id=?",
            (_voice_worker_id, lease_until, now, row["id"]),
        )
        conn.commit()
        return dict(row)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _session_state(session_id: str) -> dict | None:
    conn = get_db()
    row = conn.execute(
        "SELECT status,safety_outcome,alert_delivery_status,active_expires_at FROM voice_support_sessions WHERE id=?",
        (session_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def _voice_user(user_id: str) -> dict | None:
    from backend.database import get_user_by_id

    user = get_user_by_id(user_id)
    if not user or str(user.get("status", "")).lower() not in {"approved", "active"}:
        return None
    return user


def _normalize_spoken_choice(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9']+", " ", text.lower()).split())


def _spoken_confirmation(text: str) -> bool | None:
    normalized = _normalize_spoken_choice(text)
    if normalized in {
        "yes", "yes please", "yeah", "yeah please", "yep", "yep please", "sure", "okay", "ok",
        "go ahead", "please do", "i confirm", "confirm", "save it", "send it", "share it",
        "yes save it", "yes please save it", "yes send it", "yes please send it", "yes share it", "yes please share it",
    }:
        return True
    if normalized in {
        "no", "no thanks", "no thank you", "no please", "cancel", "cancel it", "never mind", "nevermind",
        "forget it", "stop", "dont", "dont save it", "do not save it", "dont send it", "do not send it",
        "dont share it", "do not share it", "no cancel", "no cancel it",
    }:
        return False
    return None


def _clear_voice_prompt_eligibility(session_id: str, action_id: str) -> None:
    conn = get_db()
    conn.execute(
        "UPDATE voice_support_sessions SET pending_action_prompted_at=NULL,updated_at=? "
        "WHERE id=? AND pending_action_id=? AND pending_action_source='voice' AND pending_action_state='awaiting_confirmation'",
        (_now(), session_id, action_id),
    )
    conn.commit()
    conn.close()


def _mark_voice_prompt_delivered(session_id: str, action_id: str) -> bool:
    conn = get_db()
    updated = conn.execute(
        "UPDATE voice_support_sessions SET pending_action_prompted_at=?,updated_at=? "
        "WHERE id=? AND pending_action_id=? AND pending_action_source='voice' "
        "AND pending_action_state='awaiting_confirmation' AND pending_action_expires_at>? "
        "AND status='active' AND active_expires_at>?",
        (_now(), _now(), session_id, action_id, _now(), _now()),
    )
    conn.commit()
    conn.close()
    return updated.rowcount == 1


def _response_audio_transcripts(response: dict) -> list[str]:
    transcripts = []
    for item in response.get("output", []):
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if not isinstance(content, dict):
                continue
            if content.get("type") == "audio" and isinstance(content.get("transcript"), str):
                transcripts.append(content["transcript"])
            elif content.get("type") == "audio_transcript" and isinstance(content.get("text"), str):
                transcripts.append(content["text"])
    return transcripts


async def _dispatch_realtime_tool(session_id: str, user: dict, name: str, arguments: str) -> dict:
    """Validate a model request against role-scoped tools, then reuse Voice actions."""
    allowed = {tool["name"] for tool in voice_tool_definitions(user)}
    if name not in allowed or len(arguments) > 10_000:
        return {"result": "NOT_ALLOWED", "message": "That MindGuard action is unavailable."}
    if not consume_rate_limit(f"voice-tools:{user['id']}:{session_id}", 30, 60):
        return {"result": "FAILED", "message": "Please wait a moment before asking MindGuard to check again."}
    try:
        request = VoiceActionRequest(action=name, payload=json.loads(arguments or "{}"))
    except (json.JSONDecodeError, TypeError, ValidationError):
        return {"result": "FAILED", "message": "I could not understand that action request."}
    conn = get_db()
    row = conn.execute(
        "SELECT safety_outcome FROM voice_support_sessions WHERE id=? AND user_id=? AND status='active' AND active_expires_at>?",
        (session_id, user["id"], _now()),
    ).fetchone()
    conn.close()
    if not row:
        return {"result": "FAILED", "message": "This voice session has ended."}
    if row["safety_outcome"] not in {"none", NORMAL}:
        return {"result": "SAFETY_PRIORITY", "message": "Safety support takes priority. No ordinary action was taken."}
    try:
        return await _voice_action_impl(session_id, request, user, source="voice")
    except HTTPException as exc:
        code = "NOT_ALLOWED" if exc.status_code in {403, 404} else "FAILED"
        return {"result": code, "message": "I could not complete that MindGuard action. No change should be assumed."}
    except Exception:
        logger.warning("Voice tool dispatch failed for session %s and action %s", session_id, name, exc_info=False)
        return {"result": "FAILED", "message": "I could not complete that MindGuard action. No change should be assumed."}


async def _resolve_spoken_confirmation(session_id: str, user: dict, transcript: str, socket) -> dict | None:
    """Only resolve a fresh, server-prompted Voice action from an unambiguous reply."""
    decision = _spoken_confirmation(transcript)
    conn = get_db()
    row = conn.execute(
        "SELECT pending_action_id,pending_action_expires_at,pending_action_source,pending_action_prompted_at,pending_action_state,safety_outcome "
        "FROM voice_support_sessions WHERE id=? AND user_id=? AND status='active' AND active_expires_at>?",
        (session_id, user["id"], _now()),
    ).fetchone()
    conn.close()
    if not row or not row["pending_action_id"] or row["pending_action_state"] != "awaiting_confirmation":
        return None
    action_id = row["pending_action_id"]
    if row["pending_action_source"] != "voice" or not row["pending_action_prompted_at"]:
        return None
    if not row["pending_action_expires_at"] or row["pending_action_expires_at"] <= _now():
        _finish_voice_action(session_id, action_id, "expired")
        return None
    if row["safety_outcome"] not in {"none", NORMAL}:
        _clear_voice_prompt_eligibility(session_id, action_id)
        return None
    if decision is None:
        _clear_voice_prompt_eligibility(session_id, action_id)
        return None
    result = await _confirm_voice_action_impl(
        session_id, action_id, VoiceActionConfirmation(confirmed=decision), user
    )
    if not decision:
        result = {"result": result.get("result", "SUCCESS"), "message": "Okay. Nothing was saved or shared."}
    followup_prompt = result.get("confirmation_prompt") if result.get("result") == "CONFIRMATION_REQUIRED" else None
    message = str(result.get("message") or "The action was not completed.")[:500]
    with suppress(Exception):
        await socket.send(json.dumps({"type": "response.cancel"}))
        await socket.send(json.dumps({
            "type": "response.create",
            "response": {
                "modalities": ["audio", "text"],
                "tools": [],
                "tool_choice": "none",
                "instructions": (
                    "Ask this exact next confirmation question, then wait without acting: " + json.dumps(followup_prompt)
                    if followup_prompt else
                    "The server has resolved the user's immediate confirmation. Say this verified result briefly and "
                    "do not add unsupported account facts: " + json.dumps({"result": result.get("result"), "message": message})
                ),
            },
        }))
    return {"pending_action_id": action_id, "prompt": followup_prompt} if followup_prompt else {}


def _record_safety_state(session_id: str, user_id: str, state: str) -> tuple[bool, str]:
    """Persist only a coarse server-derived state; transcript remains ephemeral."""
    severity = {NORMAL: 0, "none": 0, DISTRESS: 1, HEIGHTENED_CONCERN: 2, POTENTIAL_IMMEDIATE_DANGER: 3, "user_requested_help": 3}
    conn = get_db()
    row = conn.execute(
        "SELECT s.safety_outcome,s.status,s.alert_delivery_status,u.role_type,u.user_category "
        "FROM voice_support_sessions s JOIN users u ON u.id=s.user_id WHERE s.id=? AND s.user_id=?",
        (session_id, user_id),
    ).fetchone()
    if not row or row["status"] != "active" or severity.get(state, 0) <= severity.get(row["safety_outcome"], 0):
        conn.close()
        return False, "no_authorized_recipient"
    now = _now()
    recipient = None
    delivery = row["alert_delivery_status"]
    if state == POTENTIAL_IMMEDIATE_DANGER and not delivery:
        recipient, _kind = _care_recipient(conn, {"id": user_id, "role_type": row["role_type"], "user_category": row["user_category"]})
        delivery = "no_authorized_recipient"
        if recipient:
            try:
                create_notification(
                    recipient,
                    "Urgent voice-support follow-up",
                    "A person in your authorized care scope may need immediate human follow-up. Open the alert queue; no audio recording or transcript was retained.",
                    "crisis",
                )
                delivery = "delivered"
            except Exception:
                delivery = "failed"
    conn.execute(
        "UPDATE voice_support_sessions SET safety_outcome=?,alert_recipient_id=COALESCE(?,alert_recipient_id),"
        "alert_delivery_status=COALESCE(?,alert_delivery_status),"
        "pending_action_id=CASE WHEN ? IN ('distress','heightened_concern','potential_immediate_danger') THEN NULL ELSE pending_action_id END,"
        "pending_action_type=CASE WHEN ? IN ('distress','heightened_concern','potential_immediate_danger') THEN NULL ELSE pending_action_type END,"
        "pending_action_payload_encrypted=CASE WHEN ? IN ('distress','heightened_concern','potential_immediate_danger') THEN NULL ELSE pending_action_payload_encrypted END,"
        "pending_action_expires_at=CASE WHEN ? IN ('distress','heightened_concern','potential_immediate_danger') THEN NULL ELSE pending_action_expires_at END,"
        "pending_action_source=CASE WHEN ? IN ('distress','heightened_concern','potential_immediate_danger') THEN NULL ELSE pending_action_source END,"
        "pending_action_confirmation_prompt=CASE WHEN ? IN ('distress','heightened_concern','potential_immediate_danger') THEN NULL ELSE pending_action_confirmation_prompt END,"
        "pending_action_prompted_at=CASE WHEN ? IN ('distress','heightened_concern','potential_immediate_danger') THEN NULL ELSE pending_action_prompted_at END,"
        "pending_action_state=CASE WHEN ? IN ('distress','heightened_concern','potential_immediate_danger') THEN 'cancelled' ELSE pending_action_state END,"
        "navigation_event_id=CASE WHEN ? IN ('distress','heightened_concern','potential_immediate_danger') THEN NULL ELSE navigation_event_id END,"
        "navigation_route_id=CASE WHEN ? IN ('distress','heightened_concern','potential_immediate_danger') THEN NULL ELSE navigation_route_id END,"
        "updated_at=? WHERE id=?",
        (state, recipient, delivery if state == POTENTIAL_IMMEDIATE_DANGER else None, state, state, state, state, state, state, state, state, state, state, now, session_id),
    )
    conn.commit()
    conn.close()
    write_audit(user_id, row["role_type"], "VOICE_SAFETY_STATE_UPDATED", "voice_session", session_id, payload={"safety_state": state, "transcript_stored": False})
    if state == POTENTIAL_IMMEDIATE_DANGER:
        write_audit(user_id, row["role_type"], "VOICE_SAFETY_ESCALATION", "voice_session", session_id, payload={"delivery_status": delivery, "recipient_present": bool(recipient), "transcript_stored": False})
    return True, delivery or "no_authorized_recipient"


def _record_user_requested_help(session_id: str, user: dict, request: Request) -> tuple[str, str]:
    conn = get_db()
    row = conn.execute("SELECT status,alert_delivery_status FROM voice_support_sessions WHERE id=? AND user_id=?", (session_id, user["id"])).fetchone()
    if not row or row["status"] != "active":
        conn.close()
        raise HTTPException(409, "This voice-support session is no longer active")
    recipient, _kind = _care_recipient(conn, user)
    delivery = "no_authorized_recipient"
    if recipient and not row["alert_delivery_status"]:
        try:
            create_notification(recipient, "Urgent voice-support follow-up", "A person in your authorized care scope explicitly requested human follow-up. No audio recording or transcript was retained.", "crisis")
            delivery = "delivered"
        except Exception:
            delivery = "failed"
    now = _now()
    conn.execute("UPDATE voice_support_sessions SET safety_outcome='user_requested_help',alert_recipient_id=COALESCE(?,alert_recipient_id),alert_delivery_status=COALESCE(alert_delivery_status,?),updated_at=? WHERE id=?", (recipient, delivery, now, session_id))
    conn.commit()
    conn.close()
    write_audit(user["id"], user["role_type"], "VOICE_SUPPORT_REQUESTED", "voice_session", session_id, payload={"delivery_status": delivery, "recipient_present": bool(recipient), "transcript_stored": False}, ip=request.client.host if request.client else None)
    minor_conn = get_db()
    minor = _is_minor(minor_conn, user)
    minor_conn.close()
    return delivery, _urgent_fallback_message(minor)


async def _monitor_sideband(row: dict) -> None:
    session_id = row["id"]
    session = _session_state(session_id)
    if not session:
        _release_sideband_lease(session_id)
        return
    api_key = get_secret("OPENAI_API_KEY").strip()
    if not api_key:
        _release_sideband_lease(session_id)
        return
    user = _voice_user(row["user_id"])
    if not user:
        _mark_session_ending(session_id, final_status="failed", reason="voice_user_unavailable")
        return
    provider = OpenAIRealtimeProvider(api_key)
    socket = None
    pending_prompt_action_id = None
    pending_prompt_text = None
    expecting_prompt_response = False
    prompt_response_id = None
    try:
        async with provider.sideband(row["provider_call_id"]) as socket:
            control_id = "mindguard_voice_tools_" + uuid.uuid4().hex
            conn = get_db()
            recipient, _kind = _care_recipient(conn, user)
            minor = _is_minor(conn, user)
            conn.close()
            await socket.send(json.dumps({
                "type": "session.update",
                "event_id": control_id,
                "session": {
                    "instructions": _instructions(minor, bool(recipient)),
                    "tools": voice_tool_definitions(user),
                    "tool_choice": "auto",
                },
            }))
            deadline = time.monotonic() + 8
            configured = False
            while time.monotonic() < deadline:
                event = json.loads(await asyncio.wait_for(socket.recv(), timeout=max(0.1, deadline - time.monotonic())))
                if event.get("type") == "error" and event.get("event_id") == control_id:
                    raise VoiceProviderError("Realtime rejected the server-controlled Voice action configuration")
                if event.get("type") == "session.updated" and event.get("client_event_id") == control_id:
                    configured = True
                    break
                if event.get("type") == "session.closed":
                    return
            if not configured:
                raise VoiceProviderError("Realtime did not acknowledge Voice action configuration")

            # The browser does not receive SDP until this exact server-side
            # configuration is acknowledged, so tool execution stays owned by
            # the backend from the start of the conversation.
            connected_at = _now()
            conn = get_db()
            conn.execute(
                "UPDATE voice_support_sessions SET sideband_connected_at=?,updated_at=? "
                "WHERE id=? AND provider_call_id=? AND status IN ('active','ending')",
                (connected_at, connected_at, session_id, row["provider_call_id"]),
            )
            conn.commit()
            conn.close()
            conn = get_db()
            pending = conn.execute(
                "SELECT pending_action_id,pending_action_source,pending_action_confirmation_prompt,pending_action_prompted_at,pending_action_state,safety_outcome "
                "FROM voice_support_sessions WHERE id=? AND user_id=?",
                (session_id, row["user_id"]),
            ).fetchone()
            conn.close()
            if (
                pending and pending["pending_action_id"] and pending["pending_action_source"] == "voice"
                and pending["pending_action_state"] == "awaiting_confirmation" and not pending["pending_action_prompted_at"]
                and pending["safety_outcome"] in {"none", NORMAL}
            ):
                pending_prompt_action_id = pending["pending_action_id"]
                try:
                    pending_prompt_text = decrypt_pii(pending["pending_action_confirmation_prompt"])
                except (TypeError, ValueError, RuntimeError):
                    raise VoiceProviderError("Pending Voice confirmation could not be read securely")
                expecting_prompt_response = True
                await socket.send(json.dumps({
                    "type": "response.create",
                    "response": {
                        "modalities": ["audio", "text"],
                        "tools": [],
                        "tool_choice": "none",
                        "instructions": "Ask the user this exact confirmation question and then wait without acting: " + json.dumps(pending_prompt_text),
                    },
                }))
            while True:
                current = _session_state(session_id)
                if not current or current["status"] in {"completed", "failed", "expired"}:
                    return
                now = _now()
                if current["status"] == "ending" or current["active_expires_at"] <= now:
                    with suppress(Exception):
                        await socket.send(json.dumps({"type": "session.close"}))
                    _mark_session_ending(session_id, final_status="expired" if current["active_expires_at"] <= now else "completed", reason="session_time_limit" if current["active_expires_at"] <= now else None)
                    return
                conn = get_db()
                lease_until = (datetime.now(timezone.utc) + timedelta(seconds=25)).isoformat()
                conn.execute("UPDATE voice_support_sessions SET sideband_lease_until=?,updated_at=? WHERE id=? AND sideband_worker_id=?", (lease_until, now, session_id, _voice_worker_id))
                conn.commit()
                conn.close()
                try:
                    event = json.loads(await asyncio.wait_for(socket.recv(), timeout=2))
                except asyncio.TimeoutError:
                    continue
                event_type = event.get("type")
                transcript = event.get("transcript")
                if event_type in {"conversation.item.input_audio_transcription.completed", "input_audio_transcription.completed"} and isinstance(transcript, str) and transcript.strip():
                    state = await classify_voice_text(transcript[:4000], api_key)
                    changed, delivery = _record_safety_state(session_id, row["user_id"], state)
                    if changed and state in {HEIGHTENED_CONCERN, POTENTIAL_IMMEDIATE_DANGER}:
                        instructions = (
                            "Respond calmly and briefly to the user's latest statement. Do not diagnose or claim to know their risk level. Ask one clear question about immediate safety when appropriate. Encourage contacting a trusted person or an appropriate local professional. If the user indicates immediate danger, tell them to contact Kenya emergency services on 999, 112, or 911 or go to the nearest health facility. Never say an alert was sent unless the application confirms delivery."
                        )
                        with suppress(Exception):
                            await socket.send(json.dumps({"type": "response.cancel"}))
                            await socket.send(json.dumps({"type": "response.create", "response": {"modalities": ["audio", "text"], "instructions": instructions, "tools": [], "tool_choice": "none"}}))
                        if state == POTENTIAL_IMMEDIATE_DANGER and delivery not in {"delivered", "acknowledged"}:
                            minor_conn = get_db()
                            user_context = minor_conn.execute("SELECT role_type,user_category FROM users WHERE id=?", (row["user_id"],)).fetchone()
                            minor = _is_minor(minor_conn, {"id": row["user_id"], "role_type": user_context["role_type"], "user_category": user_context["user_category"]}) if user_context else False
                            minor_conn.close()
                            with suppress(Exception):
                                await socket.send(json.dumps({"type": "session.update", "session": {"instructions": _instructions(minor, False) + " " + _urgent_fallback_message(minor)}}))
                    elif state in {"none", NORMAL}:
                        resolution = await _resolve_spoken_confirmation(session_id, user, transcript, socket)
                        if resolution and resolution.get("prompt"):
                            pending_prompt_action_id = resolution["pending_action_id"]
                            pending_prompt_text = resolution["prompt"]
                            prompt_response_id = None
                            expecting_prompt_response = True
                elif event_type == "response.created" and expecting_prompt_response:
                    response = event.get("response") or {}
                    prompt_response_id = response.get("id")
                    expecting_prompt_response = False
                elif event_type == "response.done":
                    response = event.get("response") or {}
                    if (
                        pending_prompt_action_id and prompt_response_id
                        and response.get("id") == prompt_response_id and response.get("status") == "completed"
                    ):
                        expected = _normalize_spoken_choice(pending_prompt_text or "")
                        transcript_texts = [_normalize_spoken_choice(item) for item in _response_audio_transcripts(response)]
                        if expected and any(expected in item for item in transcript_texts):
                            _mark_voice_prompt_delivered(session_id, pending_prompt_action_id)
                        pending_prompt_action_id = None
                        pending_prompt_text = None
                        prompt_response_id = None

                    if response.get("status") != "completed":
                        continue
                    function_calls = [
                        item for item in response.get("output", [])
                        if isinstance(item, dict) and item.get("type") == "function_call" and item.get("status") == "completed"
                    ]
                    if not function_calls:
                        continue
                    tool_user = _voice_user(row["user_id"])
                    if not tool_user:
                        continue
                    next_prompt = None
                    for function_call in function_calls:
                        call_id = function_call.get("call_id")
                        name = function_call.get("name")
                        arguments = function_call.get("arguments", "{}")
                        if not isinstance(call_id, str) or len(call_id) > 200:
                            continue
                        if not isinstance(name, str) or not isinstance(arguments, str):
                            result = {"result": "NOT_ALLOWED", "message": "That MindGuard action is unavailable."}
                        else:
                            result = await _dispatch_realtime_tool(session_id, tool_user, name, arguments)
                        await socket.send(json.dumps({
                            "type": "conversation.item.create",
                            "item": {"type": "function_call_output", "call_id": call_id, "output": json.dumps(result, separators=(",", ":"))},
                        }))
                        if result.get("result") == "CONFIRMATION_REQUIRED" and result.get("pending_action_id"):
                            next_prompt = (result["pending_action_id"], result.get("confirmation_prompt", ""))
                    if next_prompt:
                        pending_prompt_action_id, pending_prompt_text = next_prompt
                        prompt_response_id = None
                        expecting_prompt_response = True
                    await socket.send(json.dumps({"type": "response.create"}))
                elif event_type == "session.closed":
                    _mark_session_ending(session_id)
                    return
    except asyncio.CancelledError:
        if socket is not None:
            with suppress(Exception):
                await socket.send(json.dumps({"type": "session.close"}))
        _mark_session_ending(session_id, final_status="failed", reason="server_shutdown")
        _release_sideband_lease(session_id)
        raise
    except Exception:
        # Log only operational identifiers and exception class, never event or
        # transcript payloads. A later lease lets a surviving worker reconnect.
        logger.warning("Voice sideband disconnected for session %s", session_id, exc_info=False)
        conn = get_db()
        conn.execute("UPDATE voice_support_sessions SET status='ending',failure_reason='sideband_disconnected',updated_at=? WHERE id=? AND status='active'", (_now(), session_id))
        conn.commit()
        conn.close()
        _release_sideband_lease(session_id)


async def voice_sideband_maintenance_loop() -> None:
    """Claim monitored sessions from shared DB state; leases recover on restart."""
    while True:
        try:
            row = _claim_sideband_session()
            if row:
                task = asyncio.create_task(_monitor_sideband(row), name=f"voice-sideband-{row['id']}")
                _voice_monitor_tasks.add(task)
                task.add_done_callback(_voice_monitor_tasks.discard)
            else:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            for task in list(_voice_monitor_tasks):
                task.cancel()
            if _voice_monitor_tasks:
                await asyncio.gather(*_voice_monitor_tasks, return_exceptions=True)
            raise
        except Exception:
            logger.exception("Voice sideband maintenance iteration failed")
            await asyncio.sleep(2)


@router.get("/availability")
async def voice_availability(user: dict = Depends(require_auth)):
    conn = get_db(); recipient, kind = _care_recipient(conn, user); minor = _is_minor(conn, user); conn.close()
    configuration_blockers = []
    if not get_secret("OPENAI_API_KEY").strip():
        configuration_blockers.append("OpenAI Realtime provider is not configured")
    if not _safety_salt():
        configuration_blockers.append("A private safety-identifier salt of at least 32 characters is not configured")
    if not _server_side_controls_ready():
        configuration_blockers.append("Server-side Realtime monitoring and shutdown are not enabled")
    return {
        "enabled": _enabled("VOICE_SUPPORT_ENABLED"),
        "review_gate_ready": _launch_ready(),
        "configuration_ready": not configuration_blockers,
        "configuration_blockers": configuration_blockers,
        "care_recipient_available": bool(recipient),
        "care_recipient_type": kind,
        "role_type": user.get("role_type"),
        "workplace_checkin_available": user.get("role_type") == "workplace_employee",
        "is_minor": minor,
        "language": "English",
        "stores_audio": False,
        "stores_transcripts": False,
        "server_side_controls_ready": _server_side_controls_ready(),
        "summary_retention_days": int(os.getenv("VOICE_SUMMARY_RETENTION_DAYS", "30")),
    }


@router.post("/sessions", status_code=201)
async def create_voice_session(data: VoiceSessionCreate, request: Request, user: dict = Depends(require_auth)):
    if not _enabled("VOICE_SUPPORT_ENABLED"):
        raise HTTPException(503, "Voice support is not enabled for this environment")
    if not _launch_ready():
        raise HTTPException(503, "Voice support is awaiting clinical, safeguarding, privacy, and accessibility review")
    if not _server_side_controls_ready():
        raise HTTPException(503, "Voice support is awaiting server-side Realtime monitoring and shutdown")
    if not data.accepted_notice:
        raise HTTPException(400, "Accept the voice-support notice before starting")
    api_key = get_secret("OPENAI_API_KEY").strip()
    safety_salt = _safety_salt()
    if not api_key or not safety_salt:
        raise HTTPException(503, "Voice support provider and privacy-preserving safety identifier are not fully configured")
    daily_limit = int(os.getenv("VOICE_DAILY_SESSION_LIMIT", "5"))
    if not consume_rate_limit(f"voice-session:{user['id']}", daily_limit, 86400):
        raise HTTPException(429, "Daily voice-support session limit reached")
    max_duration = _max_session_seconds()
    session_id = str(uuid.uuid4())
    retention = int(os.getenv("VOICE_SUMMARY_RETENTION_DAYS", "30"))
    if retention < 1 or retention > 365:
        retention = 30
    conn = get_db()
    conn.execute("BEGIN IMMEDIATE")
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()
    conn.execute(
        "UPDATE voice_support_sessions SET status='expired', ended_at=COALESCE(ended_at,?), updated_at=? "
        "WHERE user_id=? AND status IN ('created','connecting','connecting_call') AND active_expires_at<=? AND provider_call_id IS NULL",
        (now, now, user["id"], now),
    )
    conn.execute(
        "UPDATE voice_support_sessions SET status='ending',updated_at=? WHERE user_id=? AND status='active' AND active_expires_at<=?",
        (now, user["id"], now),
    )
    active = conn.execute(
        "SELECT id FROM voice_support_sessions WHERE user_id=? AND status IN ('created','connecting','connecting_call','active','ending') LIMIT 1",
        (user["id"],),
    ).fetchone()
    if active:
        conn.commit()
        conn.close()
        raise HTTPException(409, "End your current voice-support session before starting another")
    recipient, recipient_type = _care_recipient(conn, user)
    minor = _is_minor(conn, user)
    conn.execute(
        "INSERT INTO voice_support_sessions (id,user_id,status,consented_at,consent_version,exercise,safety_outcome,alert_recipient_id,active_expires_at,expires_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (session_id, user["id"], "created", now, CONSENT_NOTICE_VERSION, data.exercise, "none", recipient, (now_dt + timedelta(seconds=max_duration)).isoformat(), (now_dt + timedelta(days=retention)).isoformat(), now, now),
    )
    conn.commit()
    conn.close()
    safety_id = hashlib.sha256((str(user["id"]) + safety_salt).encode()).hexdigest()
    model = os.getenv("OPENAI_REALTIME_MODEL", "gpt-realtime-2.1")
    payload = {
        "session": {
            "type": "realtime",
            "model": model,
            "instructions": _instructions(minor, bool(recipient)),
            "tools": voice_tool_definitions(user),
            "tool_choice": "auto",
            "audio": {
                "input": {"transcription": {"model": os.getenv("OPENAI_TRANSCRIPTION_MODEL", "gpt-4o-mini-transcribe")}},
                "output": {"voice": os.getenv("OPENAI_REALTIME_VOICE", "marin")},
            },
        }
    }
    try:
        secret = await OpenAIRealtimeProvider(api_key).create_client_secret(payload, safety_id)
    except VoiceProviderError as exc:
        _mark_session_ending(session_id, final_status="failed", reason="provider_session_creation_failed")
        raise HTTPException(503, str(exc))
    now = _now()
    conn = get_db()
    conn.execute(
        "UPDATE voice_support_sessions SET provider_session_id=?,client_secret_encrypted=?,status='connecting',updated_at=? WHERE id=? AND user_id=? AND status='created'",
        (secret.get("id") or secret.get("session", {}).get("id"), encrypt_pii(secret["value"]), now, session_id, user["id"]),
    )
    conn.commit()
    conn.close()
    write_audit(user["id"], user["role_type"], "VOICE_SESSION_STARTED", "voice_session", session_id, payload={"exercise": data.exercise, "care_recipient_type": recipient_type, "audio_stored": False}, ip=request.client.host if request.client else None)
    return {"session_id": session_id, "status": "connecting", "model": model, "consent_version": CONSENT_NOTICE_VERSION, "care_recipient_available": bool(recipient), "care_recipient_type": recipient_type, "max_duration_seconds": max_duration}


@router.post("/sessions/{session_id}/connect")
async def connect_voice_session(session_id: str, data: VoiceWebrtcOffer, request: Request, user: dict = Depends(require_auth)):
    conn = get_db()
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = _session_for_user(conn, session_id, user["id"])
    except HTTPException:
        conn.rollback()
        conn.close()
        raise
    if row["status"] != "connecting" or not row["client_secret_encrypted"]:
        conn.close()
        raise HTTPException(409, "This voice session is not waiting for a connection")
    if row["active_expires_at"] <= _now():
        conn.close()
        _mark_session_ending(session_id, final_status="expired", reason="session_expired_before_connect")
        raise HTTPException(410, "The voice-support session time limit has ended")
    client_secret = decrypt_pii(row["client_secret_encrypted"])
    claimed = conn.execute("UPDATE voice_support_sessions SET status='connecting_call',updated_at=? WHERE id=? AND user_id=? AND status='connecting'", (_now(), session_id, user["id"]))
    if claimed.rowcount != 1:
        conn.rollback()
        conn.close()
        raise HTTPException(409, "This voice session is already connecting")
    conn.commit()
    conn.close()
    api_key = get_secret("OPENAI_API_KEY").strip()
    if not api_key or not client_secret:
        _mark_session_ending(session_id, final_status="failed", reason="provider_session_credential_unavailable")
        raise HTTPException(503, "Voice support could not establish its secure connection")
    try:
        answer_sdp, call_id = await OpenAIRealtimeProvider(api_key).connect_webrtc(client_secret, data.sdp)
    except VoiceProviderError as exc:
        _mark_session_ending(session_id, final_status="failed", reason="provider_connection_failed")
        raise HTTPException(503, str(exc))
    now = _now()
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE voice_support_sessions SET provider_call_id=?,client_secret_encrypted=NULL,status='active',started_at=COALESCE(started_at,?),updated_at=? WHERE id=? AND user_id=? AND status='connecting_call'",
            (call_id, now, now, session_id, user["id"]),
        )
        if conn.total_changes == 0:
            conn.rollback()
            raise HTTPException(409, "This voice session has already been connected or ended")
        conn.commit()
    except HTTPException:
        raise
    except Exception as exc:
        conn.rollback()
        _mark_session_ending(session_id, final_status="failed", reason="provider_call_binding_failed")
        raise HTTPException(503, "Unable to securely attach server-side voice controls") from exc
    finally:
        conn.close()
    write_audit(user["id"], user["role_type"], "VOICE_SESSION_CONNECTED", "voice_session", session_id, payload={"server_side_controls": True}, ip=request.client.host if request.client else None)
    # Sideband setup is asynchronous so it can be managed/recovered by the
    # shared worker lease. Never release the provider SDP answer to the
    # browser until server-side monitoring is confirmed for this exact call.
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        conn = get_db()
        monitored = conn.execute(
            "SELECT status,sideband_connected_at FROM voice_support_sessions WHERE id=? AND user_id=?",
            (session_id, user["id"]),
        ).fetchone()
        conn.close()
        if monitored and monitored["status"] == "active" and monitored["sideband_connected_at"]:
            return {"answer_sdp": answer_sdp, "status": "active"}
        if not monitored or monitored["status"] != "active":
            break
        await asyncio.sleep(0.1)
    conn = get_db()
    conn.execute(
        "UPDATE voice_support_sessions SET status='ending',failure_reason='sideband_attach_timeout',updated_at=? "
        "WHERE id=? AND user_id=? AND status='active'",
        (_now(), session_id, user["id"]),
    )
    conn.commit()
    conn.close()
    raise HTTPException(503, "Voice support could not attach its server-side safety controls")


@router.get("/sessions/{session_id}/state")
async def voice_session_state(session_id: str, user: dict = Depends(require_auth)):
    conn = get_db()
    row = _session_for_user(conn, session_id, user["id"])
    if row["status"] == "active" and row["active_expires_at"] <= _now():
        conn.execute(
            "UPDATE voice_support_sessions SET status='ending',pending_action_id=NULL,"
            "pending_action_type=NULL,pending_action_payload_encrypted=NULL,"
            "pending_action_expires_at=NULL,pending_action_source=NULL,pending_action_confirmation_prompt=NULL,"
            "pending_action_prompted_at=NULL,pending_action_state='expired',updated_at=? "
            "WHERE id=? AND status='active'",
            (_now(), session_id),
        )
        conn.commit()
        row = conn.execute("SELECT status,safety_outcome,alert_delivery_status,pending_action_id,pending_action_type,pending_action_expires_at,pending_action_state,pending_action_source,pending_action_confirmation_prompt,pending_action_prompted_at,navigation_event_id,navigation_route_id FROM voice_support_sessions WHERE id=?", (session_id,)).fetchone()
    if row["pending_action_id"] and row["pending_action_expires_at"] and row["pending_action_expires_at"] <= _now():
        conn.execute(
            "UPDATE voice_support_sessions SET pending_action_id=NULL,pending_action_type=NULL,pending_action_payload_encrypted=NULL,"
            "pending_action_expires_at=NULL,pending_action_source=NULL,pending_action_confirmation_prompt=NULL,"
            "pending_action_prompted_at=NULL,pending_action_state='expired',updated_at=? WHERE id=? AND pending_action_id=?",
            (_now(), session_id, row["pending_action_id"]),
        )
        conn.commit()
        row = conn.execute("SELECT status,safety_outcome,alert_delivery_status,pending_action_id,pending_action_type,pending_action_expires_at,pending_action_state,pending_action_source,pending_action_confirmation_prompt,pending_action_prompted_at,navigation_event_id,navigation_route_id FROM voice_support_sessions WHERE id=?", (session_id,)).fetchone()
    conn.close()
    pending = None
    if row["pending_action_id"] and row["pending_action_state"] == "awaiting_confirmation":
        action = row["pending_action_type"]
        try:
            confirmation_prompt = decrypt_pii(row["pending_action_confirmation_prompt"])
        except (TypeError, ValueError, RuntimeError):
            _finish_voice_action(session_id, row["pending_action_id"], "failed")
            confirmation_prompt = None
        if confirmation_prompt:
            pending = {
                "id": row["pending_action_id"], "action": action,
                "expires_at": row["pending_action_expires_at"],
                "source": row["pending_action_source"],
                "sensitivity": SHARE_REQUIRED if action in {"propose_summary_share"} or (action == "propose_human_support" and user.get("role_type") == "workplace_employee") else CONFIRM_REQUIRED,
                "confirmation_prompt": confirmation_prompt,
                "voice_confirmation_ready": bool(row["pending_action_prompted_at"]),
            }
    route_ids = set(NAVIGATION_TARGETS.values()) | {"workplace-checkins", "workplace-support"}
    navigation = None
    if row["navigation_event_id"] and row["navigation_route_id"] in route_ids:
        navigation = {"id": row["navigation_event_id"], "route_id": row["navigation_route_id"]}
    return {"status": row["status"], "safety_state": row["safety_outcome"], "alert_delivery_status": row["alert_delivery_status"], "pending_action": pending, "navigation_event": navigation}


@router.post("/sessions/{session_id}/request-help")
async def request_voice_help(session_id: str, request: Request, user: dict = Depends(require_auth)):
    delivery, fallback = _record_user_requested_help(session_id, user, request)
    return {
        "requested": True,
        "delivery_status": delivery,
        "message": "An in-app alert was sent to your authorized care professional." if delivery == "delivered" else fallback,
    }


@router.post("/sessions/{session_id}/safety-event")
async def legacy_voice_safety_event(session_id: str, user: dict = Depends(require_auth)):
    raise HTTPException(410, "Transcript safety is handled by the server. Use the explicit request-help action to ask for human follow-up.")


@router.post("/sessions/{session_id}/close")
async def close_voice_session(session_id: str, data: VoiceClose, request: Request, user: dict = Depends(require_auth)):
    conn = get_db(); row = _session_for_user(conn, session_id, user["id"])
    now = _now()
    if row["status"] == "expired" or row["active_expires_at"] <= now:
        conn.execute("UPDATE voice_support_sessions SET status='expired',summary_encrypted=NULL,pending_action_id=NULL,pending_action_type=NULL,pending_action_payload_encrypted=NULL,pending_action_expires_at=NULL,pending_action_source=NULL,pending_action_confirmation_prompt=NULL,pending_action_prompted_at=NULL,pending_action_state='expired',ended_at=COALESCE(ended_at,?),updated_at=? WHERE id=?", (now, now, session_id))
        conn.commit(); conn.close()
        raise HTTPException(410, "The voice-support session time limit has ended; no summary was saved")
    if row["status"] in {"completed", "failed"}:
        conn.close()
        return {"ok": True, "status": row["status"]}
    target_status = "ending" if row["provider_call_id"] and row["status"] in {"active", "ending"} else "completed"
    conn.execute(
        "UPDATE voice_support_sessions SET status=?,exercise=COALESCE(?,exercise),client_secret_encrypted=NULL,pending_action_id=NULL,pending_action_type=NULL,pending_action_payload_encrypted=NULL,pending_action_expires_at=NULL,pending_action_source=NULL,pending_action_confirmation_prompt=NULL,pending_action_prompted_at=NULL,pending_action_state='expired',ended_at=CASE WHEN ?='completed' THEN COALESCE(ended_at,?) ELSE ended_at END,updated_at=? WHERE id=?",
        (target_status, data.exercise, target_status, now, now, session_id),
    )
    conn.commit(); conn.close()
    action = "VOICE_SESSION_END_REQUESTED" if target_status == "ending" else "VOICE_SESSION_COMPLETED"
    write_audit(user["id"], user["role_type"], action, "voice_session", session_id, payload={"summary_saved": False, "audio_stored": False, "transcript_stored": False}, ip=request.client.host if request.client else None)
    return {"ok": True, "status": target_status}


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
    rows = conn.execute("SELECT s.id,s.user_id AS subject_user_id,u.name AS subject_name,u.role_type,u.user_category,s.status,s.safety_outcome,s.alert_delivery_status,s.alert_acknowledged_at,s.created_at,s.updated_at FROM voice_support_sessions s JOIN users u ON u.id=s.user_id WHERE s.alert_recipient_id=? AND s.safety_outcome IN ('potential_immediate_danger','user_requested_help') ORDER BY s.updated_at DESC LIMIT 100", (user["id"],)).fetchall()
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
    conn.execute("UPDATE voice_support_sessions SET summary_encrypted=NULL,pending_action_id=NULL,pending_action_type=NULL,pending_action_payload_encrypted=NULL,pending_action_expires_at=NULL,pending_action_source=NULL,pending_action_confirmation_prompt=NULL,pending_action_prompted_at=NULL,pending_action_state='expired',status=CASE WHEN status='active' THEN 'expired' ELSE status END,updated_at=? WHERE expires_at<=?", (now, now))
    conn.commit(); conn.close()
    return len(rows)
