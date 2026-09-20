"""Phase 1 authorization regression tests for ID substitution and stale scope."""

import os

os.environ.setdefault("JWT_SECRET", "phase1-security-test-secret")
os.environ.setdefault("ENCRYPTION_KEY", "d" * 64)

from fastapi.testclient import TestClient

from backend import database
from backend.auth import create_access_token, hash_password
from backend.main import app
from backend.services import consent_service


def _user(db, email, role, institution_id=None):
    user = database.create_user(
        email, email.split("@")[0], hash_password("pw-12345"), role_type=role
    )
    conn = db.get_db()
    conn.execute(
        "UPDATE users SET status = 'approved', institution_id = ? WHERE id = ?",
        (institution_id, user["id"]),
    )
    conn.commit()
    conn.close()
    return database.get_user_by_id(user["id"])


def _accepted_consent(db, student_id, counsellor_id):
    consent = database.create_consent(
        student_id, counsellor_id, "student@example.com", "student", ["reddit"]
    )
    consent_service.dispatch_consent(consent["id"], counsellor_id)
    return consent_service.accept_consent(consent["id"], "Student", "127.0.0.1")


def _headers(user):
    return {
        "Authorization": f"Bearer {create_access_token(user['id'], user['role_type'])}"
    }


def test_general_message_idor_is_denied(db):
    institution = database.create_institution("Phase 1 School", "school")
    c1 = _user(db, "phase1-c1@example.com", "counsellor", institution["id"])
    c2 = _user(db, "phase1-c2@example.com", "counsellor", institution["id"])
    student = _user(db, "phase1-student@example.com", "student", institution["id"])
    database.assign_student_to_counsellor(c1["id"], student["id"], institution["id"])
    _accepted_consent(db, student["id"], c1["id"])

    with TestClient(app) as client:
        assert (
            client.get(
                f"/api/messages/conversations/{student['id']}", headers=_headers(c2)
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/messages/send",
                json={"receiver_id": student["id"], "message": "unauthorised"},
                headers=_headers(c2),
            ).status_code
            == 403
        )


def test_stale_consent_does_not_authorize_student_data(db):
    institution = database.create_institution("Phase 1 Stale School", "school")
    counsellor = _user(
        db, "phase1-stale-c@example.com", "counsellor", institution["id"]
    )
    student = _user(db, "phase1-stale-s@example.com", "student", institution["id"])
    database.assign_student_to_counsellor(
        counsellor["id"], student["id"], institution["id"]
    )
    consent = database.create_consent(
        student["id"], counsellor["id"], "student@example.com", "student", ["reddit"]
    )
    conn = db.get_db()
    conn.execute(
        "UPDATE consents SET status = 'REVOKED' WHERE id = ?", (consent["id"],)
    )
    conn.commit()
    conn.close()

    with TestClient(app) as client:
        response = client.get(
            f"/api/counsellor/students/{student['id']}", headers=_headers(counsellor)
        )
        assert response.status_code == 403


def test_linked_account_revoke_is_bound_to_student(db):
    institution = database.create_institution("Phase 1 Account School", "school")
    counsellor = _user(
        db, "phase1-account-c@example.com", "counsellor", institution["id"]
    )
    student_a = _user(db, "phase1-account-a@example.com", "student", institution["id"])
    student_b = _user(db, "phase1-account-b@example.com", "student", institution["id"])
    for student in (student_a, student_b):
        database.assign_student_to_counsellor(
            counsellor["id"], student["id"], institution["id"]
        )
        _accepted_consent(db, student["id"], counsellor["id"])
    account_b = database.create_linked_account(
        student_b["id"], None, "reddit", "handle", "student_b"
    )

    with TestClient(app) as client:
        response = client.delete(
            f"/api/v1/students/{student_a['id']}/accounts/{account_b['id']}",
            headers=_headers(counsellor),
        )
        assert response.status_code == 404

    assert database.get_linked_accounts(student_b["id"])[0]["status"] == "active"


def test_approve_unassigned_student_is_denied(db):
    institution = database.create_institution("Phase 1 Approval School", "school")
    counsellor = _user(
        db, "phase1-approval-c@example.com", "counsellor", institution["id"]
    )
    student = _user(db, "phase1-approval-s@example.com", "student", institution["id"])

    with TestClient(app) as client:
        response = client.post(
            "/api/counsellor/students/approve",
            json={"id": student["id"]},
            headers=_headers(counsellor),
        )
        assert response.status_code == 403
