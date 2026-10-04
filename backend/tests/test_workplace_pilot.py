import os
import re

os.environ.setdefault("JWT_SECRET", "workplace-pilot-test-secret")

from fastapi.testclient import TestClient

from backend.auth import hash_password
from backend.services.crypto import encrypt_pii


def _client():
    from backend.main import app

    return TestClient(app)


def _login(client, email, password="workplace-test-password"):
    response = client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _company(db, admin_email="owner@acme.test"):
    company = db.create_institution("Acme Ltd", "company")
    admin = db.create_user(
        admin_email,
        "Company Admin",
        hash_password("workplace-test-password"),
        role_type="student",
    )
    conn = db.get_db()
    conn.execute(
        "UPDATE users SET status='approved', user_category='company_staff', role_type='company_admin', institution_id=?, workplace_admin_role='owner', workplace_invitation_status='accepted', workplace_terms_version='workplace-admin-v1',terms_accepted_at=datetime('now') WHERE id=?",
        (company["id"], admin["id"]),
    )
    conn.execute("UPDATE institutions SET status='ACTIVE' WHERE id=?", (company["id"],))
    conn.execute(
        "INSERT INTO workplace_settings (company_id, work_email_domains_json, legal_review_complete, created_at, updated_at) VALUES (?,?,1,datetime('now'),datetime('now'))",
        (company["id"], '["acme.test"]'),
    )
    conn.commit()
    conn.close()
    return company, db.get_user_by_id(admin["id"])


def _configure_enrollment_readiness(db, company, admin):
    """Give a fixture a reviewed policy and an approved independent provider."""
    provider = db.create_user(
        "care-provider@care.test",
        "Care Provider",
        hash_password("workplace-test-password"),
        role_type="workplace_provider",
    )
    now = "2026-09-27T10:00:00+00:00"
    conn = db.get_db()
    conn.execute(
        "UPDATE workplace_settings SET policy_status='approved' WHERE company_id=?",
        (company["id"],),
    )
    conn.execute(
        "UPDATE users SET status='approved',user_category='workplace_provider' WHERE id=?",
        (provider["id"],),
    )
    conn.execute(
        "INSERT INTO workplace_provider_credentials (provider_id,title_encrypted,qualification_encrypted,registration_encrypted,verification_reference_encrypted,status,reviewed_by,reviewed_at) VALUES (?,?,?,?,?,'verified',?,?)",
        (
            provider["id"],
            encrypt_pii("Counsellor"),
            encrypt_pii("Qualification"),
            encrypt_pii("REG-1"),
            encrypt_pii("review ref"),
            admin["id"],
            now,
        ),
    )
    conn.execute(
        "INSERT INTO workplace_providers (company_id,provider_id,status,created_at) VALUES (?,?,'active',?)",
        (company["id"], provider["id"], now),
    )
    conn.commit()
    conn.close()
    return provider


def _global_admin(db):
    admin = db.create_user(
        "global-admin@mindguard.test",
        "Global Admin",
        hash_password("workplace-test-password"),
        role_type="admin",
    )
    conn = db.get_db()
    conn.execute("UPDATE users SET status='approved' WHERE id=?", (admin["id"],))
    conn.commit()
    conn.close()
    return admin


def test_company_demo_conversion_is_atomic_invites_first_admin_and_is_idempotent(db, monkeypatch):
    demo = db.create_demo_request(
        "Company Owner", "owner@acme.co.ke", "Acme Ltd", "company",
        employee_population_range="50–199", country="KE",
    )
    db.update_demo_request(demo["id"], status="qualified")
    admin = _global_admin(db)
    from backend.services import email_sender
    monkeypatch.setattr(email_sender, "_deliver", lambda *args: (True, "", "test-message-id"))
    with _client() as client:
        headers = _login(client, admin["email"])
        payload = {
            "company_name": "Acme Workplace",
            "admin_name": "Company Owner",
            "admin_email": "owner@acme.co.ke",
            "work_email_domains": ["acme.co.ke"],
            "privacy_contact_email": "privacy@acme.co.ke",
            "population_range": "50–199",
            "retention_days": 365,
        }
        response = client.post(f"/api/v1/workplace/admin/demo-requests/{demo['id']}/convert", json=payload, headers=headers)
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["company"]["name"] == "Acme Workplace"
        assert body["administrator"]["status"] == "pending"
        assert "token=" not in response.text
        queued = db.get_db().execute("SELECT * FROM email_outbox WHERE related_type='workplace_admin_invitation'").fetchone()
        assert queued is not None and "token=" in queued["body_html"]
        assert queued["metadata_json"] is not None and demo["id"] in queued["metadata_json"]
        repeat = client.post(f"/api/v1/workplace/admin/demo-requests/{demo['id']}/convert", json=payload, headers=headers)
        assert repeat.status_code == 409

    conn = db.get_db()
    assert conn.execute("SELECT COUNT(*) FROM institutions WHERE type='company'").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM users WHERE role_type='company_admin'").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM email_outbox WHERE related_type='workplace_admin_invitation'").fetchone()[0] == 1
    events = {row[0] for row in conn.execute("SELECT event_type FROM workplace_audit_events").fetchall()}
    assert "WORKPLACE_ADMIN_INVITATION_CREATED" in events
    conn.close()


def test_company_demo_conversion_rejects_unqualified_and_institution_route(db):
    from backend.main import app

    company_demo = db.create_demo_request("Lead", "lead@acme.co.ke", "Acme", "company")
    education_demo = db.create_demo_request("School", "lead@school.test", "School", "k12")
    admin = _global_admin(db)
    payload = {"company_name":"Acme", "admin_name":"Lead", "admin_email":"lead@acme.co.ke", "work_email_domains":["acme.co.ke"], "privacy_contact_email":"privacy@acme.co.ke"}
    with _client() as client:
        headers = _login(client, admin["email"])
        rejected = client.post(f"/api/v1/workplace/admin/demo-requests/{company_demo['id']}/convert", json=payload, headers=headers)
        assert rejected.status_code == 409
        wrong_route = client.post(f"/api/v1/admin/demo-requests/{company_demo['id']}/convert", headers=headers)
        assert wrong_route.status_code == 400
        wrong_type = client.post(f"/api/v1/workplace/admin/demo-requests/{education_demo['id']}/convert", json=payload, headers=headers)
        assert wrong_type.status_code == 400
    conn = db.get_db()
    assert conn.execute("SELECT COUNT(*) FROM institutions WHERE type='company'").fetchone()[0] == 0
    conn.close()


def test_admin_demo_workplace_skips_live_setup_gates_but_cannot_become_live(db, monkeypatch):
    from backend.routes import workplace

    sent_emails = []
    monkeypatch.setattr(
        workplace,
        "send_html_email",
        lambda email, subject, body, **kwargs: (sent_emails.append((email, body)) or True, ""),
    )
    admin = _global_admin(db)
    with _client() as client:
        admin_headers = _login(client, admin["email"])
        created = client.post(
            "/api/v1/workplace/admin/demo-workplaces",
            headers=admin_headers,
            json={"name": "Example Demo", "admin_name": "Test Admin", "admin_email": "demo-admin@gmail.com"},
        )
        assert created.status_code == 201, created.text
        demo = created.json()
        assert demo["demo_mode"] is True and demo["invitation_sent"] is True
        assert "token=" not in created.text
        assert len(sent_emails) == 1 and sent_emails[0][0] == "demo-admin@gmail.com"

        invite_token = re.search(r"token=([^&\"]+)", sent_emails[0][1]).group(1)
        accepted = client.post(
            "/api/auth/invite/accept",
            json={"token": invite_token, "password": "demo-workplace-password"},
        )
        assert accepted.status_code == 200, accepted.text
        company_headers = {"Authorization": f"Bearer {accepted.json()['access_token']}"}
        assert client.post("/api/auth/terms", headers=company_headers).status_code == 200
        non_admin_create = client.post(
            "/api/v1/workplace/admin/demo-workplaces",
            headers=company_headers,
            json={"name": "Unauthorized Demo", "admin_name": "Worker", "admin_email": "another-demo@gmail.com"},
        )
        assert non_admin_create.status_code == 403

        setup = client.get("/api/v1/workplace/admin/setup", headers=company_headers)
        assert setup.status_code == 200 and setup.json()["demo_mode"] is True
        assert setup.json()["approved_domains"] == []
        link = client.post("/api/v1/workplace/admin/enrollment-link", headers=company_headers)
        assert link.status_code == 200, link.text
        resolved = client.get(f"/api/v1/workplace/enrollment/resolve?token={link.json()['token']}")
        assert resolved.status_code == 200 and resolved.json()["demo_mode"] is True

        joined = client.post(
            "/api/v1/workplace/enrollment/start",
            json={
                "token": link.json()["token"],
                "name": "Test Worker",
                "email": "test-worker@yahoo.com",
                "password": "demo-worker-password",
                "accepted_notice": True,
                "accepted_workplace_terms": True,
            },
        )
        assert joined.status_code == 202, joined.text
        assert len(sent_emails) == 2 and sent_emails[1][0] == "test-worker@yahoo.com"
        code = re.search(r"<strong>(\d{6})</strong>", sent_emails[1][1]).group(1)
        verified = client.post(
            "/api/v1/workplace/enrollment/verify",
            json={"challenge_id": joined.json()["challenge_id"], "code": code},
        )
        assert verified.status_code == 200, verified.text
        worker_headers = {"Authorization": f"Bearer {verified.json()['access_token']}"}
        context = client.get("/api/v1/workplace/member/context", headers=worker_headers)
        assert context.status_code == 200
        assert context.json() == {"company_name": "Example Demo", "demo_mode": True}

        company_id = demo["id"]
        assert client.post(
            f"/api/v1/workplace/admin/companies/{company_id}/legal-review",
            headers=admin_headers,
            json={"reviewed": True, "reference": "test review reference"},
        ).status_code == 409
        assert client.post(
            "/api/v1/workplace/admin/domains",
            headers=company_headers,
            json={"domain": "example.com"},
        ).status_code == 409
        assert client.put(
            "/api/v1/workplace/admin/policy",
            headers=company_headers,
            json={
                "privacy_contact_email": "privacy@example.com",
                "employee_population_range": "1-50",
                "retention_days": 365,
                "privacy_notice_version": "workplace-v1",
                "confirm_aggregate_only": True,
            },
        ).status_code == 409
        assert client.put(
            f"/api/v1/workplace/admin/companies/{company_id}/commercial",
            headers=admin_headers,
            json={"status": "ACTIVE", "reason": "Attempt live conversion"},
        ).status_code == 409

    conn = db.get_db()
    settings = conn.execute(
        "SELECT demo_mode,work_email_domains_json,legal_review_complete FROM workplace_settings WHERE company_id=?",
        (company_id,),
    ).fetchone()
    credential = conn.execute(
        "SELECT demo_only,registration_encrypted FROM workplace_provider_credentials WHERE provider_id IN (SELECT provider_id FROM workplace_providers WHERE company_id=?)",
        (company_id,),
    ).fetchone()
    assert settings["demo_mode"] == 1 and settings["work_email_domains_json"] == "[]"
    assert settings["legal_review_complete"] == 0
    assert credential["demo_only"] == 1
    assert conn.execute("SELECT COUNT(*) FROM workplace_memberships WHERE company_id=?", (company_id,)).fetchone()[0] == 1
    conn.close()


def test_company_admin_is_not_allowed_legacy_school_or_social_routes(db):
    _, admin = _company(db)
    with _client() as client:
        headers = _login(client, admin["email"])
        report = client.get("/api/v1/workplace/admin/report", headers=headers)
        assert report.status_code == 200 and report.json()["suppressed"] is True
        assert (
            client.get("/api/self/social-accounts", headers=headers).status_code == 403
        )
        assert client.get("/api/institution/setup", headers=headers).status_code == 403
        assert client.get("/api/institution/staff/profile", headers=headers).status_code == 200


def test_workplace_checkins_are_encrypted_and_not_returned_to_company_admin(db):
    company, admin = _company(db)
    employee = db.create_user(
        "person@acme.test",
        "Private Employee",
        hash_password("workplace-test-password"),
        role_type="workplace_employee",
        institution_id=company["id"],
    )
    conn = db.get_db()
    now = "2026-09-27T10:00:00+00:00"
    conn.execute(
        "UPDATE users SET status='approved', user_category='workplace_employee',workplace_terms_version='workplace-participant-v1',terms_accepted_at=datetime('now') WHERE id=?",
        (employee["id"],),
    )
    conn.execute(
        "INSERT INTO workplace_memberships (id,company_id,user_id,status,notice_version,consented_at,created_at,updated_at) VALUES ('m-1',?,?,'active','v1',?,?,?)",
        (company["id"], employee["id"], now, now, now),
    )
    conn.commit()
    conn.close()
    with _client() as client:
        headers = _login(client, employee["email"])
        response = client.post(
            "/api/v1/workplace/checkins",
            headers=headers,
            json={"mood": 2, "stress": 4, "support_access": 3},
        )
        assert response.status_code == 201, response.text
        conn = db.get_db()
        row = conn.execute(
            "SELECT answers_json FROM workplace_checkins WHERE user_id=?",
            (employee["id"],),
        ).fetchone()
        conn.close()
        assert row and '"stress": 4' not in row["answers_json"]
        assert (
            client.get("/api/self/social-accounts", headers=headers).status_code == 403
        )
        company_report = client.get(
            "/api/v1/workplace/admin/report", headers=_login(client, admin["email"])
        )
        assert company_report.status_code == 200
        assert "Private Employee" not in company_report.text
        assert "person@acme.test" not in company_report.text


def test_aggregate_report_suppresses_below_ten_active_respondents(db):
    company, admin = _company(db)
    now = "2026-09-27T10:00:00+00:00"
    for i in range(10):
        person = db.create_user(
            f"p{i}@acme.test",
            f"Person {i}",
            hash_password("workplace-test-password"),
            role_type="workplace_employee",
            institution_id=company["id"],
        )
        conn = db.get_db()
        conn.execute(
            "UPDATE users SET status='approved', user_category='workplace_employee',workplace_terms_version='workplace-participant-v1',terms_accepted_at=datetime('now') WHERE id=?",
            (person["id"],),
        )
        conn.execute(
            "INSERT INTO workplace_memberships (id,company_id,user_id,status,notice_version,consented_at,created_at,updated_at) VALUES (?,?,?,'active','v1',?,?,?)",
            (f"m-{i}", company["id"], person["id"], now, now, now),
        )
        if i < 9:
            conn.execute(
                "INSERT INTO workplace_checkins (id,company_id,user_id,answers_json,created_at) VALUES (?,?,?,?,?)",
                (
                    f"a-{i}",
                    company["id"],
                    person["id"],
                    encrypt_pii('{"mood": 4, "stress": 2, "support_access": 3}'),
                    "2026-08-27T10:00:00+00:00",
                ),
            )
            conn.execute(
                "INSERT INTO workplace_checkins (id,company_id,user_id,answers_json,created_at) VALUES (?,?,?,?,?)",
                (
                    f"c-{i}",
                    company["id"],
                    person["id"],
                    encrypt_pii('{"mood": 4, "stress": 2, "support_access": 3, "comment": "private raw participant text"}'),
                    now,
                ),
            )
        conn.commit()
        conn.close()
    with _client() as client:
        headers = _login(client, admin["email"])
        response = client.get("/api/v1/workplace/admin/report", headers=headers)
        assert response.status_code == 200 and response.json()["suppressed"] is True
        trends = client.get("/api/v1/workplace/admin/report/trends", headers=headers)
        assert trends.status_code == 200
        assert trends.json()["suppressed"] is True
        september = next(period for period in trends.json()["periods"] if period["period"] == "2026-09")
        august = next(period for period in trends.json()["periods"] if period["period"] == "2026-08")
        assert september["state"] == august["state"] == "INSUFFICIENT_DATA"
        assert "averages" not in september and "wellbeing_indicator" not in september
        insufficient = client.get("/api/v1/workplace/admin/insights", headers=headers).json()
        assert insufficient["state"] == "INSUFFICIENT_DATA"
        assert insufficient["overview"] is None and insufficient["recommendations"] == []
        conn = db.get_db()
        person = conn.execute(
            "SELECT user_id FROM workplace_memberships WHERE company_id=? LIMIT 1",
            (company["id"],),
        ).fetchone()
        conn.execute(
            "INSERT INTO workplace_checkins (id,company_id,user_id,answers_json,created_at) VALUES ('c-9',?,?,?,?)",
            (
                company["id"],
                person["user_id"],
                encrypt_pii('{"mood": 4, "stress": 2, "support_access": 3}'),
                now,
            ),
        )
        conn.commit()
        conn.close()
        # The tenth distinct employee now contributes after their first check-in.
        conn = db.get_db()
        # If the first selected member was one of the previous nine, the cohort is still nine;
        # add the missing respondent in a deterministic way.
        missing = conn.execute(
            "SELECT m.user_id FROM workplace_memberships m LEFT JOIN workplace_checkins c ON c.user_id=m.user_id AND c.company_id=m.company_id WHERE m.company_id=? AND c.id IS NULL LIMIT 1",
            (company["id"],),
        ).fetchone()
        conn.close()
        if missing:
            conn = db.get_db()
            conn.execute(
                "INSERT INTO workplace_checkins (id,company_id,user_id,answers_json,created_at) VALUES ('c-10',?,?,?,?)",
                (
                    company["id"],
                    missing["user_id"],
                    encrypt_pii('{"mood": 4, "stress": 2, "support_access": 3}'),
                    now,
                ),
            )
            conn.commit()
            conn.close()
        response = client.get("/api/v1/workplace/admin/report", headers=headers)
        assert response.status_code == 200 and response.json()["suppressed"] is False
        assert response.json()["cohort_size"] == "10+"
        assert "Person " not in response.text and "@acme.test" not in response.text
        insights_response = client.get("/api/v1/workplace/admin/insights", headers=headers)
        assert insights_response.status_code == 200, insights_response.text
        insights = insights_response.json()
        assert insights["state"] == "AVAILABLE" and insights["overview"]["contributors"] == "10+"
        assert insights["period"] == "2026-09"
        assert "private raw participant text" not in insights_response.text
        conn = db.get_db()
        identities = conn.execute("SELECT u.id,u.email,u.name FROM users u JOIN workplace_memberships m ON m.user_id=u.id WHERE m.company_id=?", (company["id"],)).fetchall()
        conn.close()
        assert all(identity["id"] not in insights_response.text and identity["email"] not in insights_response.text and identity["name"] not in insights_response.text for identity in identities)
        assert all(period["state"] == "INSUFFICIENT_DATA" for period in insights["trends"] if period["period"] == "2026-08")
        assert "averages" not in next(period for period in insights["trends"] if period["period"] == "2026-08")
        assert insights["comparison"]["state"] == "INSUFFICIENT_DATA" and insights["comparison"]["changes"] is None
        assert insights["recommendations"]
        assert insights["risk_distribution"]["state"] == "UNAVAILABLE"
        conn = db.get_db()
        august_missing = conn.execute("SELECT m.user_id FROM workplace_memberships m WHERE m.company_id=? AND m.status='active' AND NOT EXISTS (SELECT 1 FROM workplace_checkins c WHERE c.company_id=m.company_id AND c.user_id=m.user_id AND substr(c.created_at,1,7)='2026-08') LIMIT 1", (company["id"],)).fetchone()
        conn.execute("INSERT INTO workplace_checkins (id,company_id,user_id,answers_json,created_at) VALUES ('a-10',?,?,?,?)", (company["id"], august_missing["user_id"], encrypt_pii('{"mood": 3, "stress": 3, "support_access": 3}'), "2026-08-28T10:00:00+00:00"))
        conn.commit()
        conn.close()
        both_periods_safe = client.get("/api/v1/workplace/admin/insights", headers=headers).json()
        assert both_periods_safe["comparison"]["state"] == "AVAILABLE"
        assert set(both_periods_safe["comparison"]["changes"]) == {"mood", "stress", "support_access"}
        employer_audit = client.get("/api/v1/workplace/admin/audit", headers=headers)
        assert "WORKPLACE_INSIGHTS_VIEWED" not in employer_audit.text
        conn = db.get_db()
        assert conn.execute("SELECT COUNT(*) FROM workplace_audit_events WHERE company_id=? AND event_type='WORKPLACE_INSIGHTS_VIEWED'", (company["id"],)).fetchone()[0] > 0
        conn.close()

        other_company, other_admin = _company(db, admin_email="other-insights@other.test")
        other_headers = _login(client, other_admin["email"])
        other_insights = client.get("/api/v1/workplace/admin/insights", headers=other_headers)
        assert other_insights.status_code == 200 and other_insights.json()["state"] == "NO_DATA"
        assert "Person " not in other_insights.text and other_company["id"] not in other_insights.text
        conn = db.get_db()
        conn.execute("UPDATE workplace_commercial_accounts SET capabilities_json=? WHERE company_id=?", ('{"aggregate_analytics":false}', company["id"]))
        conn.commit()
        conn.close()
        not_entitled = client.get("/api/v1/workplace/admin/insights", headers=headers)
        assert not_entitled.status_code == 200 and not_entitled.json()["state"] == "NOT_ENTITLED"
        assert not_entitled.json()["overview"] is None and not_entitled.json()["recommendations"] == []


def test_workplace_analytics_threshold_cannot_be_configured_below_ten(monkeypatch):
    from backend.services.workplace_analytics import minimum_cohort

    monkeypatch.setenv("WORKPLACE_ANALYTICS_MIN_COHORT", "3")
    assert minimum_cohort() == 10
    monkeypatch.setenv("WORKPLACE_ANALYTICS_MIN_COHORT", "25")
    assert minimum_cohort() == 25


def test_workplace_demo_request_has_employee_population_while_legacy_student_range_remains(
    db,
):
    demo = db.create_demo_request(
        "Owner",
        "owner@acme.test",
        "Acme Ltd",
        "company",
        country="KE",
        employee_population_range="200–499",
    )
    assert demo["employee_population_range"] == "200–499"
    assert demo["student_count_range"] is None


def test_shared_link_requires_work_email_verification_before_optin_account(
    db, monkeypatch
):
    from backend.services.crypto import hash_token
    from backend.routes import workplace

    company, admin = _company(db)
    _configure_enrollment_readiness(db, company, admin)
    conn = db.get_db()
    conn.execute(
        "UPDATE workplace_settings SET work_email_domains_json='[\"acme.com\"]' WHERE company_id=?",
        (company["id"],),
    )
    conn.commit()
    conn.close()
    raw_link = "shared-workplace-enrollment-token-with-more-than-32-chars"
    conn = db.get_db()
    conn.execute(
        "INSERT INTO workplace_enrollment_links (id,company_id,token_hash,created_by,created_at) VALUES ('link-1',?,?,?,datetime('now'))",
        (company["id"], hash_token(raw_link), admin["id"]),
    )
    conn.commit()
    conn.close()
    sent = {}

    def capture(email, subject, body, **kwargs):
        sent["email"] = email
        sent["body"] = body
        return True, ""

    monkeypatch.setattr(workplace, "send_html_email", capture)
    with _client() as client:
        start = client.post(
            "/api/v1/workplace/enrollment/start",
            json={
                "token": raw_link,
                "name": "Employee One",
                "email": "one@acme.com",
                "password": "secure-workplace-password",
                "accepted_notice": True,
                "accepted_workplace_terms": True,
            },
        )
        assert start.status_code == 202, start.text
        assert sent["email"] == "one@acme.com"
        code = re.search(r"<strong>([0-9]{6})</strong>", sent["body"]).group(1)
        verify = client.post(
            "/api/v1/workplace/enrollment/verify",
            json={"challenge_id": start.json()["challenge_id"], "code": code},
        )
        assert verify.status_code == 200, verify.text
        headers = {"Authorization": f"Bearer {verify.json()['access_token']}"}
        me = client.get("/api/auth/me", headers=headers)
        assert me.status_code == 200
        assert me.json()["role_type"] == "workplace_employee"
        assert me.json()["user_category"] == "workplace_employee"
        assert client.get("/api/self/platforms", headers=headers).status_code == 403
        conn = db.get_db()
        membership = conn.execute(
            "SELECT status, notice_version FROM workplace_memberships WHERE user_id=?",
            (me.json()["id"],),
        ).fetchone()
        conn.close()
        assert membership["status"] == "active"
        assert membership["notice_version"] == "workplace-v1"


def test_provider_gets_only_the_exact_checkin_employee_shares_and_can_be_revoked(
    db, monkeypatch
):
    from backend.routes import workplace

    company, admin = _company(db)
    employee = db.create_user(
        "worker@acme.test",
        "Worker",
        hash_password("workplace-test-password"),
        role_type="workplace_employee",
        institution_id=company["id"],
    )
    provider = db.create_user(
        "provider@care.example.org",
        "Independent Provider",
        hash_password("workplace-test-password"),
        role_type="workplace_provider",
    )
    now = "2026-09-27T10:00:00+00:00"
    conn = db.get_db()
    conn.execute(
        "UPDATE users SET status='approved', user_category='workplace_employee',workplace_terms_version='workplace-participant-v1',terms_accepted_at=datetime('now') WHERE id=?",
        (employee["id"],),
    )
    conn.execute(
        "UPDATE users SET status='approved', user_category='workplace_provider' WHERE id=?",
        (provider["id"],),
    )
    conn.execute(
        "INSERT INTO workplace_memberships (id,company_id,user_id,status,notice_version,consented_at,created_at,updated_at) VALUES ('share-m',?,?,'active','v1',?,?,?)",
        (company["id"], employee["id"], now, now, now),
    )
    conn.execute(
        "INSERT INTO workplace_provider_credentials (provider_id,title_encrypted,qualification_encrypted,registration_encrypted,verification_reference_encrypted,status,reviewed_by,reviewed_at) VALUES (?,?,?,?,?,'verified',?,?)",
        (
            provider["id"],
            encrypt_pii("Counsellor"),
            encrypt_pii("Qualification"),
            encrypt_pii("REG-1"),
            encrypt_pii("review ref"),
            admin["id"],
            now,
        ),
    )
    conn.execute(
        "INSERT INTO workplace_providers (company_id,provider_id,status,created_at) VALUES (?,?,'active',?)",
        (company["id"], provider["id"], now),
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(
        workplace, "send_html_email", lambda *args, **kwargs: (True, "")
    )
    with _client() as client:
        employee_headers = _login(client, employee["email"])
        provider_headers = _login(client, provider["email"])
        first = client.post(
            "/api/v1/workplace/checkins",
            headers=employee_headers,
            json={"mood": 2, "stress": 2, "support_access": 2},
        )
        assert first.status_code == 201
        requested = client.post(
            "/api/v1/workplace/support-requests",
            headers=employee_headers,
            json={"provider_id": provider["id"], "share_latest_checkin": True},
        )
        assert requested.status_code == 201, requested.text
        client.post(
            "/api/v1/workplace/checkins",
            headers=employee_headers,
            json={"mood": 5, "stress": 5, "support_access": 5},
        )
        cases = client.get("/api/v1/workplace/provider/cases", headers=provider_headers)
        assert cases.status_code == 200
        assert len(cases.json()) == 1
        assert cases.json()[0]["shared_checkin"] == {
            "mood": 2,
            "stress": 2,
            "support_access": 2,
        }
        withdrawn = client.post(
            f"/api/v1/workplace/support-requests/{requested.json()['case_id']}/withdraw",
            headers=employee_headers,
        )
        assert withdrawn.status_code == 200
        assert (
            client.get(
                "/api/v1/workplace/provider/cases", headers=provider_headers
            ).json()
            == []
        )
        assert (
            client.get(
                "/api/v1/workplace/admin/report", headers=_login(client, admin["email"])
            ).status_code
            == 200
        )


def test_global_company_setup_keeps_legal_gate_and_separate_institution_listing(db):
    root = db.create_user(
        "root@example.org",
        "Global Admin",
        hash_password("workplace-test-password"),
        role_type="admin",
    )
    owner = db.create_user(
        "owner@acme.com",
        "Company Owner",
        hash_password("workplace-test-password"),
        role_type="student",
    )
    conn = db.get_db()
    conn.execute(
        "UPDATE users SET status='approved', user_category='adult' WHERE id=?",
        (owner["id"],),
    )
    conn.execute("UPDATE users SET status='approved' WHERE id=?", (root["id"],))
    conn.commit()
    conn.close()
    provider = db.create_user(
        "provider@care.example.org",
        "Independent Provider",
        hash_password("workplace-test-password"),
        role_type="student",
    )
    conn = db.get_db()
    conn.execute(
        "UPDATE users SET status='approved',user_category='adult' WHERE id=?",
        (provider["id"],),
    )
    conn.commit()
    conn.close()
    with _client() as client:
        root_headers = _login(client, root["email"])
        create = client.post(
            "/api/v1/workplace/admin/companies",
            headers=root_headers,
            json={
                "name": "Acme Ltd",
                "admin_email": "owner@acme.com",
                "work_email_domains": ["acme.com"],
            },
        )
        assert create.status_code == 201, create.text
        company_id = create.json()["id"]
        assert create.json()["legal_review_complete"] is False
        assert all(row["type"] != "company" for row in db.list_institutions())
        company_headers = _login(client, "owner@acme.com")
        assert client.post("/api/auth/terms", headers=company_headers).status_code == 200
        blocked = client.post(
            "/api/v1/workplace/admin/enrollment-link", headers=company_headers
        )
        assert blocked.status_code == 403
        reviewed = client.post(
            f"/api/v1/workplace/admin/companies/{company_id}/legal-review",
            headers=root_headers,
            json={"reviewed": True, "reference": "US privacy review record 2026-01"},
        )
        assert reviewed.status_code == 200
        policy = client.put(
            "/api/v1/workplace/admin/policy",
            headers=company_headers,
            json={
                "privacy_contact_email": "privacy@acme.com",
                "employee_population_range": "50-199",
                "retention_days": 365,
                "privacy_notice_version": "workplace-v1",
                "confirm_aggregate_only": True,
            },
        )
        assert policy.status_code == 200, policy.text
        credentials = client.post(
            "/api/v1/workplace/admin/provider-credentials",
            headers=root_headers,
            json={
                "provider_email": "provider@care.example.org",
                "professional_title": "Counsellor",
                "qualification": "Registered counsellor",
                "registration_number": "REG-001",
                "license_state": "California",
                "verification_reference": "State licensing board lookup, 2026-01-10",
            },
        )
        assert credentials.status_code == 201, credentials.text
        credential_conn = db.get_db()
        credential_record = credential_conn.execute(
            "SELECT license_state_encrypted FROM workplace_provider_credentials WHERE provider_id=?",
            (provider["id"],),
        ).fetchone()
        credential_conn.close()
        from backend.services.crypto import decrypt_pii
        assert decrypt_pii(credential_record["license_state_encrypted"]) == "California"
        attached = client.post(
            "/api/v1/workplace/admin/providers",
            headers=company_headers,
            json={"provider_email": "provider@care.example.org"},
        )
        assert attached.status_code == 201, attached.text
        link = client.post(
            "/api/v1/workplace/admin/enrollment-link", headers=company_headers
        )
        assert link.status_code == 200, link.text
        link_inventory = client.get(
            "/api/v1/workplace/admin/enrollment-links", headers=company_headers
        )
        assert link_inventory.status_code == 200
        assert link_inventory.json()[0]["id"] == link.json()["id"]
        assert "token" not in link_inventory.json()[0]


def test_company_audit_does_not_expose_employee_or_provider_activity(db):
    company, admin = _company(db)
    employee = db.create_user(
        "person@acme.test",
        "Private Employee",
        hash_password("workplace-test-password"),
    )
    conn = db.get_db()
    conn.execute(
        "INSERT INTO workplace_audit_events (id,company_id,actor_user_id,event_type,occurred_at) VALUES ('audit-private',?,?,?,datetime('now'))",
        (company["id"], employee["id"], "EMPLOYEE_OPTED_IN"),
    )
    conn.execute(
        "INSERT INTO workplace_audit_events (id,company_id,actor_user_id,event_type,occurred_at) VALUES ('audit-safe',?,?,?,datetime('now'))",
        (company["id"], admin["id"], "WORKPLACE_POLICY_APPROVED"),
    )
    conn.commit()
    conn.close()
    with _client() as client:
        response = client.get(
            "/api/v1/workplace/admin/audit",
            headers=_login(client, admin["email"]),
        )
    assert response.status_code == 200
    assert [row["event_type"] for row in response.json()] == [
        "WORKPLACE_POLICY_APPROVED"
    ]
    assert "actor_user_id" not in response.text
    assert employee["id"] not in response.text


def test_suspending_company_blocks_existing_employee_and_provider_access(db):
    company, admin = _company(db)
    provider = _configure_enrollment_readiness(db, company, admin)
    employee = db.create_user(
        "worker@acme.test",
        "Worker",
        hash_password("workplace-test-password"),
        role_type="workplace_employee",
        institution_id=company["id"],
    )
    root = db.create_user(
        "root@example.org",
        "Global Admin",
        hash_password("workplace-test-password"),
        role_type="admin",
    )
    now = "2026-09-27T10:00:00+00:00"
    conn = db.get_db()
    conn.execute(
        "UPDATE users SET status='approved',user_category='workplace_employee' WHERE id=?",
        (employee["id"],),
    )
    conn.execute("UPDATE users SET status='approved' WHERE id=?", (root["id"],))
    conn.execute(
        "INSERT INTO workplace_memberships (id,company_id,user_id,status,notice_version,consented_at,created_at,updated_at) VALUES ('suspend-m',?,?,'active','v1',?,?,?)",
        (company["id"], employee["id"], now, now, now),
    )
    conn.execute(
        "INSERT INTO workplace_checkins (id,company_id,user_id,answers_json,created_at) VALUES ('suspend-c',?,?,?,?)",
        (company["id"], employee["id"], encrypt_pii('{"mood":3}'), now),
    )
    conn.execute(
        "INSERT INTO workplace_support_cases (id,company_id,user_id,provider_id,status,share_consent_at,shared_checkin_id,created_at,updated_at) VALUES ('suspend-case',?,?,?,'open',?,'suspend-c',?,?)",
        (company["id"], employee["id"], provider["id"], now, now, now),
    )
    conn.commit()
    conn.close()

    with _client() as client:
        provider_headers = _login(client, provider["email"])
        employee_headers = _login(client, employee["email"])
        root_headers = _login(client, root["email"])
        before = client.get(
            "/api/v1/workplace/provider/cases", headers=provider_headers
        )
        assert before.status_code == 200 and len(before.json()) == 1
        suspended = client.post(
            f"/api/v1/workplace/admin/companies/{company['id']}/lifecycle",
            headers=root_headers,
            json={"action": "suspend", "reason": "Testing tenant suspension"},
        )
        assert suspended.status_code == 200
        assert client.get(
            "/api/v1/workplace/checkins", headers=employee_headers
        ).status_code == 403
        after = client.get(
            "/api/v1/workplace/provider/cases", headers=provider_headers
        )
        assert after.status_code == 200 and after.json() == []


def test_workplace_retention_purges_old_closed_case_data_but_keeps_active_cases(db):
    from datetime import datetime, timedelta, timezone
    from backend.routes.workplace import purge_expired_workplace_records

    company, admin = _company(db)
    provider = _configure_enrollment_readiness(db, company, admin)
    employee = db.create_user(
        "worker@acme.test",
        "Worker",
        hash_password("workplace-test-password"),
        role_type="workplace_employee",
        institution_id=company["id"],
    )
    old = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    now = datetime.now(timezone.utc).isoformat()
    conn = db.get_db()
    conn.execute(
        "UPDATE workplace_settings SET retention_days=30 WHERE company_id=?",
        (company["id"],),
    )
    conn.execute(
        "INSERT INTO workplace_checkins (id,company_id,user_id,answers_json,created_at) VALUES ('old-checkin',?,?,?,?)",
        (company["id"], employee["id"], encrypt_pii('{"mood":2}'), old),
    )
    conn.execute(
        "INSERT INTO workplace_checkins (id,company_id,user_id,answers_json,created_at) VALUES ('active-checkin',?,?,?,?)",
        (company["id"], employee["id"], encrypt_pii('{"mood":3}'), old),
    )
    conn.execute(
        "INSERT INTO workplace_support_cases (id,company_id,user_id,provider_id,status,share_consent_at,shared_checkin_id,created_at,updated_at) VALUES ('closed-old',?,?,?,'closed',?,'old-checkin',?,?)",
        (company["id"], employee["id"], provider["id"], old, old, old),
    )
    conn.execute(
        "INSERT INTO workplace_support_cases (id,company_id,user_id,provider_id,status,share_consent_at,shared_checkin_id,created_at,updated_at) VALUES ('active-retained',?,?,?,'open',?,'active-checkin',?,?)",
        (company["id"], employee["id"], provider["id"], old, old, now),
    )
    conn.execute(
        "INSERT INTO workplace_case_notes (id,case_id,provider_id,private_note_encrypted,created_at) VALUES ('old-note','closed-old',?,?,?)",
        (provider["id"], encrypt_pii("private note"), old),
    )
    conn.commit()
    conn.close()

    assert purge_expired_workplace_records() == {"cases": 1, "checkins": 1}
    conn = db.get_db()
    old_case = conn.execute(
        "SELECT 1 FROM workplace_support_cases WHERE id='closed-old'"
    ).fetchone()
    old_note = conn.execute(
        "SELECT 1 FROM workplace_case_notes WHERE id='old-note'"
    ).fetchone()
    retained_case = conn.execute(
        "SELECT 1 FROM workplace_support_cases WHERE id='active-retained'"
    ).fetchone()
    retained_checkin = conn.execute(
        "SELECT 1 FROM workplace_checkins WHERE id='active-checkin'"
    ).fetchone()
    conn.close()
    assert old_case is None and old_note is None
    assert retained_case is not None and retained_checkin is not None


def test_provider_status_and_credential_are_checked_on_all_sensitive_routes(db):
    company, admin = _company(db)
    provider = _configure_enrollment_readiness(db, company, admin)
    employee = db.create_user("guarded@acme.test", "Guarded Worker", hash_password("workplace-test-password"), role_type="workplace_employee", institution_id=company["id"])
    now = "2026-10-01T10:00:00+00:00"
    conn = db.get_db()
    conn.execute("UPDATE users SET status='approved',user_category='workplace_employee',workplace_terms_version='workplace-participant-v1',terms_accepted_at=? WHERE id=?", (now,employee["id"]))
    conn.execute("INSERT INTO workplace_memberships (id,company_id,user_id,status,notice_version,consented_at,created_at,updated_at) VALUES ('guard-m',?,?,'active','v1',?,?,?)", (company["id"],employee["id"],now,now,now))
    conn.execute("INSERT INTO workplace_checkins (id,company_id,user_id,answers_json,created_at) VALUES ('guard-c',?,?,?,?)", (company["id"],employee["id"],encrypt_pii('{"mood":3}'),now))
    conn.execute("INSERT INTO workplace_support_cases (id,company_id,user_id,provider_id,status,share_consent_at,shared_checkin_id,created_at,updated_at) VALUES ('guard-case',?,?,?,'open',?,'guard-c',?,?)", (company["id"],employee["id"],provider["id"],now,now,now))
    conn.execute("INSERT INTO workplace_appointments (id,case_id,company_id,user_id,provider_id,starts_at,mode,status,created_at,updated_at) VALUES ('guard-appt','guard-case',?,?,?,?,'online','scheduled',?,?)", (company["id"],employee["id"],provider["id"],"2026-10-03T10:00:00+00:00",now,now))
    conn.commit(); conn.close()
    with _client() as client:
        headers = _login(client, provider["email"])
        conn = db.get_db(); conn.execute("UPDATE users SET status='suspended' WHERE id=?", (provider["id"],)); conn.commit(); conn.close()
        calls = [
            client.get("/api/v1/workplace/provider/cases", headers=headers),
            client.get("/api/v1/workplace/provider/cases/guard-case", headers=headers),
            client.post("/api/v1/workplace/provider/cases/guard-case/notes", headers=headers, json={"private_note":"note"}),
            client.get("/api/v1/workplace/provider/cases/guard-case/messages", headers=headers),
            client.post("/api/v1/workplace/provider/cases/guard-case/messages", headers=headers, json={"message":"hello"}),
            client.post("/api/v1/workplace/provider/cases/guard-case/appointments", headers=headers, json={"starts_at":"2026-10-03T10:00:00+00:00","mode":"online","location_or_link":"https://meet.example.test"}),
            client.get("/api/v1/workplace/provider/appointments", headers=headers),
            client.post("/api/v1/workplace/provider/appointments/guard-appt/status", headers=headers, json={"status":"cancelled"}),
            client.post("/api/v1/workplace/provider/cases/guard-case/close", headers=headers),
        ]
        assert [response.status_code for response in calls] == [403] * len(calls)
        conn = db.get_db(); conn.execute("UPDATE users SET status='approved' WHERE id=?", (provider["id"],)); conn.execute("UPDATE workplace_provider_credentials SET status='revoked' WHERE provider_id=?", (provider["id"],)); conn.commit(); conn.close()
        assert client.get("/api/v1/workplace/provider/cases/guard-case", headers=headers).status_code == 403


def test_workplace_terms_domains_admin_invites_and_ownership_are_enforced(db, monkeypatch):
    company, owner = _company(db)
    from backend.routes import workplace
    sent_bodies = []
    monkeypatch.setattr(workplace, "send_html_email", lambda email, subject, body, **kwargs: (sent_bodies.append(body) or True, ""))
    with _client() as client:
        owner_headers = _login(client, owner["email"])
        conn = db.get_db(); conn.execute("UPDATE users SET workplace_terms_version=NULL WHERE id=?", (owner["id"],)); conn.commit(); conn.close()
        assert client.get("/api/v1/workplace/admin/setup", headers=owner_headers).status_code == 403
        assert client.get("/api/auth/me", headers=owner_headers).json()["terms_accepted"] is False
        assert client.post("/api/auth/terms", headers=owner_headers).status_code == 200
        assert client.get("/api/v1/workplace/admin/setup", headers=owner_headers).status_code == 200

        added = client.post("/api/v1/workplace/admin/domains", headers=owner_headers, json={"domain":" @New.Acme.co.ke "})
        assert added.status_code == 201 and added.json()["domains"] == ["acme.test", "new.acme.co.ke"]
        assert client.post("/api/v1/workplace/admin/domains", headers=owner_headers, json={"domain":"NEW.ACME.CO.KE"}).status_code == 409
        assert client.request("DELETE", "/api/v1/workplace/admin/domains", headers=owner_headers, json={"domain":"acme.test"}).status_code == 200
        assert client.request("DELETE", "/api/v1/workplace/admin/domains", headers=owner_headers, json={"domain":"new.acme.co.ke"}).status_code == 409

        invited = client.post("/api/v1/workplace/admin/administrators", headers=owner_headers, json={"name":"Second Admin","email":"second@new.acme.co.ke"})
        assert invited.status_code == 201, invited.text
        second_id = invited.json()["id"]
        old_token = re.search(r"token=([^&\"]+)", sent_bodies[-1]).group(1)
        resent = client.post(f"/api/v1/workplace/admin/administrators/{second_id}/resend", headers=owner_headers)
        assert resent.status_code == 200
        fresh_token = re.search(r"token=([^&\"]+)", sent_bodies[-1]).group(1)
        assert client.post("/api/auth/invite/verify", json={"token":old_token}).status_code == 400
        assert client.delete(f"/api/v1/workplace/admin/administrators/{second_id}", headers=owner_headers).json()["invitation_revoked"] is True
        assert client.post("/api/auth/invite/verify", json={"token":fresh_token}).status_code == 400

        other_company, other_owner = _company(db, "other-owner@other.test")
        third = client.post("/api/v1/workplace/admin/administrators", headers=owner_headers, json={"name":"New Owner","email":"new-owner@new.acme.co.ke"})
        assert third.status_code == 201, third.text
        new_owner_token = re.search(r"token=([^&\"]+)", sent_bodies[-1]).group(1)
        accepted = client.post("/api/auth/invite/accept", json={"token":new_owner_token,"password":"new-owner-password"})
        assert accepted.status_code == 200, accepted.text
        new_owner_headers = {"Authorization":f"Bearer {accepted.json()['access_token']}"}
        assert client.post("/api/auth/terms", headers=new_owner_headers).status_code == 200
        transferred = client.post("/api/v1/workplace/admin/ownership/transfer", headers=owner_headers, json={"administrator_id":third.json()["id"]})
        assert transferred.status_code == 200, transferred.text
        assert client.post("/api/v1/workplace/admin/ownership/transfer", headers=owner_headers, json={"administrator_id":other_owner["id"]}).status_code == 403
        assert client.post("/api/v1/workplace/admin/ownership/transfer", headers=new_owner_headers, json={"administrator_id":other_owner["id"]}).status_code == 404
        assert client.delete(f"/api/v1/workplace/admin/administrators/{third.json()['id']}", headers=new_owner_headers).status_code == 409
        conn = db.get_db()
        owners = conn.execute("SELECT COUNT(*) FROM users WHERE institution_id=? AND role_type='company_admin' AND workplace_admin_role='owner'", (company["id"],)).fetchone()[0]
        owner_id = conn.execute("SELECT id FROM users WHERE institution_id=? AND role_type='company_admin' AND workplace_admin_role='owner'", (company["id"],)).fetchone()[0]
        conn.close()
        assert owners == 1 and owner_id == third.json()["id"]


def test_existing_verified_account_joins_once_and_withdrawal_stays_private(db, monkeypatch):
    company, admin = _company(db)
    provider = _configure_enrollment_readiness(db, company, admin)
    existing = db.create_user("existing@acme.test", "Existing Account", hash_password("workplace-test-password"))
    conn = db.get_db(); conn.execute("UPDATE users SET role_type='student',user_category='adult',status='approved',institution_id=NULL WHERE id=?", (existing["id"],)); conn.commit(); conn.close()
    from backend.services.crypto import hash_token
    from backend.routes import workplace
    token = "existing-account-workplace-link-token-long-enough"
    conn = db.get_db()
    conn.execute("INSERT INTO workplace_enrollment_links (id,company_id,token_hash,expires_at,created_by,created_at) VALUES ('existing-link',?,?,datetime('now','+90 days'),?,datetime('now'))", (company["id"],hash_token(token),admin["id"]))
    conn.commit(); conn.close()
    sent = {}
    def capture(email, subject, body, **kwargs):
        sent["body"] = body
        return True, ""
    monkeypatch.setattr(workplace, "send_html_email", capture)
    with _client() as client:
        headers = _login(client, existing["email"])
        start = client.post("/api/v1/workplace/enrollment/existing/start", headers=headers, json={"token":token,"accepted_notice":True,"accepted_workplace_terms":True})
        assert start.status_code == 202, start.text
        code = re.search(r"<strong>([0-9]{6})</strong>", sent["body"]).group(1)
        verify = client.post("/api/v1/workplace/enrollment/existing/verify", headers=headers, json={"challenge_id":start.json()["challenge_id"],"code":code})
        assert verify.status_code == 200, verify.text
        employee_headers = {"Authorization":f"Bearer {verify.json()['access_token']}"}
        assert client.get("/api/v1/workplace/me", headers=employee_headers).status_code == 200
        conn = db.get_db(); count = conn.execute("SELECT COUNT(*) FROM users WHERE lower(email)=lower(?)", (existing["email"],)).fetchone()[0]; conn.close()
        assert count == 1
        assert client.post("/api/v1/workplace/enrollment/existing/start", headers=employee_headers, json={"token":token,"accepted_notice":True,"accepted_workplace_terms":True}).status_code == 403
        assert client.post("/api/v1/workplace/withdraw", headers=employee_headers).status_code == 200
        company_headers = _login(client, admin["email"])
        audit = client.get("/api/v1/workplace/admin/audit", headers=company_headers)
        report = client.get("/api/v1/workplace/admin/report", headers=company_headers)
        assert audit.status_code == 200 and "EMPLOYEE_WITHDREW" not in audit.text and existing["id"] not in audit.text
        assert report.status_code == 200 and report.json()["suppressed"] is True
        conn = db.get_db()
        internal = conn.execute("SELECT actor_user_id FROM workplace_audit_events WHERE company_id=? AND event_type='EMPLOYEE_WITHDREW_PARTICIPATION'", (company["id"],)).fetchone()
        conn.close()
        assert internal and internal["actor_user_id"] == existing["id"]


def _workplace_case(db, company, provider, case_id="continuity-case", email="worker@acme.test"):
    from datetime import datetime, timezone

    employee = db.create_user(email, "Workplace Participant", hash_password("workplace-test-password"), role_type="workplace_employee", institution_id=company["id"])
    now = datetime.now(timezone.utc).isoformat()
    conn = db.get_db()
    conn.execute("UPDATE users SET status='approved',user_category='workplace_employee',workplace_terms_version='workplace-participant-v1',terms_accepted_at=? WHERE id=?", (now, employee["id"]))
    conn.execute("INSERT INTO workplace_memberships (id,company_id,user_id,status,notice_version,consented_at,created_at,updated_at) VALUES (?,?,?,'active','v1',?,?,?)", (f"{case_id}-membership", company["id"], employee["id"], now, now, now))
    conn.execute("INSERT INTO workplace_checkins (id,company_id,user_id,answers_json,created_at) VALUES (?,?,?, ?,?)", (f"{case_id}-checkin", company["id"], employee["id"], encrypt_pii('{"mood":3,"stress":2,"support_access":4}'), now))
    conn.execute("INSERT INTO workplace_support_cases (id,company_id,user_id,provider_id,status,share_consent_at,shared_checkin_id,created_at,updated_at,assignment_status,assigned_at) VALUES (?,?,?,?,'open',?,?,?,?,'assigned',?)", (case_id, company["id"], employee["id"], provider["id"], now, f"{case_id}-checkin", now, now, now))
    conn.commit()
    conn.close()
    return employee


def _second_provider(db, company, admin, email="replacement@care.test"):
    provider = db.create_user(email, "Replacement Provider", hash_password("workplace-test-password"), role_type="workplace_provider")
    now = "2026-10-01T10:00:00+00:00"
    conn = db.get_db()
    conn.execute("UPDATE users SET status='approved',user_category='workplace_provider' WHERE id=?", (provider["id"],))
    conn.execute("INSERT INTO workplace_provider_credentials (provider_id,title_encrypted,qualification_encrypted,registration_encrypted,verification_reference_encrypted,status,reviewed_by,reviewed_at) VALUES (?,?,?,?,?,'verified',?,?)", (provider["id"], encrypt_pii("Counsellor"), encrypt_pii("Qualification"), encrypt_pii("REG-2"), encrypt_pii("review ref"), admin["id"], now))
    conn.execute("INSERT INTO workplace_providers (company_id,provider_id,status,created_at) VALUES (?,?,'active',?)", (company["id"], provider["id"], now))
    conn.commit()
    conn.close()
    return provider


def test_provider_availability_expiry_and_reverification_are_enforced(db):
    from datetime import date, timedelta

    company, company_admin = _company(db)
    provider = _configure_enrollment_readiness(db, company, company_admin)
    employee = _workplace_case(db, company, provider)
    root = _global_admin(db)
    with _client() as client:
        provider_headers = _login(client, provider["email"])
        employee_headers = _login(client, employee["email"])
        admin_headers = _login(client, root["email"])
        unavailable = client.post("/api/v1/workplace/provider/availability", headers=provider_headers, json={"availability":"unavailable"})
        assert unavailable.status_code == 200
        assert client.get("/api/v1/workplace/provider/cases/continuity-case", headers=provider_headers).status_code == 200
        declined = client.post("/api/v1/workplace/support-requests", headers=employee_headers, json={"provider_id":provider["id"],"share_latest_checkin":True})
        assert declined.status_code == 400

        conn = db.get_db()
        conn.execute("UPDATE workplace_provider_credentials SET expires_at=? WHERE provider_id=?", ((date.today()-timedelta(days=1)).isoformat(), provider["id"]))
        conn.commit()
        conn.close()
        status = client.get("/api/v1/workplace/provider/status", headers=provider_headers)
        assert status.status_code == 200 and status.json()["credential_status"] == "expired"
        assert client.get("/api/v1/workplace/provider/cases/continuity-case", headers=provider_headers).status_code == 403
        conn = db.get_db()
        case = conn.execute("SELECT assignment_status FROM workplace_support_cases WHERE id='continuity-case'").fetchone()
        conn.close()
        assert case["assignment_status"] == "reassignment_required"

        submitted = client.post("/api/v1/workplace/provider/credentials/reverification", headers=provider_headers, json={"professional_type":"Counsellor","professional_title":"Counsellor","qualification":"Updated qualification","registration_number":"REG-NEW"})
        assert submitted.status_code == 201
        review = client.get("/api/v1/workplace/admin/provider-operations", headers=admin_headers)
        assert review.status_code == 200 and review.json()[0]["pending_reviews"]
        review_id = review.json()[0]["pending_reviews"][0]["id"]
        approved = client.post(f"/api/v1/workplace/admin/provider-credential-reviews/{review_id}", headers=admin_headers, json={"review_id":review_id,"decision":"verify","verification_reference":"Manual register check 2026","valid_from":date.today().isoformat(),"expires_at":(date.today()+timedelta(days=365)).isoformat()})
        assert approved.status_code == 200, approved.text
        assert client.get("/api/v1/workplace/provider/status", headers=provider_headers).json()["credential_valid"] is True
        assert client.get("/api/v1/workplace/provider/cases/continuity-case", headers=provider_headers).status_code == 404


def test_provider_suspension_requires_explicit_worker_consent_for_reassignment(db):
    company, company_admin = _company(db)
    previous = _configure_enrollment_readiness(db, company, company_admin)
    replacement = _second_provider(db, company, company_admin)
    employee = _workplace_case(db, company, previous)
    root = _global_admin(db)
    with _client() as client:
        previous_headers = _login(client, previous["email"])
        replacement_headers = _login(client, replacement["email"])
        employee_headers = _login(client, employee["email"])
        company_headers = _login(client, company_admin["email"])
        suspended = client.post(f"/api/v1/workplace/admin/providers/{previous['id']}/access", headers=_login(client, root["email"]), json={"action":"suspend","reason":"Temporary safety review"})
        assert suspended.status_code == 200
        assert client.get("/api/v1/workplace/provider/cases/continuity-case", headers=previous_headers).status_code == 403
        assert client.get("/api/v1/workplace/provider/cases/continuity-case", headers=replacement_headers).status_code == 404
        assert client.post("/api/v1/workplace/support-requests/continuity-case/reassign", headers=employee_headers, json={"provider_id":replacement["id"],"confirm_shared_history":False}).status_code == 400
        reassigned = client.post("/api/v1/workplace/support-requests/continuity-case/reassign", headers=employee_headers, json={"provider_id":replacement["id"],"confirm_shared_history":True})
        assert reassigned.status_code == 200, reassigned.text
        assert client.get("/api/v1/workplace/provider/cases/continuity-case", headers=replacement_headers).status_code == 200
        provider_cases = client.get("/api/v1/workplace/provider/cases", headers=replacement_headers)
        assert provider_cases.status_code == 200 and provider_cases.json()[0]["shared_checkin"] == {"mood":3,"stress":2,"support_access":4}
        audit = client.get("/api/v1/workplace/admin/audit", headers=company_headers)
        assert audit.status_code == 200 and employee["id"] not in audit.text and "continuity-case" not in audit.text
        conn = db.get_db()
        history = conn.execute("SELECT previous_provider_id,new_provider_id,worker_consent_at FROM workplace_case_assignment_history WHERE case_id='continuity-case' AND event_type='worker_consented_reassignment'").fetchone()
        retained = conn.execute("SELECT 1 FROM workplace_support_cases WHERE id='continuity-case'").fetchone()
        conn.close()
        assert history and history["previous_provider_id"] == previous["id"] and history["new_provider_id"] == replacement["id"] and history["worker_consent_at"]
        assert retained


def test_commercial_lifecycle_entitlements_and_company_scope(db):
    from datetime import date, timedelta

    company, company_admin = _company(db)
    root = _global_admin(db)
    other_company, other_admin = _company(db, admin_email="other-owner@other.test")
    with _client() as client:
        company_headers = _login(client, company_admin["email"])
        other_headers = _login(client, other_admin["email"])
        admin_headers = _login(client, root["email"])

        legacy = client.get("/api/v1/workplace/admin/commercial", headers=company_headers)
        assert legacy.status_code == 200 and legacy.json()["status"] == "PILOT"
        assert legacy.json()["plan_key"] == "legacy_pilot"
        assert "internal_notes" not in legacy.json() and "internal_reference" not in legacy.json()
        assert client.put(f"/api/v1/workplace/admin/companies/{company['id']}/commercial", headers=company_headers, json={"plan_key":"enterprise"}).status_code == 403
        assert client.get("/api/v1/workplace/admin/commercial", headers=other_headers).json()["population_band"] == "not_recorded"

        invalid = client.put(f"/api/v1/workplace/admin/companies/{company['id']}/commercial", headers=admin_headers, json={"status":"TERMINATED","reason":"Invalid direct termination"})
        assert invalid.status_code == 409
        active = client.put(f"/api/v1/workplace/admin/companies/{company['id']}/commercial", headers=admin_headers, json={
            "status":"ACTIVE", "reason":"Contract signed", "plan_key":"team", "billing_cycle":"annual",
            "contract_start_date":date.today().isoformat(), "contract_end_date":(date.today()+timedelta(days=90)).isoformat(),
            "renewal_date":(date.today()+timedelta(days=75)).isoformat(), "population_band":"51-200",
            "internal_reference":"MG-CONTRACT-42", "internal_notes":"Commercial details for MindGuard only",
            "enabled_capabilities":{"enrollment":False,"aggregate_analytics":True,"provider_services":True,"voice_support":False},
        })
        assert active.status_code == 200 and active.json()["status"] == "ACTIVE"
        assert active.json()["population_band"] == "51-200"
        assert "Commercial details for MindGuard only" in active.json()["internal_notes"]
        company_view = client.get("/api/v1/workplace/admin/commercial", headers=company_headers).json()
        other_view = client.get("/api/v1/workplace/admin/commercial", headers=other_headers).json()
        assert company_view["status"] == "ACTIVE" and company_view["population_band"] == "51-200"
        assert company_view.get("internal_notes") is None and other_view["population_band"] == "not_recorded"
        assert client.post("/api/v1/workplace/admin/enrollment-link", headers=company_headers).status_code == 403

        updated = client.put(f"/api/v1/workplace/admin/companies/{company['id']}/commercial", headers=admin_headers, json={"enabled_capabilities":{"enrollment":True,"aggregate_analytics":True,"provider_services":True,"voice_support":False}})
        assert updated.status_code == 200
        conn = db.get_db()
        history = conn.execute("SELECT previous_status,new_status,actor_user_id,reason_encrypted FROM workplace_commercial_events WHERE company_id=? AND event_type='CONTRACT_ACTIVATED'", (company["id"],)).fetchone()
        conn.close()
        assert history and history["previous_status"] == "PILOT" and history["new_status"] == "ACTIVE" and history["actor_user_id"] == root["id"] and history["reason_encrypted"]


def test_commercial_expiry_suspension_preserves_workers_and_support(db):
    from datetime import date, timedelta

    company, company_admin = _company(db)
    provider = _configure_enrollment_readiness(db, company, company_admin)
    employee = _workplace_case(db, company, provider)
    root = _global_admin(db)
    with _client() as client:
        company_headers = _login(client, company_admin["email"])
        provider_headers = _login(client, provider["email"])
        employee_headers = _login(client, employee["email"])
        admin_headers = _login(client, root["email"])
        dates = {"contract_start_date":(date.today()-timedelta(days=40)).isoformat(),"contract_end_date":(date.today()+timedelta(days=20)).isoformat(),"plan_key":"pilot","population_band":"1-50","reason":"Pilot configured"}
        active = client.put(f"/api/v1/workplace/admin/companies/{company['id']}/commercial", headers=admin_headers, json={"status":"ACTIVE",**dates})
        assert active.status_code == 200 and active.json()["status"] == "ACTIVE"
        disabled_provider_services = client.put(f"/api/v1/workplace/admin/companies/{company['id']}/commercial", headers=admin_headers, json={"enabled_capabilities":{"enrollment":True,"aggregate_analytics":True,"provider_services":False,"voice_support":False}})
        assert disabled_provider_services.status_code == 200
        assert client.post("/api/v1/workplace/support-requests", headers=employee_headers, json={"provider_id":provider["id"],"share_latest_checkin":True}).status_code == 403
        assert client.get("/api/v1/workplace/provider/cases/continuity-case", headers=provider_headers).status_code == 200
        enabled_provider_services = client.put(f"/api/v1/workplace/admin/companies/{company['id']}/commercial", headers=admin_headers, json={"enabled_capabilities":{"enrollment":True,"aggregate_analytics":True,"provider_services":True,"voice_support":False}})
        assert enabled_provider_services.status_code == 200

        expired = client.put(f"/api/v1/workplace/admin/companies/{company['id']}/commercial", headers=admin_headers, json={"contract_end_date":(date.today()-timedelta(days=5)).isoformat()})
        assert expired.status_code == 200 and expired.json()["status"] == "GRACE_PERIOD"
        assert expired.json()["grace_period_end"]
        assert client.get("/api/v1/workplace/provider/cases/continuity-case", headers=provider_headers).status_code == 200
        new_support = client.post("/api/v1/workplace/support-requests", headers=employee_headers, json={"provider_id":provider["id"],"share_latest_checkin":True})
        assert new_support.status_code == 201, new_support.text

        suspended = client.put(f"/api/v1/workplace/admin/companies/{company['id']}/commercial", headers=admin_headers, json={"status":"SUSPENDED","reason":"Grace period ended; contract renewal is pending"})
        assert suspended.status_code == 200 and suspended.json()["status"] == "SUSPENDED"
        assert client.post("/api/v1/workplace/admin/enrollment-link", headers=company_headers).status_code == 403
        assert client.get("/api/v1/workplace/admin/report", headers=company_headers).status_code == 403
        assert client.get("/api/v1/workplace/provider/cases/continuity-case", headers=provider_headers).status_code == 200
        assert client.get("/api/v1/workplace/support-requests", headers=employee_headers).status_code == 200
        assert client.get("/api/v1/workplace/checkins", headers=employee_headers).status_code == 200

        reactivated = client.put(f"/api/v1/workplace/admin/companies/{company['id']}/commercial", headers=admin_headers, json={"status":"ACTIVE","reason":"Renewal executed","contract_end_date":(date.today()+timedelta(days=365)).isoformat(),"renewal_date":(date.today()+timedelta(days=350)).isoformat()})
        assert reactivated.status_code == 200 and reactivated.json()["status"] == "ACTIVE"
        assert client.get("/api/v1/workplace/admin/report", headers=company_headers).status_code == 200
        assert client.post("/api/v1/workplace/admin/enrollment-link", headers=company_headers).status_code == 200
        cancelled = client.put(f"/api/v1/workplace/admin/companies/{company['id']}/commercial", headers=admin_headers, json={"status":"CANCELLED","reason":"Company elected to end at term","cancellation_effective_date":(date.today()+timedelta(days=30)).isoformat(),"cancellation_reason":"Company elected not to renew"})
        assert cancelled.status_code == 200 and cancelled.json()["status"] == "CANCELLED"
        conn = db.get_db()
        retained = conn.execute("SELECT (SELECT COUNT(*) FROM workplace_memberships WHERE company_id=? AND user_id=?),(SELECT COUNT(*) FROM workplace_support_cases WHERE company_id=? AND user_id=?),(SELECT COUNT(*) FROM workplace_checkins WHERE company_id=? AND user_id=?)", (company["id"],employee["id"],company["id"],employee["id"],company["id"],employee["id"])).fetchone()
        conn.close()
        assert retained[0] == 1 and retained[1] == 2 and retained[2] == 1


def test_effective_termination_offboards_without_deleting_worker_or_case(db, monkeypatch):
    from datetime import date, datetime, timedelta, timezone
    from backend.services.workplace_lifecycle import sync_offboarding

    monkeypatch.setenv("WORKPLACE_OFFBOARDING_CONTINUITY_DAYS", "2")
    company, company_admin = _company(db)
    provider = _configure_enrollment_readiness(db, company, company_admin)
    employee = _workplace_case(db, company, provider)
    root = _global_admin(db)
    with _client() as client:
        company_headers = _login(client, company_admin["email"])
        provider_headers = _login(client, provider["email"])
        employee_headers = _login(client, employee["email"])
        admin_headers = _login(client, root["email"])
        link_response = client.post("/api/v1/workplace/admin/enrollment-link", headers=company_headers)
        assert link_response.status_code == 200, link_response.text
        token = link_response.json()["token"]

        future = (date.today() + timedelta(days=10)).isoformat()
        scheduled = client.put(f"/api/v1/workplace/admin/companies/{company['id']}/commercial", headers=admin_headers, json={
            "status":"CANCELLED", "reason":"Company elected to end at term", "cancellation_effective_date":future,
            "cancellation_reason":"Company elected not to renew",
        })
        assert scheduled.status_code == 200, scheduled.text
        assert client.get("/api/v1/workplace/admin/offboarding-status", headers=company_headers).json()["status"] == "SCHEDULED"
        conn = db.get_db()
        assert conn.execute("SELECT status FROM workplace_memberships WHERE user_id=?", (employee["id"],)).fetchone()["status"] == "active"
        assert conn.execute("SELECT status FROM workplace_support_cases WHERE id='continuity-case'").fetchone()["status"] == "open"
        assert conn.execute("SELECT status FROM workplace_providers WHERE company_id=? AND provider_id=?", (company["id"], provider["id"])).fetchone()["status"] == "active"
        conn.close()

        effective = client.put(f"/api/v1/workplace/admin/companies/{company['id']}/commercial", headers=admin_headers, json={
            "cancellation_effective_date":date.today().isoformat(),
        })
        assert effective.status_code == 200, effective.text
        assert client.post("/api/v1/workplace/support-requests", headers=employee_headers, json={"provider_id":provider["id"],"share_latest_checkin":True}).status_code == 403
        assert client.get("/api/v1/workplace/admin/report", headers=company_headers).status_code == 403
        assert client.get("/api/v1/workplace/admin/insights", headers=company_headers).status_code == 403
        assert client.get("/api/v1/workplace/provider/cases/continuity-case", headers=provider_headers).status_code == 200
        denied_link = client.post("/api/v1/workplace/enrollment/start", json={
            "token":token,"name":"New Worker","email":"new@acme.co.ke","password":"long-workplace-password",
            "accepted_notice":True,"accepted_workplace_terms":True,
        })
        assert denied_link.status_code in {400,403}

    now = datetime.now(timezone.utc)
    conn = db.get_db()
    initial = conn.execute("SELECT status,continuity_deadline,retention_deadline FROM workplace_offboarding WHERE company_id=?", (company["id"],)).fetchone()
    assert initial["status"] == "IN_PROGRESS" and initial["continuity_deadline"] and initial["retention_deadline"]
    assert conn.execute("SELECT status,continuity_until FROM workplace_support_cases WHERE id='continuity-case'").fetchone()["continuity_until"]
    conn.close()

    conn = db.get_db()
    ended = sync_offboarding(conn, company["id"], actor_id=root["id"], now=now + timedelta(days=3))
    repeated = sync_offboarding(conn, company["id"], actor_id=root["id"], now=now + timedelta(days=4))
    conn.commit()
    membership = conn.execute("SELECT status,ended_at FROM workplace_memberships WHERE company_id=? AND user_id=?", (company["id"], employee["id"])).fetchone()
    account = conn.execute("SELECT role_type,institution_id,status FROM users WHERE id=?", (employee["id"],)).fetchone()
    case = conn.execute("SELECT status FROM workplace_support_cases WHERE id='continuity-case'").fetchone()
    association = conn.execute("SELECT status,ended_at FROM workplace_providers WHERE company_id=? AND provider_id=?", (company["id"], provider["id"])).fetchone()
    retained_company = conn.execute("SELECT 1 FROM institutions WHERE id=?", (company["id"],)).fetchone()
    import sqlite3
    try:
        conn.execute("DELETE FROM institutions WHERE id=?", (company["id"],))
        deletion_blocked = False
    except sqlite3.IntegrityError:
        deletion_blocked = True
        conn.rollback()
    conn.close()
    assert ended["status"] == repeated["status"] == "RETENTION_PERIOD"
    assert membership["status"] == "ended" and membership["ended_at"]
    assert account["role_type"] == "student" and account["institution_id"] is None and account["status"] == "approved"
    assert case["status"] == "closed" and association["status"] == "ended" and association["ended_at"]
    assert retained_company and deletion_blocked


def test_workplace_retention_decisions_respect_live_dependencies():
    from datetime import datetime, timedelta, timezone
    from backend.services.workplace_lifecycle import retention_decision

    old = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
    assert retention_decision("closed_case", old, 365, active_dependency=True) == "RETAIN"
    assert retention_decision("closed_case", old, 365) == "DELETE"
    assert retention_decision("membership", old, 365) == "RETAIN"
    assert retention_decision("audit_event", old, 365) == "RETAIN"


def test_global_admin_creates_new_independent_provider_and_invites_them(db, monkeypatch):
    from backend.routes import workplace

    sent = []
    monkeypatch.setattr(
        workplace,
        "send_html_email",
        lambda email, subject, body, **kwargs: (sent.append((email, subject, body, kwargs)) or True, ""),
    )
    admin = _global_admin(db)
    with _client() as client:
        admin_headers = _login(client, admin["email"])
        payload = {
            "full_name": "Jordan Provider",
            "provider_email": "jordan.provider@gmail.com",
            "professional_type": "Counselor",
            "professional_title": "Licensed Professional Counselor",
            "qualification": "Master's degree",
            "registration_number": "LIC-12345",
            "license_state": "California",
            "verification_reference": "California board lookup 2026-10-04",
        }
        created = client.post(
            "/api/v1/workplace/admin/provider-accounts",
            headers=admin_headers,
            json=payload,
        )
        assert created.status_code == 201, created.text
        result = created.json()
        assert result["account_status"] == "pending"
        assert result["invitation_pending"] is True
        assert result["invitation_sent"] is True
        assert "token" not in created.text.lower()
        assert len(sent) == 1 and sent[0][0] == payload["provider_email"]

        invite_token = re.search(r"token=([^&\"]+)", sent[0][2]).group(1)
        verified = client.post("/api/auth/invite/verify", json={"token": invite_token})
        assert verified.status_code == 200
        accepted = client.post(
            "/api/auth/invite/accept",
            json={"token": invite_token, "password": "new-provider-password"},
        )
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["user"]["role_type"] == "workplace_provider"

        provider = db.get_user_by_email(payload["provider_email"])
        assert provider["status"] == "approved"
        assert provider["user_category"] == "workplace_provider"
        assert provider["institution_id"] is None
        conn = db.get_db()
        credential = conn.execute(
            "SELECT status,demo_only FROM workplace_provider_credentials WHERE provider_id=?",
            (provider["id"],),
        ).fetchone()
        audit = conn.execute(
            "SELECT action FROM audit_log WHERE target_id=? AND action='WORKPLACE_PROVIDER_INVITATION_ACCEPTED'",
            (provider["id"],),
        ).fetchone()
        conn.close()
        assert credential["status"] == "verified" and credential["demo_only"] == 0
        assert audit

        existing = db.create_user(
            "existing.counsellor@gmail.com",
            "Existing Counsellor",
            hash_password("workplace-test-password"),
            role_type="counsellor",
        )
        duplicate = client.post(
            "/api/v1/workplace/admin/provider-accounts",
            headers=admin_headers,
            json={**payload, "provider_email": existing["email"]},
        )
        assert duplicate.status_code == 409
        unchanged = db.get_user_by_id(existing["id"])
        assert unchanged["role_type"] == "counsellor"
