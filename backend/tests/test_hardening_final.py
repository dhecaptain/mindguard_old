"""Final hardening tests for assignment, platform, IDOR, pagination, revocation."""

import os

os.environ.setdefault("JWT_SECRET", "hardening-final-secret")
os.environ.setdefault("ENCRYPTION_KEY", "c" * 64)

from fastapi.testclient import TestClient
from backend import database
from backend.auth import hash_password, create_access_token
from backend.main import app
from backend.services import consent_service


def _user(db, email, role, status="approved", inst=None):
    u = database.create_user(
        email, email.split("@")[0], hash_password("pw-12345"), role_type=role
    )
    conn = db.get_db()
    conn.execute(
        "UPDATE users SET status=?, institution_id=? WHERE id=?",
        (status, inst, u["id"]),
    )
    conn.commit()
    conn.close()
    return database.get_user_by_id(u["id"])


def _token(u):
    return create_access_token(u["id"], u["role_type"])


def test_assigned_consented_appears(db):
    c = _user(db, "hc1@school.edu", "counsellor")
    s = _user(db, "hs1@school.edu", "student")
    database.assign_student_to_counsellor(c["id"], s["id"])
    database.create_consent(s["id"], c["id"], "hs1@school.edu", "student", ["Reddit"])
    with TestClient(app) as client:
        tok = _token(c)
        resp = client.get(
            "/api/counsellor/students", headers={"Authorization": f"Bearer {tok}"}
        )
        assert any(x["email"] == "hs1@school.edu" for x in resp.json())


def test_assigned_no_consent_not_in_detail(db):
    c = _user(db, "hc2@school.edu", "counsellor")
    s = _user(db, "hs2@school.edu", "student")
    database.assign_student_to_counsellor(c["id"], s["id"])
    with TestClient(app) as client:
        tok = _token(c)
        resp = client.get(
            f"/api/counsellor/students/{s['id']}",
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert resp.status_code == 403


def test_unassigned_consented_not_in_list(db):
    c = _user(db, "hc3@school.edu", "counsellor")
    s = _user(db, "hs3@school.edu", "student")
    database.create_consent(s["id"], c["id"], "hs3@school.edu", "student", ["Reddit"])
    with TestClient(app) as client:
        tok = _token(c)
        resp = client.get(
            "/api/counsellor/students", headers={"Authorization": f"Bearer {tok}"}
        )
        assert all(x["email"] != "hs3@school.edu" for x in resp.json())


def test_cross_institution_denied(db):
    inst1 = database.create_institution("Inst1", "school")
    inst2 = database.create_institution("Inst2", "school")
    c = _user(db, "hc4@school.edu", "counsellor", inst=inst1["id"])
    s = _user(db, "hs4@school.edu", "student", inst=inst2["id"])
    database.assign_student_to_counsellor(c["id"], s["id"], inst2["id"])
    database.create_consent(s["id"], c["id"], "hs4@school.edu", "student", ["Reddit"])
    with TestClient(app) as client:
        tok = _token(c)
        resp = client.get(
            f"/api/counsellor/students/{s['id']}",
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert resp.status_code == 403


def test_deactivated_denied(db):
    c = _user(db, "hc5@school.edu", "counsellor", status="revoked")
    s = _user(db, "hs5@school.edu", "student")
    database.assign_student_to_counsellor(c["id"], s["id"])
    database.create_consent(s["id"], c["id"], "hs5@school.edu", "student", ["Reddit"])
    with TestClient(app) as client:
        tok = _token(c)
        resp = client.get(
            "/api/counsellor/students", headers={"Authorization": f"Bearer {tok}"}
        )
        assert resp.status_code in (401, 403)


def test_empty_consented_denied(db):
    c = _user(db, "hc6@school.edu", "counsellor")
    s = _user(db, "hs6@school.edu", "student")
    database.assign_student_to_counsellor(c["id"], s["id"])
    consent = database.create_consent(s["id"], c["id"], "hs6@school.edu", "student", [])
    # dispatch and accept with empty platforms
    consent_service.dispatch_consent(consent["id"], c["id"])
    consent_service.accept_consent(consent["id"], "Test", "127.0.0.1")
    with TestClient(app) as client:
        tok = _token(c)
        resp = client.post(
            f"/api/v1/students/{s['id']}/analyze",
            json={
                "platform": "Instagram",
                "posts": [{"text": "hello", "risk_score": 0.5}],
            },
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert resp.status_code == 400
        assert "not in consented" in resp.text.lower()


def test_referral_idor(db):
    c1 = _user(db, "cref1@school.edu", "counsellor")
    c2 = _user(db, "cref2@school.edu", "counsellor")
    s = _user(db, "sref@school.edu", "student")
    database.assign_student_to_counsellor(c1["id"], s["id"])
    database.create_consent(s["id"], c1["id"], "sref@school.edu", "student", ["Reddit"])
    with TestClient(app) as client:
        tok2 = _token(c2)
        resp = client.post(
            "/api/counsellor/referrals",
            json={"student_id": s["id"], "urgency": "high"},
            headers={"Authorization": f"Bearer {tok2}"},
        )
        assert resp.status_code == 403


def test_conversation_idor(db):
    c1 = _user(db, "cconv1@school.edu", "counsellor")
    c2 = _user(db, "cconv2@school.edu", "counsellor")
    s = _user(db, "sconv@school.edu", "student")
    database.assign_student_to_counsellor(c1["id"], s["id"])
    database.create_consent(
        s["id"], c1["id"], "sconv@school.edu", "student", ["Reddit"]
    )
    with TestClient(app) as client:
        tok2 = _token(c2)
        resp = client.get(
            f"/api/counsellor/conversations/{s['id']}",
            headers={"Authorization": f"Bearer {tok2}"},
        )
        assert resp.status_code == 403


def test_pagination(db):
    c = _user(db, "cpag@school.edu", "counsellor")
    s = _user(db, "spag@school.edu", "student")
    database.assign_student_to_counsellor(c["id"], s["id"])
    consent = database.create_consent(
        s["id"], c["id"], "spag@school.edu", "student", ["Reddit"]
    )
    consent_service.dispatch_consent(consent["id"], c["id"])
    consent_service.accept_consent(consent["id"], "Test", "127.0.0.1")
    for i in range(5):
        database.create_analysis_session(
            s["id"],
            c["id"],
            None,
            consent["id"],
            "test",
            ["Reddit"],
            {"prob": 0.5},
            0.5,
        )
    with TestClient(app) as client:
        tok = _token(c)
        resp = client.get(
            f"/api/v1/students/{s['id']}/analysis-sessions?limit=2&offset=0",
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert resp.status_code == 200
        assert len(resp.json()["sessions"]) == 2
        assert resp.json()["total"] == 5
        resp2 = client.get(
            f"/api/v1/students/{s['id']}/analysis-sessions?limit=2&offset=2",
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert len(resp2.json()["sessions"]) == 2
