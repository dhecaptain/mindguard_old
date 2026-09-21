"""Tests for notification read scoping (M6).

A user must only be able to mark their own notifications as read. Passing
another user's notification id must be a no-op, not a cross-user write.
"""

import os

os.environ.setdefault("JWT_SECRET", "notif-scope-test-secret")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import database  # noqa: E402
from backend.auth import hash_password  # noqa: E402


@pytest.fixture(scope="module")
def client():
    from backend.main import app

    with TestClient(app) as c:
        yield c


def _token(client, email: str) -> str:
    return client.post(
        "/api/auth/login", json={"email": email, "password": "pw-12345"}
    ).json()["access_token"]


def test_cannot_mark_another_users_notification_read(db, client, monkeypatch):
    monkeypatch.delenv("RECAPTCHA_SECRET", raising=False)
    database.create_user(
        "n1@school.edu", "Notif One", hash_password("pw-12345"), role_type="student"
    )
    b = database.create_user(
        "n2@school.edu", "Notif Two", hash_password("pw-12345"), role_type="student"
    )
    nid = database.create_notification(
        b["id"], "Alert", "You have a new alert", "alert"
    )

    a_token = _token(client, "n1@school.edu")
    resp = client.post(
        "/api/notifications/read",
        headers={"Authorization": f"Bearer {a_token}"},
        json={"id": nid},
    )
    assert resp.status_code == 200

    conn = db.get_db()
    row = conn.execute("SELECT read FROM notifications WHERE id = ?", (nid,)).fetchone()
    conn.close()
    assert row["read"] == 0, "cross-user mark-read must be a no-op"


def test_owner_can_mark_own_notification_read(db, client, monkeypatch):
    monkeypatch.delenv("RECAPTCHA_SECRET", raising=False)
    b = database.create_user(
        "n3@school.edu", "Notif Three", hash_password("pw-12345"), role_type="student"
    )
    nid = database.create_notification(
        b["id"], "Alert", "You have a new alert", "alert"
    )

    b_token = _token(client, "n3@school.edu")
    resp = client.post(
        "/api/notifications/read",
        headers={"Authorization": f"Bearer {b_token}"},
        json={"id": nid},
    )
    assert resp.status_code == 200

    conn = db.get_db()
    row = conn.execute("SELECT read FROM notifications WHERE id = ?", (nid,)).fetchone()
    conn.close()
    assert row["read"] == 1
