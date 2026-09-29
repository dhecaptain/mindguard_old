import os
from urllib.parse import parse_qs, urlparse

os.environ.setdefault("JWT_SECRET", "guest-voice-test-secret")

from fastapi.testclient import TestClient

from backend.auth import hash_password


def _client():
    from backend.main import app

    return TestClient(app)


def _login(client, email):
    response = client.post(
        "/api/auth/login", json={"email": email, "password": "guest-test-password"}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _counsellor(db, email):
    user = db.create_user(
        email,
        "Guest Counsellor",
        hash_password("guest-test-password"),
        role_type="counsellor",
    )
    conn = db.get_db()
    conn.execute("UPDATE users SET status='approved' WHERE id=?", (user["id"],))
    conn.commit()
    conn.close()
    return user


def test_guest_analysis_requires_single_use_consent_and_is_counsellor_scoped(db):
    owner = _counsellor(db, "counsellor.one@example.org")
    other = _counsellor(db, "counsellor.two@example.org")
    with _client() as client:
        owner_headers = _login(client, owner["email"])
        other_headers = _login(client, other["email"])
        created = client.post(
            "/api/v1/guest-analysis/cases",
            headers=owner_headers,
            json={"platforms": {"reddit": "visitor_handle_01"}},
        )
        assert created.status_code == 201, created.text
        case_id = created.json()["id"]
        token = parse_qs(urlparse(created.json()["consent_url"]).query)["token"][0]
        preview = client.get(
            "/api/v1/guest-analysis/consent", params={"token": token}
        )
        assert preview.status_code == 200
        assert preview.json()["accounts"] == [
            {
                "platform": "reddit",
                "handle": "visitor_handle_01",
                "ownership_status": "visitor_authorized_unverified",
            }
        ]

        pending_analysis = client.post(
            f"/api/v1/guest-analysis/cases/{case_id}/run", headers=owner_headers
        )
        assert pending_analysis.status_code == 403
        assert (
            client.get(
                f"/api/v1/guest-analysis/cases/{case_id}", headers=other_headers
            ).status_code
            == 404
        )

        accepted = client.post(
            "/api/v1/guest-analysis/consent",
            json={"token": token, "accepted": True},
        )
        assert accepted.status_code == 200, accepted.text
        replayed = client.post(
            "/api/v1/guest-analysis/consent",
            json={"token": token, "accepted": True},
        )
        assert replayed.status_code == 400

    conn = db.get_db()
    account = conn.execute(
        "SELECT handle_encrypted FROM guest_platform_authorizations WHERE case_id=?",
        (case_id,),
    ).fetchone()
    case = conn.execute(
        "SELECT status,consent_method FROM guest_cases WHERE id=?", (case_id,)
    ).fetchone()
    conn.close()
    assert account and "visitor_handle_01" not in account["handle_encrypted"]
    assert case["status"] == "consented"
    assert case["consent_method"] == "visitor_link"


def test_guest_decline_deletes_preentered_handles_and_invalidates_link(db):
    owner = _counsellor(db, "counsellor.decline@example.org")
    with _client() as client:
        headers = _login(client, owner["email"])
        created = client.post(
            "/api/v1/guest-analysis/cases",
            headers=headers,
            json={"platforms": {"bluesky": "visitor.bsky.social"}},
        )
        assert created.status_code == 201, created.text
        case_id = created.json()["id"]
        token = parse_qs(urlparse(created.json()["consent_url"]).query)["token"][0]
        declined = client.post(
            "/api/v1/guest-analysis/consent",
            json={"token": token, "accepted": False},
        )
        assert declined.status_code == 200
        assert declined.json()["status"] == "declined"
        assert client.get(
            "/api/v1/guest-analysis/consent", params={"token": token}
        ).status_code == 400
        assert client.post(
            f"/api/v1/guest-analysis/cases/{case_id}/run", headers=headers
        ).status_code == 403

    conn = db.get_db()
    handles = conn.execute(
        "SELECT COUNT(*) FROM guest_platform_authorizations WHERE case_id=?",
        (case_id,),
    ).fetchone()[0]
    status = conn.execute(
        "SELECT status FROM guest_cases WHERE id=?", (case_id,)
    ).fetchone()["status"]
    conn.close()
    assert handles == 0
    assert status == "declined"


def test_expired_unanswered_guest_consent_purges_handles(db):
    from backend.routes.guest_analysis import purge_expired_guest_cases

    owner = _counsellor(db, "counsellor.expiry@example.org")
    with _client() as client:
        created = client.post(
            "/api/v1/guest-analysis/cases",
            headers=_login(client, owner["email"]),
            json={"platforms": {"reddit": "visitor_handle_expiry"}},
        )
        assert created.status_code == 201, created.text
        case_id = created.json()["id"]
    conn = db.get_db()
    conn.execute(
        "UPDATE guest_cases SET consent_expires_at='2000-01-01T00:00:00+00:00' WHERE id=?",
        (case_id,),
    )
    conn.commit()
    conn.close()

    assert purge_expired_guest_cases() == 1
    conn = db.get_db()
    handles = conn.execute(
        "SELECT COUNT(*) FROM guest_platform_authorizations WHERE case_id=?",
        (case_id,),
    ).fetchone()[0]
    case = conn.execute(
        "SELECT status,deleted_at FROM guest_cases WHERE id=?", (case_id,)
    ).fetchone()
    conn.close()
    assert handles == 0
    assert case["status"] == "expired_deleted"
    assert case["deleted_at"]


def test_voice_is_disabled_until_review_and_provider_configuration(db, monkeypatch):
    user = db.create_user(
        "adult@example.org",
        "Adult User",
        hash_password("guest-test-password"),
        role_type="student",
    )
    conn = db.get_db()
    conn.execute(
        "UPDATE users SET status='approved',user_category='adult' WHERE id=?",
        (user["id"],),
    )
    conn.commit()
    conn.close()
    monkeypatch.setenv("VOICE_SUPPORT_ENABLED", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-provider-key")
    for name in (
        "VOICE_CLINICAL_REVIEW_COMPLETE",
        "VOICE_CHILD_SAFEGUARDING_REVIEW_COMPLETE",
        "VOICE_PRIVACY_REVIEW_COMPLETE",
        "VOICE_ACCESSIBILITY_REVIEW_COMPLETE",
    ):
        monkeypatch.setenv(name, "false")

    with _client() as client:
        headers = _login(client, user["email"])
        availability = client.get("/api/v1/voice/availability", headers=headers)
        assert availability.status_code == 200
        assert availability.json()["enabled"] is True
        assert availability.json()["review_gate_ready"] is False
        start = client.post(
            "/api/v1/voice/sessions",
            headers=headers,
            json={"accepted_notice": True, "exercise": "grounding"},
        )
        assert start.status_code == 503
        assert "review" in start.json()["detail"].lower()


def test_voice_minor_safety_event_is_transient_and_truthful_without_care_recipient(
    db, monkeypatch
):
    from backend.routes import voice_support

    user = db.create_user(
        "minor@example.org",
        "Young Person",
        hash_password("guest-test-password"),
        role_type="student",
    )
    conn = db.get_db()
    conn.execute(
        "UPDATE users SET status='approved',user_category='minor' WHERE id=?",
        (user["id"],),
    )
    conn.commit()
    conn.close()

    for name in (
        "VOICE_SUPPORT_ENABLED",
        "VOICE_CLINICAL_REVIEW_COMPLETE",
        "VOICE_CHILD_SAFEGUARDING_REVIEW_COMPLETE",
        "VOICE_PRIVACY_REVIEW_COMPLETE",
        "VOICE_ACCESSIBILITY_REVIEW_COMPLETE",
    ):
        monkeypatch.setenv(name, "true")
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-provider-key")
    monkeypatch.setenv("VOICE_SAFETY_SALT", "unit-test-only-safety-salt-at-least-32-chars")
    captured = {}

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {
                "id": "provider-session-test",
                "value": "ephemeral-client-credential",
                "expires_at": 1_900_000_000,
            }

    class FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def post(self, url, *, headers, json):
            captured["url"] = url
            captured["payload"] = json
            return FakeResponse()

    monkeypatch.setattr(
        voice_support.httpx, "AsyncClient", lambda **_: FakeAsyncClient()
    )
    with _client() as client:
        headers = _login(client, user["email"])
        availability = client.get("/api/v1/voice/availability", headers=headers)
        assert availability.status_code == 200 and availability.json()["is_minor"] is True
        start = client.post(
            "/api/v1/voice/sessions",
            headers=headers,
            json={"accepted_notice": True, "exercise": "grounding"},
        )
        assert start.status_code == 201, start.text
        assert start.json()["max_duration_seconds"] == 900
        assert start.json()["consent_version"] == "voice-v1"
        assert "young person" in captured["payload"]["session"]["instructions"]
        assert "No care professional is currently connected" in captured["payload"]["session"]["instructions"]
        duplicate = client.post(
            "/api/v1/voice/sessions",
            headers=headers,
            json={"accepted_notice": True, "exercise": "grounding"},
        )
        assert duplicate.status_code == 409

        transcript = "I want to end my life tonight"
        alert = client.post(
            f"/api/v1/voice/sessions/{start.json()['session_id']}/safety-event",
            headers=headers,
            json={"transcript_segment": transcript},
        )
        assert alert.status_code == 200
        assert alert.json()["delivery_status"] == "no_authorized_recipient"
        assert "could not notify" in alert.json()["message"].lower()
        assert "116" in alert.json()["message"]

    conn = db.get_db()
    session = conn.execute(
        "SELECT consent_version,summary_encrypted,safety_outcome FROM voice_support_sessions WHERE id=?",
        (start.json()["session_id"],),
    ).fetchone()
    conn.close()
    assert session["consent_version"] == "voice-v1"
    assert session["summary_encrypted"] is None
    assert session["safety_outcome"] == "urgent"
    assert transcript not in str(dict(session))


def test_voice_alert_does_not_reach_workplace_provider_after_participation_withdrawal(db):
    from datetime import datetime, timedelta, timezone
    from backend.services.crypto import encrypt_pii

    company = db.create_institution("Voice Test Company", "company")
    employee = db.create_user(
        "worker@voice-company.test",
        "Workplace Employee",
        hash_password("guest-test-password"),
        role_type="workplace_employee",
        institution_id=company["id"],
    )
    provider = db.create_user(
        "provider@voice-care.test",
        "Independent Provider",
        hash_password("guest-test-password"),
        role_type="workplace_provider",
    )
    now = datetime.now(timezone.utc).isoformat()
    active_until = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
    conn = db.get_db()
    conn.execute("UPDATE institutions SET status='ACTIVE' WHERE id=?", (company["id"],))
    conn.execute("UPDATE users SET status='approved',user_category='workplace_employee' WHERE id=?", (employee["id"],))
    conn.execute("UPDATE users SET status='approved',user_category='workplace_provider' WHERE id=?", (provider["id"],))
    conn.execute(
        "INSERT INTO workplace_settings (company_id,work_email_domains_json,created_at,updated_at) VALUES (?,?,?,?)",
        (company["id"], '["voice-company.test"]', now, now),
    )
    conn.execute(
        "INSERT INTO workplace_memberships (id,company_id,user_id,status,notice_version,consented_at,created_at,updated_at) VALUES ('voice-membership',?,?,'active','v1',?,?,?)",
        (company["id"], employee["id"], now, now, now),
    )
    conn.execute(
        "INSERT INTO workplace_provider_credentials (provider_id,title_encrypted,qualification_encrypted,registration_encrypted,verification_reference_encrypted,status,reviewed_by,reviewed_at) VALUES (?,?,?,?,?,'verified',?,?)",
        (provider["id"], encrypt_pii("Counsellor"), encrypt_pii("Qualification"), encrypt_pii("REG-VOICE"), encrypt_pii("reviewed"), provider["id"], now),
    )
    conn.execute(
        "INSERT INTO workplace_providers (company_id,provider_id,status,created_at) VALUES (?,?,'active',?)",
        (company["id"], provider["id"], now),
    )
    conn.execute(
        "INSERT INTO workplace_checkins (id,company_id,user_id,answers_json,created_at) VALUES ('voice-checkin',?,?,?,?)",
        (company["id"], employee["id"], encrypt_pii("{}"), now),
    )
    conn.execute(
        "INSERT INTO workplace_support_cases (id,company_id,user_id,provider_id,status,share_consent_at,shared_checkin_id,created_at,updated_at) VALUES ('voice-case',?,?,?,'open',?,'voice-checkin',?,?)",
        (company["id"], employee["id"], provider["id"], now, now, now),
    )
    conn.execute(
        "INSERT INTO voice_support_sessions (id,user_id,status,consented_at,consent_version,safety_outcome,alert_recipient_id,active_expires_at,expires_at,created_at,updated_at) VALUES ('voice-withdrawal',?,'active',?,'voice-v1','none',?,?,?, ?,?)",
        (employee["id"], now, provider["id"], active_until, active_until, now, now),
    )
    conn.execute(
        "UPDATE workplace_memberships SET status='withdrawn',withdrawn_at=?,updated_at=? WHERE id='voice-membership'",
        (now, now),
    )
    conn.commit()
    conn.close()

    with _client() as client:
        response = client.post(
            "/api/v1/voice/sessions/voice-withdrawal/safety-event",
            headers=_login(client, employee["email"]),
            json={"transcript_segment": "I want to end my life"},
        )
    assert response.status_code == 200
    assert response.json()["delivery_status"] == "no_authorized_recipient"

    conn = db.get_db()
    session = conn.execute(
        "SELECT alert_recipient_id,alert_delivery_status FROM voice_support_sessions WHERE id='voice-withdrawal'"
    ).fetchone()
    notifications = conn.execute(
        "SELECT COUNT(*) FROM notifications WHERE user_id=? AND title='Urgent voice-support follow-up'",
        (provider["id"],),
    ).fetchone()[0]
    conn.close()
    assert session["alert_recipient_id"] is None
    assert session["alert_delivery_status"] == "no_authorized_recipient"
    assert notifications == 0
