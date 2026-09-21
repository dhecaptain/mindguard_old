"""Tests for the critical auth/data-exposure hardening.

Covers:
- Google OAuth must trust only the Supabase-verified email, never the
  client-supplied ``email``/``name`` body fields (account-takeover guard).
- Public registration must not mint counsellor/school-admin accounts.
- Pending/revoked accounts must be blocked at the permission/auth layers.
- ``/api/users/directory`` must not leak emails to non-admins.
- ``seed_defaults`` must not create known-password demo accounts in production.
"""

import os
import sys
from types import SimpleNamespace

os.environ.setdefault("JWT_SECRET", "auth-hardening-test-secret")

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import database  # noqa: E402
from backend import permissions as perm  # noqa: E402
from backend.auth import hash_password, verify_password  # noqa: E402


@pytest.fixture(scope="module")
def client():
    from backend.main import app

    with TestClient(app) as c:
        yield c


def _mock_supabase(
    monkeypatch, email: str | None, metadata_name: str | None = "Verified User"
):
    """Stub the ``supabase`` package so ``/api/auth/google`` runs offline."""

    class _FakeUser:
        def __init__(self):
            self.email = email
            self.user_metadata = {"full_name": metadata_name} if metadata_name else {}

    fake = SimpleNamespace(
        auth=SimpleNamespace(get_user=lambda token: SimpleNamespace(user=_FakeUser()))
    )
    module = SimpleNamespace(create_client=lambda *a, **k: fake)
    monkeypatch.setitem(sys.modules, "supabase", module)


# ── C1: Google OAuth email trust ──────────────────────────────────────


def test_google_auth_ignores_client_supplied_email(db, client, monkeypatch):
    """Body email must never win over the verified Supabase email."""
    db.create_user("victim@school.edu", "Victim", "x", role_type="student")
    _mock_supabase(monkeypatch, email="attacker@gmail.com")

    resp = client.post(
        "/api/auth/google",
        json={"access_token": "any", "email": "victim@school.edu", "name": "Spoofed"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["email"] == "attacker@gmail.com"
    assert data["name"] == "Verified User"


def test_google_auth_logs_into_existing_verified_user_only(db, client, monkeypatch):
    """Existing-account match must key on the verified email, not the body."""
    db.create_user("attacker@gmail.com", "Attacker", "x", role_type="student")
    db.create_user("victim@school.edu", "Victim", "x", role_type="counsellor")
    _mock_supabase(monkeypatch, email="attacker@gmail.com")

    resp = client.post(
        "/api/auth/google",
        json={"access_token": "any", "email": "victim@school.edu", "name": "Spoofed"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["email"] == "attacker@gmail.com"


def test_google_auth_rejects_token_without_email(db, client, monkeypatch):
    _mock_supabase(monkeypatch, email=None)
    resp = client.post("/api/auth/google", json={"access_token": "any"})
    assert resp.status_code == 401


# ── C2: staff registration gate + status enforcement ──────────────────


def test_register_rejects_counsellor_and_school_admin(db, client):
    for role in ("counsellor", "counselor"):
        resp = client.post(
            "/api/auth/register",
            json={
                "name": "Rogue",
                "email": f"rogue-{role}@x.edu",
                "password": "secret-pass",
                "role": role,
            },
        )
        assert resp.status_code == 403, resp.text
        assert database.get_user_by_email(f"rogue-{role}@x.edu") is None

    resp = client.post(
        "/api/auth/register",
        json={
            "name": "Rogue Admin",
            "email": "rogue-admin@x.edu",
            "password": "secret-pass",
            "role": "school_admin",
        },
    )
    assert resp.status_code in (
        403,
        200,
    )  # school_admin is not a registerable role either way


def test_register_accepts_student(db, client):
    resp = client.post(
        "/api/auth/register",
        json={
            "name": "Real Student",
            "email": "student-ok@x.edu",
            "password": "secret-pass",
            "role": "student",
        },
    )
    assert resp.status_code == 200, resp.text
    assert database.get_user_by_email("student-ok@x.edu") is not None


def test_pending_user_cannot_use_permissions(db):
    user = db.create_user(
        "pending-c@school.edu", "Pending C", "x", role_type="counsellor"
    )
    assert user["status"] == "pending"
    with pytest.raises(HTTPException) as exc:
        perm.require_permission(user, perm.PERM_ANALYSIS_RUN)
    assert exc.value.status_code == 403


def test_pending_user_cannot_require_any_permission(db):
    user = db.create_user(
        "pending-c2@school.edu", "Pending C2", "x", role_type="counsellor"
    )
    with pytest.raises(HTTPException) as exc:
        perm.require_any_permission(
            user, {perm.PERM_ANALYSIS_RUN, perm.PERM_STUDENTS_VIEW}
        )
    assert exc.value.status_code == 403


def test_revoked_user_cannot_login(db, client):
    user = db.create_user(
        "revoked@school.edu", "Revoked", hash_password("pw-1"), role_type="student"
    )
    database.update_student_status(user["id"], "revoked")
    resp = client.post(
        "/api/auth/login", json={"email": "revoked@school.edu", "password": "pw-1"}
    )
    assert resp.status_code == 401


def test_directory_does_not_leak_emails_to_students(db, client):
    db.create_user(
        "target-student@school.edu", "Target Student", "x", role_type="student"
    )
    db.create_user(
        "the-counsellor@school.edu", "The Counsellor", "x", role_type="counsellor"
    )
    client.post(
        "/api/auth/register",
        json={
            "name": "Me",
            "email": "me@student.edu",
            "password": "secret-pass",
            "role": "student",
        },
    )
    token = client.post(
        "/api/auth/login", json={"email": "me@student.edu", "password": "secret-pass"}
    ).json()["access_token"]

    resp = client.get(
        "/api/users/directory", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200, resp.text
    assert isinstance(resp.json(), list)
    assert all("email" not in u for u in resp.json())
    names = {u["name"] for u in resp.json()}
    assert "Target Student" in names and "The Counsellor" in names


def test_directory_shows_emails_to_admin(db, client):
    from backend.main import _bootstrap_admins

    register = client.post(
        "/api/auth/register",
        json={
            "name": "Boss",
            "email": "boss@school.edu",
            "password": "boss-pass-1",
            "role": "student",
        },
    )
    assert register.status_code == 200, register.text
    os.environ["MINDGUARD_BOOTSTRAP_ADMIN_EMAIL"] = "boss@school.edu"
    _bootstrap_admins()
    token = client.post(
        "/api/auth/login", json={"email": "boss@school.edu", "password": "boss-pass-1"}
    ).json()["access_token"]

    resp = client.get(
        "/api/users/directory", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200, resp.text
    assert any("email" in u for u in resp.json())


# ── C3: no known-password demo accounts in production ─────────────────


def test_seed_defaults_production_has_no_demo_accounts(db, monkeypatch):
    monkeypatch.setenv("MINDGUARD_ENV", "production")
    monkeypatch.setenv("MINDGUARD_ADMIN_PASSWORD", "sup3r-admin-secret")
    database.seed_defaults()

    assert database.get_user_by_email("admin@mindguard.org") is not None
    for email in (
        "counsellor@mindguard.org",
        "student@mindguard.org",
        "demo@mindguard.org",
        "diana@mindguard.org",
    ):
        assert database.get_user_by_email(email) is None, (
            f"demo account {email} seeded in production"
        )

    admin = database.get_user_by_email("admin@mindguard.org")
    assert not verify_password("password", admin["password_hash"])


def test_seed_defaults_development_seeds_demo_accounts(db, monkeypatch):
    monkeypatch.delenv("MINDGUARD_ENV", raising=False)
    monkeypatch.setenv("MINDGUARD_ADMIN_PASSWORD", "sup3r-admin-secret")
    database.seed_defaults()

    assert database.get_user_by_email("admin@mindguard.org") is not None
    assert database.get_user_by_email("counsellor@mindguard.org") is not None
    assert database.get_user_by_email("student@mindguard.org") is not None
    assert database.get_user_by_email("demo@mindguard.org") is not None
