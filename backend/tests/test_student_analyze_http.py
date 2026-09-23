"""HTTP-level tests for the consent-gated student analysis endpoint.

The endpoint ``POST /api/v1/students/{student_id}/analyze`` is the entry point
the counsellor UI uses to run a rolling-risk analysis on a consenting student.
These tests verify the full wire: auth, staff gating, consent enforcement at
the HTTP boundary, 404 handling, and persistence of the risk record.
"""

import os
from datetime import datetime, timezone

os.environ.setdefault("JWT_SECRET", "student-analyze-test-secret")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import database  # noqa: E402
from backend.auth import hash_password  # noqa: E402
from backend.services import consent_service  # noqa: E402


@pytest.fixture(scope="module")
def client():
    from backend.main import app

    with TestClient(app) as c:
        yield c


def _approve(db, user_id: str) -> None:
    conn = db.get_db()
    conn.execute("UPDATE users SET status = 'approved' WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()


def _make_user(db, email: str, role: str) -> dict:
    user = db.create_user(
        email, email.split("@")[0].title(), hash_password("pw-12345"), role_type=role
    )
    _approve(db, user["id"])
    return user


def _login(client, email: str, password: str = "pw-12345") -> str:
    resp = client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _grant_active_consent(db, student_id: str, counsellor_id: str) -> dict:
    # Analysis targets must be a student-owned, verified account. This is a
    # fixture shortcut; the product flow verifies the public profile proof.
    db.save_social_account(
        student_id,
        "reddit",
        "student-owned-reddit",
        "https://www.reddit.com/user/student-owned-reddit/",
    )
    db.mark_social_account_verified(student_id, "reddit")
    consent = db.create_consent(
        student_id, counsellor_id, "student@school.edu", "student", ["reddit"]
    )
    dispatched = consent_service.dispatch_consent(consent["id"], counsellor_id)
    return consent_service.accept_consent(dispatched["id"], "Student", "127.0.0.1")


def _posts(n: int = 2, score: float = 0.3) -> list[dict]:
    now = datetime.now(timezone.utc).isoformat()
    return [
        {
            "text": " ".join(["word"] * 30),
            "date": now,
            "risk_score": score + (i * 0.01),
            "url": "https://reddit.com/x",
        }
        for i in range(n)
    ]


def test_blocks_student_without_active_consent(db, client):
    counsellor = _make_user(db, "c1@school.edu", "counsellor")
    student = _make_user(db, "s1@school.edu", "student")
    database.assign_student_to_counsellor(counsellor["id"], student["id"])
    token = _login(client, "c1@school.edu")

    resp = client.post(
        f"/api/v1/students/{student['id']}/analyze",
        headers={"Authorization": f"Bearer {token}"},
        json={"posts": _posts(), "platform": "reddit"},
    )
    assert resp.status_code == 403
    assert "consent" in resp.json()["detail"].lower()


def test_runs_analysis_with_active_consent(db, client):
    counsellor = _make_user(db, "c2@school.edu", "counsellor")
    student = _make_user(db, "s2@school.edu", "student")
    database.assign_student_to_counsellor(counsellor["id"], student["id"])
    _grant_active_consent(db, student["id"], counsellor["id"])
    token = _login(client, "c2@school.edu")

    resp = client.post(
        f"/api/v1/students/{student['id']}/analyze",
        headers={"Authorization": f"Bearer {token}"},
        json={"posts": _posts(), "platform": "reddit"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["student_id"] == student["id"]
    assert data["platform"] == "reddit"
    assert 0.0 <= data["rolling_score"] <= 1.0
    assert data["n_posts"] == 2
    assert "score" in data["risk_record"]

    # Risk record is persisted and surfaced on the student detail endpoint.
    detail = client.get(
        f"/api/counsellor/students/{student['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["rolling_risk"] is not None
    assert body["rolling_risk"]["score"] == data["rolling_score"]
    assert body["risk_summary"]["latest_prob"] == data["rolling_score"]
    assert body["consent_status"]["active"] is True


def test_student_detail_reports_missing_consent_for_ui_gating(db, client):
    counsellor = _make_user(db, "c5@school.edu", "counsellor")
    student = _make_user(db, "s5@school.edu", "student")
    db.create_consent(
        student["id"], counsellor["id"], "student@school.edu", "student", ["reddit"]
    )
    database.assign_student_to_counsellor(counsellor["id"], student["id"])
    token = _login(client, "c5@school.edu")

    resp = client.get(
        f"/api/counsellor/students/{student['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["consent_status"]["enforced"] is True
    assert body["consent_status"]["active"] is False


def test_404_for_unknown_student(db, client):
    _make_user(db, "c3@school.edu", "counsellor")
    token = _login(client, "c3@school.edu")

    resp = client.post(
        "/api/v1/students/does-not-exist/analyze",
        headers={"Authorization": f"Bearer {token}"},
        json={"posts": _posts(), "platform": "reddit"},
    )
    assert resp.status_code == 404


def test_blocks_unauthenticated(db, client):
    resp = client.post(
        f"/api/v1/students/{'x' * 36}/analyze",
        json={"posts": _posts(), "platform": "reddit"},
    )
    assert resp.status_code == 401


def test_blocks_pending_counsellor_at_permission_layer(db, client):
    counsellor = db.create_user(
        "c4@school.edu", "C4", hash_password("pw-12345"), role_type="counsellor"
    )
    student = _make_user(db, "s4@school.edu", "student")
    database.assign_student_to_counsellor(counsellor["id"], student["id"])
    _grant_active_consent(db, student["id"], counsellor["id"])
    token = _login(client, "c4@school.edu")

    resp = client.post(
        f"/api/v1/students/{student['id']}/analyze",
        headers={"Authorization": f"Bearer {token}"},
        json={"posts": _posts(), "platform": "reddit"},
    )
    assert resp.status_code == 403


def test_rejects_malformed_posts(db, client):
    counsellor = _make_user(db, "c5@school.edu", "counsellor")
    student = _make_user(db, "s5@school.edu", "student")
    database.assign_student_to_counsellor(counsellor["id"], student["id"])
    _grant_active_consent(db, student["id"], counsellor["id"])
    token = _login(client, "c5@school.edu")

    resp = client.post(
        f"/api/v1/students/{student['id']}/analyze",
        headers={"Authorization": f"Bearer {token}"},
        json={"posts": [{"text": "no risk score"}], "platform": "reddit"},
    )
    assert resp.status_code == 400
