import os

os.environ.setdefault("JWT_SECRET", "consent-decision-test-secret")

from fastapi.testclient import TestClient

from backend.auth import create_access_token, hash_password
from backend.main import app


def _approved_user(db, email: str, role: str) -> dict:
    user = db.create_user(
        email, email.split("@")[0], hash_password("pw-12345"), role_type=role
    )
    conn = db.get_db()
    conn.execute("UPDATE users SET status = 'approved' WHERE id = ?", (user["id"],))
    conn.commit()
    conn.close()
    return user


def _auth_headers(user: dict) -> dict:
    return {
        "Authorization": f"Bearer {create_access_token(user['id'], user['role_type'])}"
    }


def _make_pending_consent(db, counsellor: dict, student: dict) -> dict:
    consent = db.create_consent(
        student_id=student["id"],
        counsellor_id=counsellor["id"],
        recipient_email=student["email"],
        recipient_role="student",
        platforms=["Reddit"],
    )
    from backend.services import consent_service

    return consent_service.dispatch_consent(consent["id"], counsellor["id"])


def test_record_decision_accept_writes_audit_and_signature(db, monkeypatch):
    counsellor = _approved_user(db, "c1@school.edu", "counsellor")
    student = _approved_user(db, "s1@school.edu", "student")
    consent = _make_pending_consent(db, counsellor, student)
    monkeypatch.setattr(
        "backend.services.consent_service.send_html_email", lambda *a, **k: (True, "")
    )

    with TestClient(app) as client:
        resp = client.post(
            f"/api/v1/consents/{consent['id']}/decision",
            json={"decision": "ACCEPTED", "signature_name": "Jane Doe"},
            headers=_auth_headers(counsellor),
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["status"] == "ACCEPTED"

    updated = db.get_consent_by_id(consent["id"])
    assert updated["status"] == "ACCEPTED"
    assert updated["signature_name"] == "Jane Doe"
    assert updated["accepted_at"]

    actions = {
        row["action"] for row in db.get_audit_log_for_target("consent", consent["id"])
    }
    assert "CONSENT_ACCEPTED" in actions

    events = db.get_consent_events(consent["id"])
    assert any(
        e["event_type"] == "accepted" and e["actor_type"] == "counsellor"
        for e in events
    )


def test_record_decision_declined(db, monkeypatch):
    counsellor = _approved_user(db, "c2@school.edu", "counsellor")
    student = _approved_user(db, "s2@school.edu", "student")
    consent = _make_pending_consent(db, counsellor, student)
    monkeypatch.setattr(
        "backend.services.consent_service.send_html_email", lambda *a, **k: (True, "")
    )

    with TestClient(app) as client:
        resp = client.post(
            f"/api/v1/consents/{consent['id']}/decision",
            json={"decision": "DECLINED"},
            headers=_auth_headers(counsellor),
        )

    assert resp.status_code == 200
    updated = db.get_consent_by_id(consent["id"])
    assert updated["status"] == "DECLINED"
    actions = {
        row["action"] for row in db.get_audit_log_for_target("consent", consent["id"])
    }
    assert "CONSENT_DECLINED" in actions


def test_record_decision_rejects_invalid_value(db):
    counsellor = _approved_user(db, "c3@school.edu", "counsellor")
    student = _approved_user(db, "s3@school.edu", "student")
    consent = _make_pending_consent(db, counsellor, student)

    with TestClient(app) as client:
        resp = client.post(
            f"/api/v1/consents/{consent['id']}/decision",
            json={"decision": "MAYBE"},
            headers=_auth_headers(counsellor),
        )
    assert resp.status_code == 400


def test_record_decision_forbidden_for_other_counsellor(db):
    counsellor = _approved_user(db, "c4@school.edu", "counsellor")
    other = _approved_user(db, "c4b@school.edu", "counsellor")
    student = _approved_user(db, "s4@school.edu", "student")
    consent = _make_pending_consent(db, counsellor, student)

    with TestClient(app) as client:
        resp = client.post(
            f"/api/v1/consents/{consent['id']}/decision",
            json={"decision": "ACCEPTED"},
            headers=_auth_headers(other),
        )
    assert resp.status_code == 403


def test_record_decision_on_revoked_consent_fails(db):
    counsellor = _approved_user(db, "c5@school.edu", "counsellor")
    student = _approved_user(db, "s5@school.edu", "student")
    consent = _make_pending_consent(db, counsellor, student)
    from backend.services import consent_service

    consent_service.accept_consent(consent["id"], "Recipient", "127.0.0.1")
    consent_service.revoke_consent(consent["id"], "127.0.0.1")

    with TestClient(app) as client:
        resp = client.post(
            f"/api/v1/consents/{consent['id']}/decision",
            json={"decision": "ACCEPTED"},
            headers=_auth_headers(counsellor),
        )
    assert resp.status_code == 400


def test_counsellor_audit_log_returns_relevant_entries(db):
    """Regression: get_audit_log queried a non-existent users.institution_id."""
    counsellor = _approved_user(db, "c6@school.edu", "counsellor")
    student = _approved_user(db, "s6@school.edu", "student")
    consent = _make_pending_consent(db, counsellor, student)

    db.write_audit(
        counsellor["id"], "counsellor", "CONSENT_DISPATCHED", "consent", consent["id"]
    )
    db.write_audit(
        counsellor["id"],
        "counsellor",
        "NOTE_CREATED",
        "note",
        "n1",
        payload={"student_id": student["id"]},
    )

    entries = db.get_audit_log(counsellor["id"], limit=100)
    actions = {e["action"] for e in entries}
    assert "CONSENT_DISPATCHED" in actions


def test_admin_audit_endpoint_returns_entries(db):
    """Regression: the admin panel audit trail must return logged actions."""
    admin = _approved_user(db, "a7@school.edu", "admin")
    student = db.create_user(
        "s7@school.edu", "s7", hash_password("pw-12345"), role_type="student"
    )

    with TestClient(app) as client:
        client.post(
            "/api/counsellor/students/approve",
            json={"id": student["id"]},
            headers=_auth_headers(admin),
        )

    with TestClient(app) as client:
        resp = client.get("/api/v1/admin/audit?limit=50", headers=_auth_headers(admin))

    assert resp.status_code == 200
    actions = {row["action"] for row in resp.json()["entries"]}
    assert "STUDENT_APPROVED" in actions
