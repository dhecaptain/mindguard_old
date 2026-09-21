import os

os.environ.setdefault("JWT_SECRET", "admin-status-test-secret")

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


def test_admin_status_changes_notify_and_audit(db, monkeypatch):
    admin = _approved_user(db, "admin@school.edu", "admin")
    student = db.create_user(
        "student@school.edu", "student", hash_password("pw-12345"), role_type="student"
    )
    sent = []

    def fake_send(to_email, subject, body_html, **kwargs):
        sent.append((to_email, subject, kwargs))
        return True, ""

    monkeypatch.setattr("backend.services.email_sender.send_html_email", fake_send)
    monkeypatch.setattr("backend.main.send_html_email", fake_send)
    headers = {
        "Authorization": f"Bearer {create_access_token(admin['id'], admin['role_type'])}"
    }

    with TestClient(app) as client:
        approved = client.post(
            "/api/counsellor/students/approve",
            json={"id": student["id"]},
            headers=headers,
        )
        revoked = client.post(
            "/api/counsellor/students/revoke",
            json={"id": student["id"]},
            headers=headers,
        )

    assert approved.status_code == 200
    assert approved.json()["email_sent"] is True
    assert revoked.status_code == 200
    assert revoked.json()["email_sent"] is True
    assert [event[2]["metadata"]["status"] for event in sent] == ["approved", "revoked"]
    actions = {row["action"] for row in db.get_all_audit_log(limit=20)}
    assert {"STUDENT_APPROVED", "STUDENT_REVOKED"} <= actions


def test_dashboard_works_without_user_institution_column(db):
    admin = _approved_user(db, "dashboard-admin@school.edu", "admin")
    dashboard = db.get_counsellor_dashboard(admin["id"])
    assert dashboard["total_students"] == 0
    assert dashboard["pending_approvals"] == 0
