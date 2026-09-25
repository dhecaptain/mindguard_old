"""Tests for counsellor student-list scoping (M7).

A counsellor must not be able to enumerate the platform-wide student
directory. ``GET /api/counsellor/students`` is scoped to students the
counsellor has a consent relationship with; admins still see all.
"""

import os

os.environ.setdefault("JWT_SECRET", "student-scope-test-secret")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import database  # noqa: E402
from backend.auth import hash_password  # noqa: E402


@pytest.fixture(scope="module")
def client():
    from backend.main import app

    with TestClient(app) as c:
        yield c


def _make(db, email: str, role: str) -> dict:
    user = database.create_user(
        email, email.split("@")[0].title(), hash_password("pw-12345"), role_type=role
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


def test_counsellor_sees_only_consent_linked_students(db, client, monkeypatch):
    monkeypatch.delenv("RECAPTCHA_SECRET", raising=False)
    a = _make(db, "scope1@school.edu", "counsellor")
    b = _make(db, "scope2@school.edu", "counsellor")
    s1 = _make(db, "s1@school.edu", "student")
    s2 = _make(db, "s2@school.edu", "student")
    _make(db, "s3@school.edu", "student")

    database.assign_student_to_counsellor(a["id"], s1["id"])
    database.assign_student_to_counsellor(b["id"], s2["id"])
    database.create_consent(s1["id"], a["id"], "s1@school.edu", "student", ["reddit"])
    database.create_consent(s2["id"], b["id"], "s2@school.edu", "student", ["reddit"])

    token = _token(client, "scope1@school.edu")
    resp = client.get(
        "/api/counsellor/students", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    emails = {s["email"] for s in resp.json()}
    assert emails == {"s1@school.edu"}, f"expected only assigned student, got {emails}"


def test_counsellor_with_no_consents_sees_empty_list(db, client, monkeypatch):
    monkeypatch.delenv("RECAPTCHA_SECRET", raising=False)
    _make(db, "scope3@school.edu", "counsellor")
    _make(db, "s4@school.edu", "student")

    token = _token(client, "scope3@school.edu")
    resp = client.get(
        "/api/counsellor/students", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    assert resp.json() == []


def test_admin_still_sees_all_students(db, client, monkeypatch):
    monkeypatch.delenv("RECAPTCHA_SECRET", raising=False)
    _make(db, "scopeadmin@school.edu", "admin")
    institution = database.create_institution("Scoped School", "k12")
    s1 = _make(db, "s5@school.edu", "student")
    s2 = _make(db, "s6@school.edu", "student")
    conn = db.get_db()
    conn.executemany(
        "UPDATE users SET institution_id = ? WHERE id = ?",
        [(institution["id"], s1["id"]), (institution["id"], s2["id"])],
    )
    conn.commit()
    conn.close()

    token = _token(client, "scopeadmin@school.edu")
    resp = client.get(
        "/api/counsellor/students", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    emails = {s["email"] for s in resp.json()}
    assert emails == {"s5@school.edu", "s6@school.edu"}


def test_student_detail_requires_consent_relationship(db, client, monkeypatch):
    monkeypatch.delenv("RECAPTCHA_SECRET", raising=False)
    a = _make(db, "scope4@school.edu", "counsellor")
    _make(db, "scope5@school.edu", "counsellor")
    s = _make(db, "s7@school.edu", "student")
    database.create_consent(s["id"], a["id"], "s7@school.edu", "student", ["reddit"])
    database.assign_student_to_counsellor(a["id"], s["id"])

    outsider = _token(client, "scope5@school.edu")
    resp = client.get(
        f"/api/counsellor/students/{s['id']}",
        headers={"Authorization": f"Bearer {outsider}"},
    )
    assert resp.status_code == 403

    owner = _token(client, "scope4@school.edu")
    resp = client.get(
        f"/api/counsellor/students/{s['id']}",
        headers={"Authorization": f"Bearer {owner}"},
    )
    assert resp.status_code == 200, resp.text


def test_unassigned_but_consented_denied(db, client, monkeypatch):
    monkeypatch.delenv("RECAPTCHA_SECRET", raising=False)
    a = _make(db, "unass_c1@school.edu", "counsellor")
    s = _make(db, "unass_s1@school.edu", "student")
    database.create_consent(
        s["id"], a["id"], "unass_s1@school.edu", "student", ["reddit"]
    )
    # no assignment
    token = _token(client, "unass_c1@school.edu")
    resp = client.get(
        f"/api/counsellor/students/{s['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
    resp2 = client.get(
        f"/api/v1/students/{s['id']}/timeline",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp2.status_code == 403
    resp3 = client.get(
        f"/api/v1/students/{s['id']}/notes",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp3.status_code == 403


def test_institution_roster_scope_allows_linked_account_with_missing_user_scope(db):
    """Roster institution scope must backstop legacy user rows.

    Institution-managed imports can leave users.institution_id empty while
    the linked roster row and assignment already carry the correct tenant.
    Shared counsellor authorization must not reject appointments or other
    assigned-student actions in that state.
    """
    from backend.main import _require_counsellor_student_access

    institution = db.create_institution("Roster Scope School", "k12")
    counsellor = _make(db, "roster-scope-counsellor@school.edu", "counsellor")
    student = _make(db, "roster-scope-student@school.edu", "student")
    conn = db.get_db()
    conn.execute(
        "UPDATE users SET institution_id = ? WHERE id = ?",
        (institution["id"], counsellor["id"]),
    )
    conn.commit()
    conn.close()
    counsellor["institution_id"] = institution["id"]
    db.create_student(
        institution_id=institution["id"],
        student_id_hash="roster-scope-student",
        first_name_encrypted="Student",
        email_encrypted=student["email"],
        date_of_birth_encrypted="2005-01-01",
        is_minor=False,
        created_by=counsellor["id"],
        user_id=student["id"],
    )
    db.assign_student_to_counsellor(
        counsellor["id"], student["id"], institution["id"], counsellor["id"]
    )
    consent_owner = _make(db, "roster-scope-admin@school.edu", "school_admin")
    consent = db.create_consent(
        student["id"], consent_owner["id"], student["email"], "student", ["instagram"]
    )
    db.update_consent_status(consent["id"], "ACCEPTED")

    # Deliberately preserve the legacy blank user institution value.
    assert db.get_user_by_id(student["id"])["institution_id"] is None
    _require_counsellor_student_access(counsellor, student["id"])
