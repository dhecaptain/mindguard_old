"""Tests for analysis/platform rate limiting (H4).

The expensive analysis and platform endpoints are capped per authenticated
user; once the budget is spent a 429 is returned instead of running more
inference.
"""

import os

os.environ.setdefault("JWT_SECRET", "analysis-rate-test-secret")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import database  # noqa: E402
from backend.auth import hash_password  # noqa: E402
from backend.main import _ANALYSIS_RATE_MAX, _check_rate_limit  # noqa: E402


@pytest.fixture(scope="module")
def client():
    from backend.main import app

    with TestClient(app) as c:
        yield c


def _auth_header(client, email="rl@school.edu") -> dict:
    token = client.post(
        "/api/auth/login", json={"email": email, "password": "pw-12345"}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_analysis_budget_exhausted_returns_429(monkeypatch, db, client):
    monkeypatch.delenv("RECAPTCHA_SECRET", raising=False)
    user = database.create_user(
        "rl@school.edu", "Rate Limited", hash_password("pw-12345"), role_type="admin"
    )
    headers = _auth_header(client)

    # Drain the per-user budget, then the next analysis call must be refused.
    for _ in range(_ANALYSIS_RATE_MAX):
        _check_rate_limit(f"analyze:{user['id']}", max_requests=_ANALYSIS_RATE_MAX)

    resp = client.post("/api/analysis/text", json={"text": "hello"}, headers=headers)
    assert resp.status_code == 429


def test_analysis_budget_allows_normal_use(monkeypatch, db, client):
    monkeypatch.delenv("RECAPTCHA_SECRET", raising=False)
    database.create_user(
        "rl2@school.edu", "Rate OK", hash_password("pw-12345"), role_type="admin"
    )
    headers = _auth_header(client, email="rl2@school.edu")

    resp = client.post("/api/analysis/text", json={"text": "hello"}, headers=headers)
    assert resp.status_code in (200, 503)  # 503 if the ML model is unavailable offline


def test_student_cannot_run_direct_text_analysis(db, client):
    database.create_user(
        "student-direct@school.edu",
        "Student",
        hash_password("pw-12345"),
        role_type="student",
    )
    headers = _auth_header(client, email="student-direct@school.edu")

    resp = client.post("/api/analysis/text", json={"text": "hello"}, headers=headers)
    assert resp.status_code == 403
    assert "assigned counsellor" in resp.json()["detail"].lower()
