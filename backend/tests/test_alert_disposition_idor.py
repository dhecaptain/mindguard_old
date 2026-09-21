"""Tests for alert-disposition authorization (M4).

A counsellor must only be able to dispose alerts they own. Disposing another
counsellor's alert is an IDOR; the route must reject it with 403.
"""

import os

os.environ.setdefault("JWT_SECRET", "alert-idor-test-secret")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import database  # noqa: E402
from backend.auth import hash_password  # noqa: E402


@pytest.fixture(scope="module")
def client():
    from backend.main import app

    with TestClient(app) as c:
        yield c


def _make_counsellor(db, email: str) -> dict:
    user = database.create_user(
        email,
        email.split("@")[0].title(),
        hash_password("pw-12345"),
        role_type="counsellor",
    )
    conn = db.get_db()
    conn.execute("UPDATE users SET status = 'approved' WHERE id = ?", (user["id"],))
    conn.commit()
    conn.close()
    return user


def _token(client, email: str) -> str:
    return client.post(
        "/api/auth/login", json={"email": email, "password": "pw-12345"}
    ).json()["access_token"]


def test_cannot_dispose_another_counsellors_alert(db, client, monkeypatch):
    monkeypatch.delenv("RECAPTCHA_SECRET", raising=False)
    a = _make_counsellor(db, "alice@school.edu")
    _make_counsellor(db, "bob@school.edu")
    student = database.create_user(
        "stu@school.edu", "Stu", hash_password("pw-12345"), role_type="student"
    )

    alert = database.create_alert(student["id"], a["id"], 0.91, 0.65, "reddit")
    assert alert is not None

    bob_token = _token(client, "bob@school.edu")
    resp = client.post(
        f"/api/v1/alerts/{alert['id']}/disposition",
        headers={"Authorization": f"Bearer {bob_token}"},
        json={"action": "DISMISS", "reason_code": "false-positive", "reason_note": ""},
    )
    assert resp.status_code == 403

    conn = db.get_db()
    row = conn.execute(
        "SELECT status FROM alerts WHERE id = ?", (alert["id"],)
    ).fetchone()
    conn.close()
    assert row["status"] == "OPEN", (
        "alert must remain OPEN after an unauthorised attempt"
    )


def test_owner_can_dispose_own_alert(db, client, monkeypatch):
    monkeypatch.delenv("RECAPTCHA_SECRET", raising=False)
    a = _make_counsellor(db, "carol@school.edu")
    student = database.create_user(
        "stu2@school.edu", "Stu Two", hash_password("pw-12345"), role_type="student"
    )

    alert = database.create_alert(student["id"], a["id"], 0.91, 0.65, "reddit")
    token = _token(client, "carol@school.edu")
    resp = client.post(
        f"/api/v1/alerts/{alert['id']}/disposition",
        headers={"Authorization": f"Bearer {token}"},
        json={"action": "DISMISS", "reason_code": "false-positive", "reason_note": ""},
    )
    assert resp.status_code == 200, resp.text

    conn = db.get_db()
    row = conn.execute(
        "SELECT status FROM alerts WHERE id = ?", (alert["id"],)
    ).fetchone()
    conn.close()
    assert row["status"] == "CLOSED"
