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
        "UPDATE users SET status='approved', user_category='adult', role_type='company_admin', institution_id=? WHERE id=?",
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
        "UPDATE users SET status='approved', user_category='workplace_employee' WHERE id=?",
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
            "UPDATE users SET status='approved', user_category='workplace_employee' WHERE id=?",
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
                    f"c-{i}",
                    company["id"],
                    person["id"],
                    encrypt_pii('{"mood": 4, "stress": 2, "support_access": 3}'),
                    now,
                ),
            )
        conn.commit()
        conn.close()
    with _client() as client:
        headers = _login(client, admin["email"])
        response = client.get("/api/v1/workplace/admin/report", headers=headers)
        assert response.status_code == 200 and response.json()["suppressed"] is True
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
        "UPDATE users SET status='approved', user_category='workplace_employee' WHERE id=?",
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
        blocked = client.post(
            "/api/v1/workplace/admin/enrollment-link", headers=company_headers
        )
        assert blocked.status_code == 403
        reviewed = client.post(
            f"/api/v1/workplace/admin/companies/{company_id}/legal-review",
            headers=root_headers,
            json={"reviewed": True, "reference": "KE privacy review record 2026-01"},
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
                "verification_reference": "Credential document reviewed",
            },
        )
        assert credentials.status_code == 201, credentials.text
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
