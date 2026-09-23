"""Tests for the adult-gated self-analysis workspace.

Covers: adult category gate, encrypted-at-rest credentials that are never
echoed, no-fake-success sessions (``no_data`` instead of a fabricated score),
and cross-user session isolation (IDOR). Platform retrieval is monkeypatched so
the suite never touches the network or the ML model.
"""

import os
import inspect
from datetime import datetime, timezone

os.environ.setdefault("JWT_SECRET", "self-analyze-test-secret")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.auth import hash_password  # noqa: E402
from backend.services import self_analysis  # noqa: E402


@pytest.fixture()
def client(db):
    from backend.main import app

    with TestClient(app) as c:
        yield c


def _approve(db, user_id):
    conn = db.get_db()
    conn.execute("UPDATE users SET status = 'approved' WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()


def _make_adult(db, email: str) -> dict:
    user = db.create_user(
        email,
        email.split("@")[0].title(),
        hash_password("pw-12345"),
        role_type="student",
    )
    _approve(db, user["id"])
    assert db.update_user_onboarding(user["id"], "adult")
    fresh = db.get_user_by_id(user["id"])
    assert (fresh or {}).get("user_category") == "adult"
    return fresh


def _make_pending(db, email: str) -> dict:
    user = db.create_user(
        email,
        email.split("@")[0].title(),
        hash_password("pw-12345"),
        role_type="student",
    )
    _approve(db, user["id"])
    return user


def _login(client, email: str) -> str:
    resp = client.post("/api/auth/login", json={"email": email, "password": "pw-12345"})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _connect(parent_db, user_id: str, platform: str, handle: str, creds=None) -> dict:
    return parent_db.save_social_account(
        user_id, platform, handle, None, credentials=creds or None
    )


def test_self_routes_require_adult_category(db, client):
    _make_pending(db, "pending@self.test")
    _make_adult(db, "adult@self.test")
    token = _login(client, "pending@self.test")

    resp = client.get(
        "/api/self/platforms", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 403
    resp = client.post(
        "/api/self/analyze",
        headers={"Authorization": f"Bearer {token}"},
        json={"platform": "reddit"},
    )
    assert resp.status_code == 403

    token_adult = _login(client, "adult@self.test")
    resp = client.get(
        "/api/self/platforms", headers={"Authorization": f"Bearer {token_adult}"}
    )
    assert resp.status_code == 200
    slugs = [p["key"] for p in resp.json()["platforms"]]
    assert "reddit" in slugs and "bluesky" in slugs


def test_connect_encrypts_credentials_and_never_echoes(db, client):
    adult = _make_adult(db, "creds@self.test")
    _connect(
        db,
        adult["id"],
        "bluesky",
        "me@mydomain.bsky.social",
        {"app_password": "abcd-efgh-ijkl-mnop"},
    )

    # At rest: app password is ciphertext, not a raw string.
    conn = db.get_db()
    row = conn.execute(
        "SELECT credentials_json FROM student_social_accounts WHERE student_id = ? AND platform = 'bluesky'",
        (adult["id"],),
    ).fetchone()
    conn.close()
    assert row and row["credentials_json"]
    assert "abcd-efgh-ijkl-mnop" not in row["credentials_json"]

    # Over the wire: credentials are never returned.
    token = _login(client, "creds@self.test")
    accs = client.get(
        "/api/self/social-accounts", headers={"Authorization": f"Bearer {token}"}
    ).json()["accounts"]
    assert accs[0]["platform"] == "bluesky"
    assert accs[0]["has_credentials"] is True
    serialized = str(accs)
    assert "app_password" not in serialized
    assert "abcd-efgh-ijkl-mnop" not in serialized


def test_analyze_with_no_data_never_fakes_a_score(db, client, monkeypatch):
    adult = _make_adult(db, "nodata@self.test")
    _connect(db, adult["id"], "reddit", "sneaky_snack")

    async def fake_reddit(user_id):
        return {
            "platform": "reddit",
            "status": "no_data",
            "message": "No public posts found.",
        }

    monkeypatch.setattr(self_analysis, "_ANALYZERS", {"reddit": fake_reddit})

    token = _login(client, "nodata@self.test")
    resp = client.post(
        "/api/self/analyze",
        headers={"Authorization": f"Bearer {token}"},
        json={"platform": "reddit"},
    )
    assert resp.status_code == 403
    assert "assigned counsellor" in resp.json()["detail"].lower()


def test_analyze_only_uses_own_connected_accounts(db, client, monkeypatch):
    adult_a = _make_adult(db, "owna@self.test")
    _connect(db, adult_a["id"], "reddit", "alice-reddit")

    async def fake_reddit_ok(user_id):
        now = datetime.now(timezone.utc).isoformat()
        return {
            "platform": "reddit",
            "status": "ok",
            "message": "OK",
            "posts": [
                {
                    "platform": "reddit",
                    "text": "I have been struggling to sleep and nothing helps these days",
                    "risk_score": 0.85,
                    "level": "critical",
                    "date": now,
                    "url": "https://reddit.com/user/alice/1",
                }
            ],
        }

    monkeypatch.setattr(self_analysis, "_ANALYZERS", {"reddit": fake_reddit_ok})

    # Self-service analysis is deliberately unavailable: an assigned
    # counsellor performs analysis after account ownership is verified.
    token_a = _login(client, "owna@self.test")
    ra = client.post(
        "/api/self/analyze",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"platform": "reddit"},
    )
    assert ra.status_code == 403


def test_mixed_platform_results_are_recorded_as_partial(db, client, monkeypatch):
    adult = _make_adult(db, "partial@self.test")
    _connect(db, adult["id"], "reddit", "partial-reddit")
    _connect(
        db, adult["id"], "bluesky", "partial.bsky.social", {"app_password": "abcd"}
    )

    async def fake_reddit(user_id):
        return {
            "platform": "reddit",
            "status": "ok",
            "message": "OK",
            "posts": [
                {
                    "platform": "reddit",
                    "text": "I am having a difficult week but I am reaching out for support",
                    "risk_score": 0.25,
                    "level": "low",
                    "date": datetime.now(timezone.utc).isoformat(),
                    "url": "https://reddit.com/u/partial-reddit/1",
                }
            ],
        }

    async def fake_bluesky(user_id):
        return {
            "platform": "bluesky",
            "status": "error",
            "message": "Authentication required.",
        }

    monkeypatch.setattr(
        self_analysis, "_ANALYZERS", {"reddit": fake_reddit, "bluesky": fake_bluesky}
    )

    token = _login(client, "partial@self.test")
    resp = client.post(
        "/api/self/analyze", headers={"Authorization": f"Bearer {token}"}, json={}
    )
    assert resp.status_code == 403


def test_targeted_analysis_rejects_another_connected_platform(db, client, monkeypatch):
    adult = _make_adult(db, "targeted@self.test")
    _connect(db, adult["id"], "reddit", "targeted-reddit")
    token = _login(client, "targeted@self.test")

    resp = client.post(
        "/api/self/analyze",
        headers={"Authorization": f"Bearer {token}"},
        json={"platform": "bluesky"},
    )
    assert resp.status_code == 403


def test_guess_other_session_id_is_404(db, client):
    _make_adult(db, "idor@self.test")
    token = _login(client, "idor@self.test")
    resp = client.get(
        f"/api/self/analysis-sessions/{'deadbeef' * 4}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_verify_writes_public_verification_status(db, client, monkeypatch):
    adult = _make_adult(db, "verify@self.test")
    _connect(db, adult["id"], "reddit", "real-user")

    def fake_fetch(username: str):
        return [
            {
                "text": "hello everyone this is a public post about a topic worth talking through",
                "date": datetime.now(timezone.utc).isoformat(),
                "url": "https://reddit.com/r/x/1",
            }
        ]

    import backend.main as main_mod

    monkeypatch.setattr(main_mod, "_fetch_reddit_rss_posts", fake_fetch)

    token = _login(client, "verify@self.test")
    resp = client.post(
        "/api/self/social-accounts/reddit/verify",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400
    assert "profile url" in resp.json()["detail"].lower()


def test_not_retrievable_platform_analyzer_is_awaitable(db):
    """A connected account whose platform can't be retrieved must not crash the
    analyzer loop with a sync-dict ``await`` error (the deployed 503 root cause)."""

    for slug in ("instagram", "linkedin", "tiktok", "facebook", "twitter"):
        assert slug in self_analysis._ANALYZERS, f"missing analyzer for {slug}"
        analyzer = self_analysis._ANALYZERS[slug]
        assert callable(analyzer)
        assert inspect.iscoroutinefunction(analyzer), f"{slug} analyzer must be async"


def test_self_history_excludes_non_self_sessions(db, client):
    """Legacy counsellor/consent-gated sessions must never leak into the adult
    self-service history (their findings shape would crash the frontend)."""

    from backend.database import create_analysis_session

    adult = _make_adult(db, "hist@self.test")

    legacy = create_analysis_session(
        student_id=adult["id"],
        counsellor_id=None,
        institution_id=None,
        consent_id=None,
        analysis_type="counsellor_student",
        platforms=["reddit"],
        findings={"posts": [], "result": {"rolling_score": 0.4}},
    )
    own_self = create_analysis_session(
        student_id=adult["id"],
        counsellor_id=None,
        institution_id=None,
        consent_id=None,
        analysis_type="self",
        platforms=["reddit"],
        findings={"platforms_analyzed": ["reddit"], "posts_analyzed": 0},
    )

    token = _login(client, "hist@self.test")
    resp = client.get(
        "/api/self/analysis-sessions", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200, resp.text
    ids = [s["id"] for s in resp.json()["sessions"]]
    assert own_self["id"] in ids
    assert legacy["id"] not in ids, (
        "counsellor_student sessions must not appear in self history"
    )

    detail = client.get(
        f"/api/self/analysis-sessions/{legacy['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert detail.status_code == 404, (
        "counsellor_student session detail must 404 for the adult"
    )


def test_delete_wipes_credentials(db, client):
    adult = _make_adult(db, "del@self.test")
    _connect(
        db,
        adult["id"],
        "bluesky",
        "del@del.bsky.social",
        {"app_password": "aaaa-bbbb-cccc-dddd"},
    )
    token = _login(client, "del@self.test")

    resp = client.delete(
        "/api/self/social-accounts/bluesky",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200

    conn = db.get_db()
    row = conn.execute(
        "SELECT active, credentials_json FROM student_social_accounts WHERE student_id = ? AND platform = 'bluesky'",
        (adult["id"],),
    ).fetchone()
    conn.close()
    assert row and row["active"] == 0
    assert row["credentials_json"] is None
