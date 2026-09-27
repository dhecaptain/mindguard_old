import os

os.environ.setdefault("JWT_SECRET", "guardian-recipient-test-secret")

from fastapi.testclient import TestClient

from backend.auth import create_access_token, hash_password
from backend.main import app
from backend.services import consent_service
from backend.services.crypto import decrypt_pii, encrypt_pii, hash_student_id


def _approved(db, email, role, institution_id=None):
    user = db.create_user(
        email, email.split("@")[0], hash_password("pw-12345"),
        role_type=role, institution_id=institution_id,
    )
    conn = db.get_db()
    conn.execute("UPDATE users SET status = 'approved' WHERE id = ?", (user["id"],))
    conn.commit()
    conn.close()
    return user


def test_school_admin_corrects_guardian_email_and_old_link_is_invalidated(db, monkeypatch):
    institution = db.create_institution("Guardian Test School", "school")
    db.update_institution(institution["id"], status="ACTIVE")
    school_admin = _approved(db, "admin@guardian-school.test", "school_admin", institution["id"])
    student_user = _approved(db, "student@guardian-school.test", "student", institution["id"])
    roster = db.create_student(
        institution["id"],
        hash_student_id("G-001"),
        encrypt_pii("Student"),
        encrypt_pii(student_user["email"]),
        encrypt_pii("2012-04-10"),
        True,
        school_admin["id"],
        parent_email_encrypted=encrypt_pii("wrong.parent@example.test"),
        user_id=student_user["id"],
    )
    consent = db.create_consent(
        student_user["id"], school_admin["id"], "wrong.parent@example.test",
        "parent", ["Mastodon"],
    )
    monkeypatch.setattr(consent_service, "send_html_email", lambda *args, **kwargs: (True, ""))
    pending = consent_service.dispatch_consent(consent["id"], school_admin["id"], actor_role="school_admin")
    old_token = pending["magic_token"]

    headers = {"Authorization": f"Bearer {create_access_token(school_admin['id'], 'school_admin')}"}
    with TestClient(app) as client:
        response = client.patch(
            f"/api/institution/consents/{consent['id']}/guardian-recipient",
            json={"recipient_email": "correct.parent@example.test"},
            headers=headers,
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["email_sent"] is True
    assert body["consent"]["recipient_email"] == "correct.parent@example.test"
    assert body["consent"]["status"] == "PENDING"
    assert consent_service.verify_consent_token(db.get_consent_by_id(consent["id"]), old_token) is False
    updated_roster = db.get_student_by_id(roster["id"])
    assert decrypt_pii(updated_roster["parent_email_encrypted"]) == "correct.parent@example.test"
    assert any(
        event["event_type"] == "recipient_corrected_and_resent"
        for event in db.get_consent_events(consent["id"])
    )
    assert "GUARDIAN_CONSENT_RECIPIENT_CORRECTED" in {
        event["action"] for event in db.get_audit_log_for_target("consent", consent["id"])
    }


def test_only_school_admin_can_correct_guardian_recipient(db):
    institution = db.create_institution("Guardian Test School", "school")
    db.update_institution(institution["id"], status="ACTIVE")
    counsellor = _approved(db, "counsellor@guardian-school.test", "counsellor", institution["id"])
    headers = {"Authorization": f"Bearer {create_access_token(counsellor['id'], 'counsellor')}"}
    with TestClient(app) as client:
        response = client.patch(
            "/api/institution/consents/not-a-consent/guardian-recipient",
            json={"recipient_email": "parent@example.test"},
            headers=headers,
        )
    assert response.status_code == 403
