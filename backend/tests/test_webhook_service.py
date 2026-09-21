"""Tests for ESP (Resend/Svix) webhook verification + delivery-event processing."""

import base64
import hashlib
import hmac
import json
import time

import pytest

from services.webhook_service import (
    handle_webhook,
    process_email_event,
    verify_webhook_signature,
)

SECRET = "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw"


def _sign(
    payload: str,
    msg_id: str = "msg_test123",
    timestamp: str | None = None,
    secret: str = SECRET,
):
    ts = timestamp or str(int(time.time()))
    key = base64.b64decode(secret.removeprefix("whsec_"))
    sig = base64.b64encode(
        hmac.new(key, f"{msg_id}.{ts}.{payload}".encode(), hashlib.sha256).digest()
    ).decode()
    return (
        {
            "svix-id": msg_id,
            "svix-timestamp": ts,
            "svix-signature": f"v1,{sig}",
        },
        msg_id,
        ts,
    )


def _bounce_payload(email_id: str = "resend-email-1"):
    return {
        "type": "email.bounced",
        "data": {
            "created_at": "2026-01-15T10:00:00.000Z",
            "email_id": email_id,
            "from": "MindGuard <noreply@mindguard.ai>",
            "subject": "Consent request",
            "to": ["parent@example.com"],
            "bounce": {"code": "554", "description": "mailbox unavailable"},
        },
    }


# ── Signature verification ────────────────────────────────────────────


def test_valid_signature_passes():
    payload = json.dumps(_bounce_payload())
    headers, _, _ = _sign(payload)
    assert verify_webhook_signature(payload, headers, SECRET) is True


def test_wrong_secret_fails():
    payload = json.dumps(_bounce_payload())
    other_secret = "whsec_" + base64.b64encode(b"wrong secret material").decode()
    headers, _, _ = _sign(payload, secret=other_secret)
    assert verify_webhook_signature(payload, headers, SECRET) is False


def test_no_secret_fails_closed():
    payload = json.dumps(_bounce_payload())
    headers, _, _ = _sign(payload)
    assert verify_webhook_signature(payload, headers, "") is False


def test_stale_timestamp_fails():
    payload = json.dumps(_bounce_payload())
    headers, _, _ = _sign(payload, timestamp=str(int(time.time()) - 3600))
    assert (
        verify_webhook_signature(payload, headers, SECRET, tolerance_seconds=300)
        is False
    )


def test_missing_headers_fail():
    assert verify_webhook_signature("{}", {}, SECRET) is False
    assert verify_webhook_signature("{}", {"svix-id": "x"}, SECRET) is False


def test_mutated_body_fails():
    payload = json.dumps(_bounce_payload())
    headers, _, _ = _sign(payload)
    assert verify_webhook_signature(payload + " ", headers, SECRET) is False


def test_multiple_signatures_accepts_any():
    payload = json.dumps(_bounce_payload())
    headers, msg_id, ts = _sign(payload)
    good = headers["svix-signature"]
    bad_sig = "v1,bm9ldHUjKzFob2VudXRob2VodWUzMjRvdWVvdW9ldQo="
    headers["svix-signature"] = f"{bad_sig} {good}"
    assert verify_webhook_signature(payload, headers, SECRET) is True


# ── Event processing ──────────────────────────────────────────────────


def test_bounce_recorded_against_sent_email(db):
    db.create_email_event(
        "consent",
        "c-1",
        "sent",
        esp_message_id="resend-email-1",
        recipient_email="parent@example.com",
    )
    result = process_email_event(_bounce_payload())
    assert result["processed"] == 1
    assert result["matched"] is True

    events = db.get_email_events(related_type="consent", related_id="c-1")
    assert [e["event"] for e in events] == ["bounced", "sent"]
    assert events[0]["esp_message_id"] == "resend-email-1"
    assert events[0]["recipient_email"] == "parent@example.com"
    assert "email.bounced" in events[0]["metadata_json"]


def test_duplicate_webhook_is_idempotent(db):
    db.create_email_event(
        "consent",
        "c-1",
        "sent",
        esp_message_id="resend-email-1",
        recipient_email="parent@example.com",
    )
    first = process_email_event(_bounce_payload())
    second = process_email_event(_bounce_payload())
    assert first["processed"] == 1
    assert second["processed"] == 0
    assert second["reason"] == "duplicate"
    events = db.get_email_events(related_type="consent", related_id="c-1")
    assert len([e for e in events if e["event"] == "bounced"]) == 1


def test_unknown_email_id_unmatched(db):
    result = process_email_event(_bounce_payload(email_id="ghost-email"))
    assert result["matched"] is False
    assert result["reason"] == "unknown message id"
    assert result["processed"] == 0


def test_unsupported_event_type_unmatched(db):
    result = process_email_event({"type": "email.unknown", "data": {"email_id": "x"}})
    assert result["matched"] is False
    assert result["reason"] == "unsupported"


def test_delivered_and_complained_mappings(db):
    db.create_email_event(
        "consent",
        "c-1",
        "sent",
        esp_message_id="m-1",
        recipient_email="a@b.c",
    )
    assert (
        process_email_event(
            {"type": "email.delivered", "data": {"email_id": "m-1", "to": ["a@b.c"]}}
        )["processed"]
        == 1
    )
    assert (
        process_email_event(
            {"type": "email.complained", "data": {"email_id": "m-1", "to": ["a@b.c"]}}
        )["processed"]
        == 1
    )
    events = db.get_email_events(related_type="consent", related_id="c-1")
    assert [e["event"] for e in events] == ["complained", "delivered", "sent"]


def test_handle_webhook_full_pipeline(db, monkeypatch):
    monkeypatch.setenv("RESEND_WEBHOOK_SECRET", SECRET)
    db.create_email_event(
        "consent",
        "c-1",
        "sent",
        esp_message_id="resend-email-1",
        recipient_email="parent@example.com",
    )
    payload = json.dumps(_bounce_payload())
    headers, _, _ = _sign(payload)
    summary = handle_webhook(payload, headers, SECRET)
    assert summary["matched"] is True
    events = db.get_email_events(related_type="consent", related_id="c-1")
    assert events[0]["event"] == "bounced"


def test_handle_webhook_bad_signature_raises():
    payload = json.dumps(_bounce_payload())
    with pytest.raises(ValueError):
        handle_webhook(
            payload,
            {
                "svix-id": "x",
                "svix-timestamp": str(int(time.time())),
                "svix-signature": "v1,bad",
            },
            SECRET,
        )


def test_handle_webhook_bad_json_raises(db):
    headers, _, _ = _sign('{"type": ')
    with pytest.raises(json.JSONDecodeError):
        handle_webhook('{"type": ', headers, SECRET)


# ── Delivery status surfaced on the tracker ───────────────────────────


def test_bounce_flips_consent_to_invalid(db):
    from services import consent_service

    counsellor = db.create_user(
        "counsellor@school.edu", "Counsellor", "x", role_type="counsellor"
    )
    student = db.create_user("student@school.edu", "Student", "x", role_type="student")
    consent = db.create_consent(
        student["id"], counsellor["id"], "student@school.edu", "student", ["reddit"]
    )
    dispatched = consent_service.dispatch_consent(consent["id"], counsellor["id"])
    assert dispatched["status"] == "PENDING"

    db.create_email_event(
        "consent",
        consent["id"],
        "sent",
        esp_message_id="resend-email-1",
        recipient_email="student@school.edu",
    )
    result = process_email_event(_bounce_payload())
    assert result["processed"] == 1
    assert result["matched"] is True

    after = db.get_consent_by_id(consent["id"])
    assert after["status"] == "INVALID"
    events = db.get_consent_events(consent["id"])
    assert events[0]["event_type"] == "bounced"
    assert events[0]["metadata_json"] and "to_status" in events[0]["metadata_json"]


def test_bounce_does_not_flip_accepted_consent(db):
    from services import consent_service

    counsellor = db.create_user(
        "c@school.edu", "Counsellor", "x", role_type="counsellor"
    )
    student = db.create_user("s@school.edu", "Student", "x", role_type="student")
    consent = db.create_consent(
        student["id"], counsellor["id"], "s@school.edu", "student", ["reddit"]
    )
    dispatched = consent_service.dispatch_consent(consent["id"], counsellor["id"])
    consent_service.accept_consent(dispatched["id"], "Student", "1.2.3.4")

    db.create_email_event(
        "consent",
        consent["id"],
        "sent",
        esp_message_id="resend-email-1",
        recipient_email="s@school.edu",
    )
    process_email_event(_bounce_payload())
    assert db.get_consent_by_id(consent["id"])["status"] == "ACCEPTED"


def test_invalid_consent_can_be_redespatched(db):
    from services import consent_service

    counsellor = db.create_user(
        "c2@school.edu", "Counsellor", "x", role_type="counsellor"
    )
    student = db.create_user("s2@school.edu", "Student", "x", role_type="student")
    consent = db.create_consent(
        student["id"], counsellor["id"], "s2@school.edu", "student", ["reddit"]
    )
    dispatched = consent_service.dispatch_consent(consent["id"], counsellor["id"])
    consent_service.mark_consent_invalid(consent["id"], reason="mailbox unavailable")
    assert db.get_consent_by_id(consent["id"])["status"] == "INVALID"
    re = consent_service.dispatch_consent(consent["id"], counsellor["id"])
    assert re["status"] == "PENDING"
    assert re["magic_token"] != dispatched["magic_token"]


def test_query_consents_shows_delivery_status(db):
    counsellor = db.create_user(
        "counsellor@school.edu", "Counsellor", "x", role_type="counsellor"
    )
    student = db.create_user("student@school.edu", "Student", "x", role_type="student")
    consent = db.create_consent(
        student["id"], counsellor["id"], "student@school.edu", "student", ["reddit"]
    )
    consent = db.get_consent_by_id(consent["id"])

    db.create_email_event(
        "consent",
        consent["id"],
        "sent",
        esp_message_id="resend-email-1",
        recipient_email="student@school.edu",
    )
    db.create_email_event(
        "consent",
        consent["id"],
        "bounced",
        esp_message_id="resend-email-1",
        recipient_email="student@school.edu",
    )

    rows, total = db.query_consents(counsellor["id"])
    assert total == 1
    assert rows[0]["delivery_status"] == "bounced"
    assert rows[0]["last_delivery_event_at"]

    detail = db.get_consent_with_student(consent["id"])
    assert detail["delivery_status"] == "bounced"


def test_query_consents_no_delivery_event_is_none(db):
    counsellor = db.create_user(
        "c2@school.edu", "Counsellor", "x", role_type="counsellor"
    )
    student = db.create_user("s2@school.edu", "Student", "x", role_type="student")
    db.create_consent(
        student["id"], counsellor["id"], "s2@school.edu", "student", ["reddit"]
    )
    rows, _ = db.query_consents(counsellor["id"])
    assert rows[0]["delivery_status"] is None
