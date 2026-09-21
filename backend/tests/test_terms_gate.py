"""Tests for the terms-of-use gate (H2).

The frontend must show the practitioner agreement until the user has explicitly
accepted it via ``POST /api/auth/terms``. The ``terms_accepted`` flag on the
auth responses is what drives the gate — it must reflect the persisted DB state,
not a client-side assumption.
"""

import os

os.environ.setdefault("JWT_SECRET", "terms-gate-test-secret")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="module")
def client():
    from backend.main import app

    with TestClient(app) as c:
        yield c


def _register_student(client, email: str, password: str = "pw-12345") -> str:
    resp = client.post(
        "/api/auth/register",
        json={
            "name": "Student",
            "email": email,
            "password": password,
            "role": "student",
        },
    )
    assert resp.status_code == 200, resp.text
    token = client.post(
        "/api/auth/login", json={"email": email, "password": password}
    ).json()["access_token"]
    return token


def test_new_user_has_terms_unaccepted(db, client):
    token = _register_student(client, "t1@school.edu")
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["terms_accepted"] is False


def test_accept_terms_persists(db, client):
    token = _register_student(client, "t2@school.edu")

    resp = client.post("/api/auth/terms", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["terms_accepted"] is True

    # A fresh session (new login) still reports the persisted acceptance.
    token2 = client.post(
        "/api/auth/login", json={"email": "t2@school.edu", "password": "pw-12345"}
    ).json()["access_token"]
    me2 = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token2}"})
    assert me2.json()["terms_accepted"] is True


def test_login_response_carries_terms_flag(db, client):
    _register_student(client, "t3@school.edu")
    resp = client.post(
        "/api/auth/login", json={"email": "t3@school.edu", "password": "pw-12345"}
    )
    assert resp.status_code == 200
    assert resp.json()["terms_accepted"] is False
