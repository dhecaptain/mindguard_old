"""Focused integration coverage for server-authoritative Voice actions."""

import json
import os
import uuid
from datetime import datetime, timedelta, timezone

os.environ.setdefault("JWT_SECRET", "voice-action-test-secret")

from fastapi.testclient import TestClient

from backend.auth import hash_password
from backend.services.crypto import decrypt_pii, encrypt_pii


def _client():
    from backend.main import app

    return TestClient(app)


def _login(client, email, password="voice-action-test-password"):
    response = client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _active_session(db, user_id):
    now = datetime.now(timezone.utc)
    session_id = str(uuid.uuid4())
    conn = db.get_db()
    conn.execute(
        "INSERT INTO voice_support_sessions "
        "(id,user_id,status,consented_at,consent_version,safety_outcome,active_expires_at,"
        "expires_at,started_at,sideband_connected_at,created_at,updated_at) "
        "VALUES (?,?,'active',?,'voice-v2','none',?,?,?,?,?,?)",
        (
            session_id,
            user_id,
            now.isoformat(),
            (now + timedelta(minutes=10)).isoformat(),
            (now + timedelta(days=30)).isoformat(),
            now.isoformat(),
            now.isoformat(),
            now.isoformat(),
            now.isoformat(),
        ),
    )
    conn.commit()
    conn.close()
    return session_id


def _configure_voice(monkeypatch):
    for name in (
        "VOICE_SUPPORT_ENABLED",
        "VOICE_SERVER_SIDE_CONTROLS_ENABLED",
        "VOICE_CLINICAL_REVIEW_COMPLETE",
        "VOICE_CHILD_SAFEGUARDING_REVIEW_COMPLETE",
        "VOICE_PRIVACY_REVIEW_COMPLETE",
        "VOICE_ACCESSIBILITY_REVIEW_COMPLETE",
    ):
        monkeypatch.setenv(name, "true")
    monkeypatch.setenv("MINDGUARD_DISABLE_BACKGROUND_TASKS", "false")


def _company(db):
    company = db.create_institution("Voice Action Company", "company")
    admin = db.create_user(
        "voice-owner@acme.test", "Company Owner",
        hash_password("voice-action-test-password"), role_type="student",
    )
    now = datetime.now(timezone.utc).isoformat()
    conn = db.get_db()
    conn.execute("UPDATE institutions SET status='ACTIVE' WHERE id=?", (company["id"],))
    conn.execute(
        "UPDATE users SET status='approved',user_category='company_staff',role_type='company_admin',"
        "institution_id=?,workplace_admin_role='owner',workplace_invitation_status='accepted',"
        "workplace_terms_version='workplace-admin-v1',terms_accepted_at=? WHERE id=?",
        (company["id"], now, admin["id"]),
    )
    conn.execute(
        "INSERT INTO workplace_settings (company_id,work_email_domains_json,legal_review_complete,policy_status,created_at,updated_at) VALUES (?,?,1,'approved',?,?)",
        (company["id"], '["acme.test"]', now, now),
    )
    from backend.services.workplace_commercial import ensure_account

    ensure_account(conn, company["id"])
    conn.commit()
    conn.close()
    return company, db.get_user_by_id(admin["id"])


def _provider(db, company, reviewer):
    provider = db.create_user(
        "voice-provider@care.test", "Voice Provider",
        hash_password("voice-action-test-password"), role_type="workplace_provider",
    )
    now = datetime.now(timezone.utc).isoformat()
    conn = db.get_db()
    conn.execute(
        "UPDATE users SET status='approved',user_category='workplace_provider' WHERE id=?",
        (provider["id"],),
    )
    conn.execute(
        "INSERT INTO workplace_provider_credentials (provider_id,title_encrypted,qualification_encrypted,registration_encrypted,verification_reference_encrypted,status,reviewed_by,reviewed_at) VALUES (?,?,?,?,?,'verified',?,?)",
        (provider["id"], encrypt_pii("Counsellor"), encrypt_pii("Qualification"), encrypt_pii("REG-VOICE"), encrypt_pii("Reviewed"), reviewer["id"], now),
    )
    conn.execute(
        "INSERT INTO workplace_providers (company_id,provider_id,status,created_at) VALUES (?,?,'active',?)",
        (company["id"], provider["id"], now),
    )
    conn.commit()
    conn.close()
    return provider


def test_voice_actions_are_allowlisted_owned_and_explicit(db, monkeypatch):
    from backend.database import assign_student_to_counsellor, create_appointment

    _configure_voice(monkeypatch)
    student = db.create_user(
        "voice.student@example.test",
        "Voice Student",
        hash_password("voice-action-test-password"),
        role_type="student",
    )
    other = db.create_user(
        "voice.other@example.test",
        "Other Student",
        hash_password("voice-action-test-password"),
        role_type="student",
    )
    counsellor = db.create_user(
        "voice.counsellor@example.test",
        "Assigned Counsellor",
        hash_password("voice-action-test-password"),
        role_type="counsellor",
    )
    other_counsellor = db.create_user(
        "voice.other-counsellor@example.test",
        "Other Counsellor",
        hash_password("voice-action-test-password"),
        role_type="counsellor",
    )
    conn = db.get_db()
    for user in (student, other, counsellor, other_counsellor):
        conn.execute("UPDATE users SET status='approved' WHERE id=?", (user["id"],))
    conn.execute("UPDATE users SET user_category='adult' WHERE id=?", (student["id"],))
    conn.commit()
    conn.close()
    assign_student_to_counsellor(counsellor["id"], student["id"])

    now = datetime.now(timezone.utc)
    appointment = create_appointment(
        student["id"], counsellor["id"], student["id"], "Wellbeing meeting",
        (now + timedelta(days=2)).isoformat(), (now + timedelta(days=2, minutes=30)).isoformat(),
        timezone_name="Africa/Nairobi", mode="in_person", location="Private location",
    )
    other_appointment = create_appointment(
        other["id"], other_counsellor["id"], other["id"], "Other private meeting",
        (now + timedelta(days=3)).isoformat(), (now + timedelta(days=3, minutes=30)).isoformat(),
        timezone_name="Africa/Nairobi", mode="in_person", location="Other private location",
    )
    session_id = _active_session(db, student["id"])
    other_session = _active_session(db, other["id"])

    with _client() as client:
        headers = _login(client, student["email"])
        unauthenticated = client.post(
            f"/api/v1/voice/sessions/{session_id}/actions",
            json={"action": "get_my_upcoming_appointments"},
        )
        assert unauthenticated.status_code == 401
        foreign = client.post(
            f"/api/v1/voice/sessions/{other_session}/actions",
            headers=headers,
            json={"action": "get_my_upcoming_appointments"},
        )
        assert foreign.status_code == 404
        arbitrary = client.post(
            f"/api/v1/voice/sessions/{session_id}/actions",
            headers=headers,
            json={"action": "call_arbitrary_api", "payload": {"url": "https://example.test"}},
        )
        assert arbitrary.status_code == 422

        appointments = client.post(
            f"/api/v1/voice/sessions/{session_id}/actions",
            headers=headers,
            json={"action": "get_my_upcoming_appointments"},
        )
        assert appointments.status_code == 200
        assert appointments.json()["result"] == "SUCCESS"
        assert [row["id"] for row in appointments.json()["appointments"]] == [appointment["id"]]
        assert appointments.json()["appointments"][0]["provider_name"] == counsellor["name"]
        assert other_appointment["id"] not in json.dumps(appointments.json())
        assert "Private location" not in json.dumps(appointments.json())

        support = client.post(
            f"/api/v1/voice/sessions/{session_id}/actions",
            headers=headers,
            json={"action": "get_my_current_support"},
        )
        assert support.json()["support"] == {
            "state": "connected",
            "provider_name": counsellor["name"],
            "relationship": "assigned_counsellor",
        }
        prepare = client.post(
            f"/api/v1/voice/sessions/{session_id}/actions",
            headers=headers,
            json={"action": "prepare_for_appointment", "payload": {"appointment_id": appointment["id"]}},
        )
        assert prepare.json()["result"] == "SUCCESS"
        assert prepare.json()["saved"] is False
        not_owned = client.post(
            f"/api/v1/voice/sessions/{session_id}/actions",
            headers=headers,
            json={"action": "prepare_for_appointment", "payload": {"appointment_id": other_appointment["id"]}},
        )
        assert not_owned.json()["result"] == "NOT_FOUND"
        arbitrary_navigation = client.post(
            f"/api/v1/voice/sessions/{session_id}/actions",
            headers=headers,
            json={"action": "navigate", "payload": {"target": "../../admin"}},
        )
        assert arbitrary_navigation.json()["result"] == "NOT_ALLOWED"
        navigation = client.post(
            f"/api/v1/voice/sessions/{session_id}/actions",
            headers=headers,
            json={"action": "navigate", "payload": {"target": "appointments"}},
        )
        assert navigation.json()["route_id"] == "appointments"

        proposed_support = client.post(
            f"/api/v1/voice/sessions/{session_id}/actions",
            headers=headers,
            json={"action": "propose_human_support"},
        )
        assert proposed_support.json()["result"] == "CONFIRMATION_REQUIRED"
        assert proposed_support.json()["sensitivity"] == "CONFIRM_REQUIRED"
        conn = db.get_db()
        before = conn.execute("SELECT COUNT(*) FROM communications WHERE sender_id=?", (student["id"],)).fetchone()[0]
        conn.close()
        assert before == 0
        confirmation = client.post(
            f"/api/v1/voice/sessions/{session_id}/actions/{proposed_support.json()['pending_action_id']}/confirm",
            headers=headers,
            json={"confirmed": True},
        )
        assert confirmation.json()["result"] == "SUCCESS"
        conn = db.get_db()
        after = conn.execute("SELECT COUNT(*) FROM communications WHERE sender_id=?", (student["id"],)).fetchone()[0]
        message = conn.execute("SELECT message FROM communications WHERE sender_id=?", (student["id"],)).fetchone()[0]
        conn.close()
        assert after == 1
        assert "voice transcript" not in message.lower()

        pending_note = client.post(
            f"/api/v1/voice/sessions/{session_id}/actions",
            headers=headers,
            json={"action": "propose_private_summary", "payload": {"summary": "Discard after expiry"}},
        )
        conn = db.get_db()
        conn.execute("UPDATE voice_support_sessions SET active_expires_at='2000-01-01T00:00:00+00:00' WHERE id=?", (session_id,))
        conn.commit()
        conn.close()
        expired = client.post(
            f"/api/v1/voice/sessions/{session_id}/actions/{pending_note.json()['pending_action_id']}/confirm",
            headers=headers,
            json={"confirmed": True},
        )
        assert expired.status_code == 410
        conn = db.get_db()
        final = conn.execute("SELECT status,pending_action_id,pending_action_payload_encrypted,summary_encrypted FROM voice_support_sessions WHERE id=?", (session_id,)).fetchone()
        conn.close()
        assert final["status"] == "ending"
        assert final["pending_action_id"] is None
        assert final["pending_action_payload_encrypted"] is None
        assert final["summary_encrypted"] is None


def test_workplace_voice_actions_reuse_checkin_support_and_scoped_sharing(db, monkeypatch):
    from backend.routes import workplace
    from backend.services.workplace_analytics import get_workplace_insights

    _configure_voice(monkeypatch)
    monkeypatch.setattr(workplace, "send_html_email", lambda *args, **kwargs: (True, ""))
    company, admin = _company(db)
    employee = db.create_user(
        "worker@acme.test",
        "Workplace Employee",
        hash_password("workplace-test-password"),
        role_type="workplace_employee",
        institution_id=company["id"],
    )
    now = datetime.now(timezone.utc)
    conn = db.get_db()
    conn.execute(
        "UPDATE users SET status='approved',user_category='workplace_employee',"
        "workplace_terms_version='workplace-participant-v1',terms_accepted_at=? WHERE id=?",
        (now.isoformat(), employee["id"]),
    )
    conn.execute(
        "INSERT INTO workplace_memberships (id,company_id,user_id,status,notice_version,consented_at,created_at,updated_at) VALUES (?,?,?,'active','v1',?,?,?)",
        ("voice-action-membership", company["id"], employee["id"], now.isoformat(), now.isoformat(), now.isoformat()),
    )
    conn.commit()
    conn.close()
    provider = _provider(db, company, admin)
    session_id = _active_session(db, employee["id"])
    owner_session = _active_session(db, admin["id"])

    with _client() as client:
        employee_headers = _login(client, employee["email"], "workplace-test-password")
        admin_headers = _login(client, admin["email"])
        current_support = client.post(
            f"/api/v1/voice/sessions/{session_id}/actions",
            headers=employee_headers,
            json={"action": "get_my_current_support"},
        )
        assert current_support.json()["support"]["state"] == "none"
        upcoming = client.post(
            f"/api/v1/voice/sessions/{session_id}/actions",
            headers=employee_headers,
            json={"action": "get_my_upcoming_appointments"},
        )
        assert upcoming.json()["appointments"] == []
        available = client.post(
            f"/api/v1/voice/sessions/{session_id}/actions",
            headers=employee_headers,
            json={"action": "get_my_available_providers"},
        )
        assert available.json()["result"] == "SUCCESS"
        assert [item["id"] for item in available.json()["providers"]] == [provider["id"]]
        bad_checkin = client.post(
            f"/api/v1/voice/sessions/{session_id}/actions",
            headers=employee_headers,
            json={"action": "propose_workplace_checkin", "payload": {"mood": 3, "stress": 2, "support_access": 4, "diagnosis": "anxiety"}},
        )
        assert bad_checkin.json()["result"] == "FAILED"
        conn = db.get_db()
        assert conn.execute("SELECT COUNT(*) FROM workplace_checkins WHERE user_id=?", (employee["id"],)).fetchone()[0] == 0
        conn.close()

        checkin = client.post(
            f"/api/v1/voice/sessions/{session_id}/actions",
            headers=employee_headers,
            json={"action": "propose_workplace_checkin", "payload": {"mood": 3, "stress": 2, "support_access": 4}},
        )
        assert checkin.json()["result"] == "CONFIRMATION_REQUIRED"
        conn = db.get_db()
        assert conn.execute("SELECT COUNT(*) FROM workplace_checkins WHERE user_id=?", (employee["id"],)).fetchone()[0] == 0
        conn.close()
        saved_checkin = client.post(
            f"/api/v1/voice/sessions/{session_id}/actions/{checkin.json()['pending_action_id']}/confirm",
            headers=employee_headers,
            json={"confirmed": True},
        )
        assert saved_checkin.json()["result"] == "SUCCESS"
        conn = db.get_db()
        checkin_row = conn.execute("SELECT answers_json,origin FROM workplace_checkins WHERE user_id=?", (employee["id"],)).fetchone()
        assert checkin_row["origin"] == "voice"
        assert json.loads(decrypt_pii(checkin_row["answers_json"])) == {"mood": 3, "stress": 2, "support_access": 4}
        conn.close()

        no_consent = client.post(
            f"/api/v1/voice/sessions/{session_id}/actions",
            headers=employee_headers,
            json={"action": "propose_human_support", "payload": {"provider_id": provider["id"], "share_latest_checkin": False}},
        )
        assert no_consent.json()["result"] == "CONSENT_REQUIRED"
        request = client.post(
            f"/api/v1/voice/sessions/{session_id}/actions",
            headers=employee_headers,
            json={"action": "propose_human_support", "payload": {"provider_id": provider["id"], "share_latest_checkin": True}},
        )
        assert request.json()["result"] == "CONFIRMATION_REQUIRED"
        assert request.json()["sensitivity"] == "SHARE_REQUIRED"
        case_id = None
        conn = db.get_db()
        assert conn.execute("SELECT COUNT(*) FROM workplace_support_cases WHERE user_id=?", (employee["id"],)).fetchone()[0] == 0
        conn.close()
        created = client.post(
            f"/api/v1/voice/sessions/{session_id}/actions/{request.json()['pending_action_id']}/confirm",
            headers=employee_headers,
            json={"confirmed": True},
        )
        assert created.json()["result"] == "SUCCESS"
        case_id = created.json()["case_id"]
        duplicate = client.post(
            f"/api/v1/voice/sessions/{session_id}/actions",
            headers=employee_headers,
            json={"action": "propose_human_support", "payload": {"provider_id": provider["id"], "share_latest_checkin": True}},
        )
        assert duplicate.json()["already_active"] is True
        conn = db.get_db()
        assert conn.execute("SELECT COUNT(*) FROM workplace_support_cases WHERE user_id=?", (employee["id"],)).fetchone()[0] == 1
        conn.close()

        note = "I want to discuss feeling overloaded at work."
        proposal = client.post(
            f"/api/v1/voice/sessions/{session_id}/actions",
            headers=employee_headers,
            json={"action": "propose_private_summary", "payload": {"summary": note}},
        )
        conn = db.get_db()
        session_before = conn.execute("SELECT summary_encrypted,pending_action_payload_encrypted FROM voice_support_sessions WHERE id=?", (session_id,)).fetchone()
        assert session_before["summary_encrypted"] is None
        assert note not in session_before["pending_action_payload_encrypted"]
        conn.close()
        note_saved = client.post(
            f"/api/v1/voice/sessions/{session_id}/actions/{proposal.json()['pending_action_id']}/confirm",
            headers=employee_headers,
            json={"confirmed": True},
        )
        assert note_saved.json()["result"] == "SUCCESS"
        conn = db.get_db()
        stored_note = conn.execute("SELECT summary_encrypted,summary_saved_at FROM voice_support_sessions WHERE id=?", (session_id,)).fetchone()
        assert note not in stored_note["summary_encrypted"]
        assert stored_note["summary_saved_at"]
        conn.close()

        share = client.post(
            f"/api/v1/voice/sessions/{session_id}/actions",
            headers=employee_headers,
            json={"action": "propose_summary_share", "payload": {"case_id": case_id}},
        )
        assert share.json()["result"] == "CONFIRMATION_REQUIRED"
        assert share.json()["sensitivity"] == "SHARE_REQUIRED"
        conn = db.get_db()
        assert conn.execute("SELECT COUNT(*) FROM workplace_messages WHERE case_id=?", (case_id,)).fetchone()[0] == 0
        conn.close()
        shared = client.post(
            f"/api/v1/voice/sessions/{session_id}/actions/{share.json()['pending_action_id']}/confirm",
            headers=employee_headers,
            json={"confirmed": True},
        )
        assert shared.json()["result"] == "SUCCESS"
        conn = db.get_db()
        message = conn.execute("SELECT body_encrypted FROM workplace_messages WHERE case_id=?", (case_id,)).fetchone()
        assert decrypt_pii(message["body_encrypted"]) == note
        conn.close()

        assert client.get(f"/api/v1/voice/sessions/{session_id}/state", headers=admin_headers).status_code == 404
        employer_audit = client.get("/api/v1/workplace/admin/audit", headers=admin_headers)
        assert employer_audit.status_code == 200
        assert "VOICE_SUMMARY_SHARED" not in json.dumps(employer_audit.json())
        assert "voice-action-membership" not in json.dumps(employer_audit.json())

    # Voice-origin check-ins never enter employer aggregate analytics, even
    # when nine web check-ins are otherwise present in the same month.
    conn = db.get_db()
    previous_month = (now.replace(day=1) - timedelta(days=1))
    created_at = previous_month.replace(day=12).isoformat()
    conn.execute("UPDATE workplace_checkins SET created_at=? WHERE user_id=?", (created_at, employee["id"]))
    conn.commit()
    password_hash = hash_password("voice-action-test-password")
    for index in range(9):
        worker = db.create_user(
            f"aggregate-{index}@acme.test", f"Aggregate Worker {index}", password_hash,
            role_type="workplace_employee", institution_id=company["id"],
        )
        conn.execute("UPDATE users SET status='approved',user_category='workplace_employee' WHERE id=?", (worker["id"],))
        conn.execute(
            "INSERT INTO workplace_memberships (id,company_id,user_id,status,notice_version,consented_at,created_at,updated_at) VALUES (?,?,?,'active','v1',?,?,?)",
            (str(uuid.uuid4()), company["id"], worker["id"], created_at, created_at, created_at),
        )
        conn.execute(
            "INSERT INTO workplace_checkins (id,company_id,user_id,answers_json,created_at,origin) VALUES (?,?,?,?,?,'web')",
            (str(uuid.uuid4()), company["id"], worker["id"], encrypt_pii('{\"mood\":4,\"stress\":4,\"support_access\":4}'), created_at),
        )
        conn.commit()
    result = get_workplace_insights(conn, company["id"], now=now)
    conn.close()
    assert result["state"] == "INSUFFICIENT_DATA"

    with _client() as client:
        owner_headers = _login(client, admin["email"])
        report = client.get("/api/v1/workplace/admin/report", headers=owner_headers)
        assert report.status_code == 200
        assert report.json()["suppressed"] is True
        assert "voice" not in json.dumps(report.json()).lower()
