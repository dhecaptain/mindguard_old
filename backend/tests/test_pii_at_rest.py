"""P0-4: PII encrypted at rest — ciphertext assertions, hash joins, legacy compat."""

import json

import pytest

from backend.services import crypto
from backend.services.crypto import hash_email, redact_pii


def test_hash_email_normalises_and_is_deterministic():
    assert hash_email("  Jane.Doe@School.edu ") == hash_email("jane.doe@school.edu")
    assert len(hash_email("jane@school.edu")) == 64
    assert hash_email(None) == hash_email("")


def test_redact_pii_emails_urls_and_keys():
    blob = redact_pii(
        {
            "to": "Jane Doe <jane@school.edu>",
            "url": "https://app.mindguard.org/consent/v1.abc.def.ghi",
            "recipient": "jane@school.edu",
            "signature": "Jane Doe",
            "nested": {"parent_email": "mom@school.edu"},
            "tags": ["jane@school.edu", "keep-me"],
        }
    )
    dumped = json.dumps(blob)
    assert "jane@school.edu" not in dumped
    assert "mom@school.edu" not in dumped
    assert "v1.abc.def.ghi" not in dumped
    assert "redacted-" in dumped
    assert "[redacted]" in dumped
    assert blob["nested"]["parent_email"].endswith("@redacted")
    assert "mom@school.edu" not in blob["nested"]["parent_email"]
    assert blob["signature"] == "[redacted]"
    assert blob["tags"] == [
        f"redacted-{hash_email('jane@school.edu')[:12]}@redacted",
        "keep-me",
    ]


def test_consent_recipient_email_encrypted_at_rest(db):
    counsellor = db.create_user(
        "counsellor@school.edu", "Counsellor", "x", role_type="counsellor"
    )
    alex = db.create_user("alex@uni.edu", "Alex Roe", "x", role_type="student")
    cons = db.create_consent(
        alex["id"], counsellor["id"], "jane@school.edu", "student", ["Reddit"]
    )
    conn = db.get_db()
    raw = conn.execute(
        "SELECT recipient_email, recipient_email_hash FROM consents WHERE id = ?",
        (cons["id"],),
    ).fetchone()
    conn.close()
    assert raw["recipient_email"].startswith("gcm1:")
    assert raw["recipient_email"] != "jane@school.edu"
    assert raw["recipient_email_hash"] == hash_email("jane@school.edu")
    assert db.get_consent_by_id(cons["id"])["recipient_email"] == "jane@school.edu"


def test_email_event_recipient_encrypted_at_rest(db):
    eid = db.create_email_event(
        "consent",
        "c-1",
        "delivered",
        esp_message_id="esp-9",
        recipient_email="jane@school.edu",
        metadata={"tag": "consent"},
    )
    conn = db.get_db()
    raw = conn.execute(
        "SELECT recipient_email, recipient_email_hash FROM email_events WHERE id = ?",
        (eid,),
    ).fetchone()
    conn.close()
    assert raw["recipient_email"].startswith("gcm1:")
    assert raw["recipient_email_hash"] == hash_email("jane@school.edu")
    events = db.get_email_events_by_esp_message_id("esp-9")
    assert events[0]["recipient_email"] == "jane@school.edu"
    assert events[0]["recipient_email_hash"] == hash_email("jane@school.edu")


def test_delivery_status_join_works_through_hashes(db):
    counsellor = db.create_user(
        "counsellor@school.edu", "Counsellor", "x", role_type="counsellor"
    )
    alex = db.create_user("alex@uni.edu", "Alex Roe", "x", role_type="student")
    cons = db.create_consent(
        alex["id"], counsellor["id"], "ALEX@uni.edu", "student", ["Reddit"]
    )
    db.create_email_event(
        "consent",
        cons["id"],
        "delivered",
        esp_message_id="esp-1",
        recipient_email="alex@uni.edu",
    )
    joined = db.get_consent_with_student(cons["id"])
    assert joined["recipient_email"] == "ALEX@uni.edu"
    assert joined["delivery_status"] == "delivered"
    assert joined["last_delivery_event_at"]


def test_demo_request_pii_encrypted_at_rest(db):
    demo = db.create_demo_request("Jane Doe", "jane@corp.com", "Acme Inc")
    conn = db.get_db()
    raw = conn.execute(
        "SELECT full_name, work_email, organisation, work_email_hash FROM demo_requests WHERE id = ?",
        (demo["id"],),
    ).fetchone()
    conn.close()
    assert raw["full_name"].startswith("gcm1:")
    assert raw["work_email"].startswith("gcm1:")
    assert raw["organisation"].startswith("gcm1:")
    assert raw["work_email_hash"] == hash_email("jane@corp.com")
    fetched = db.get_demo_request(demo["id"])
    assert fetched["full_name"] == "Jane Doe"
    assert fetched["work_email"] == "jane@corp.com"
    assert fetched["organisation"] == "Acme Inc"


def test_demo_request_delivery_status_join_through_hash(db):
    demo = db.create_demo_request("Jane Doe", "jane@corp.com", "Acme Inc")
    db.create_email_event(
        "demo_request",
        demo["id"],
        "bounced",
        esp_message_id="esp-2",
        recipient_email="JANE@corp.com",
    )
    rows = db.list_demo_requests(status="new")
    assert rows[0]["id"] == demo["id"]
    assert rows[0]["delivery_status"] == "bounced"
    assert rows[0]["work_email"] == "jane@corp.com"


def test_legacy_plaintext_consent_reads_transparently(db):
    counsellor = db.create_user(
        "counsellor@school.edu", "Counsellor", "x", role_type="counsellor"
    )
    alex = db.create_user("alex@uni.edu", "Alex Roe", "x", role_type="student")
    cons = db.create_consent(
        alex["id"], counsellor["id"], "alex@uni.edu", "student", ["Reddit"]
    )
    conn = db.get_db()
    conn.execute(
        "UPDATE consents SET recipient_email = ?, recipient_email_hash = NULL WHERE id = ?",
        ("legacy@uni.edu", cons["id"]),
    )
    conn.commit()
    conn.close()
    fetched = db.get_consent_by_id(cons["id"])
    assert fetched["recipient_email"] == "legacy@uni.edu"
    assert not fetched["recipient_email"].startswith("gcm1:")


def test_audit_and_consent_event_json_redacted_at_write(db):
    from backend.database import (
        create_consent_event,
        get_audit_log_for_target,
        get_consent_events,
        write_audit,
    )

    counsellor = db.create_user(
        "counsellor@school.edu", "Counsellor", "x", role_type="counsellor"
    )
    alex = db.create_user("alex@uni.edu", "Alex Roe", "x", role_type="student")
    cons = db.create_consent(
        alex["id"], counsellor["id"], "alex@uni.edu", "student", ["Reddit"]
    )
    write_audit(
        "actor-1",
        "counsellor",
        "CONSENT_DISPATCHED",
        "consent",
        cons["id"],
        payload={
            "recipient": "jane@school.edu",
            "url": "https://app.mindguard.org/consent/v1.token123.mac",
            "note": "sent to jane@school.edu",
        },
    )
    create_consent_event(
        cons["id"],
        "CONSENT_ACCEPTED",
        "student",
        "alex@uni.edu",
        metadata={"recipient_email": "jane@school.edu", "signature": "Jane Doe"},
    )
    audit = get_audit_log_for_target("consent", cons["id"])
    raw_audit = json.dumps(audit)
    assert "jane@school.edu" not in raw_audit
    assert "token123" not in raw_audit
    assert "redacted-" in raw_audit
    events = get_consent_events(cons["id"])
    raw_event = json.dumps(events)
    assert "jane@school.edu" not in raw_event
    assert "[redacted]" in raw_event


def test_decrypt_pii_rejects_plaintext(db):
    with pytest.raises(ValueError):
        crypto.decrypt_pii("plaintext!")
