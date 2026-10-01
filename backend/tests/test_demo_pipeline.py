"""Tests for the demo request pipeline (Delivery Brief §6)."""

from backend.services.email_sender import send_html_email
from backend.services.demo_service import work_email_warning


def _create(db, **overrides) -> dict:
    kwargs = dict(
        full_name="Jordan Blake",
        work_email="jordan@acme.org",
        organisation="Acme Learning Trust",
        organisation_type="k12",
        role_title="Head of Pastoral Care",
        country="UK",
        student_count_range="1,001-5,000",
        message="We'd love a walkthrough.",
        heard_about_us="Conference",
    )
    kwargs.update(overrides)
    return db.create_demo_request(**kwargs)


def test_create_demo_request_stores_consent_to_contact(db):
    req = _create(db, consent_to_contact=False)
    assert req["status"] == "new"
    assert req["consent_to_contact"] == 0
    req2 = _create(db, work_email="other@acme.org", consent_to_contact=True)
    assert req2["consent_to_contact"] == 1


def test_demo_request_status_transitions(db):
    req = _create(db)
    db.update_demo_request(req["id"], status="qualified", notes="good fit")
    row = db.get_demo_request(req["id"])
    assert row["status"] == "qualified"
    assert row["notes"] == "good fit"


def test_update_demo_request_rejects_unknown_fields(db):
    req = _create(db)
    db.update_demo_request(req["id"], work_email="hax@evil.org")
    assert db.get_demo_request(req["id"])["work_email"] == "jordan@acme.org"


def test_list_demo_requests_filters_by_status(db):
    _create(db)
    _create(db, work_email="a@acme.org")
    _create(db, work_email="b@acme.org")
    rows = db.list_demo_requests(status="new")
    assert len(rows) == 3
    first = db.list_demo_requests()[0]
    assert first["created_at"] >= rows[0]["created_at"]


def test_work_email_warning_flags_free_providers():
    assert work_email_warning("jordan@gmail.com", "k12") is not None
    assert work_email_warning("Jordan@outlook.COM", "university") is not None
    assert work_email_warning("jordan@acme.org", "k12") is None
    assert work_email_warning("jordan@school.ac.uk", "k12") is None
    assert work_email_warning("") is None


def test_work_email_warning_only_for_k12_university():
    assert work_email_warning("jordan@gmail.com", "clinic") is None
    assert work_email_warning("jordan@gmail.com", "research") is None
    assert work_email_warning("jordan@gmail.com", "other") is None
    assert work_email_warning("jordan@gmail.com") is None


def test_demo_request_migration_column_exists(db):
    cols = {
        r[1] for r in db.get_db().execute("PRAGMA table_info(demo_requests)").fetchall()
    }
    assert "consent_to_contact" in cols
    assert "population_range" in cols


def test_population_range_is_canonical_and_legacy_aliases_round_trip(db):
    company = _create(
        db,
        organisation_type="company",
        student_count_range="legacy students",
        employee_population_range="legacy employees",
        population_range="50–199",
    )
    assert company["population_range"] == "50–199"
    assert company["employee_population_range"] == "50–199"
    school = _create(
        db,
        work_email="school@acme.org",
        student_count_range="1,001-5,000",
    )
    assert school["population_range"] == school["student_count_range"] == "1,001-5,000"


def test_population_migration_backfills_legacy_company_and_school_ranges(db):
    from alembic import command
    from alembic.config import Config
    from pathlib import Path

    backend_dir = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db.DB_PATH}")
    command.downgrade(cfg, "0029")
    conn = db.get_db()
    for row_id, org_type, students, employees in (
        ("legacy-company", "company", None, "200–499"),
        ("legacy-school", "k12", "500–1,000", None),
    ):
        conn.execute(
            "INSERT INTO demo_requests (id,full_name,work_email,organisation,organisation_type,student_count_range,employee_population_range,status,consent_to_contact,created_at,updated_at) VALUES (?,?,?,?,?,?,?,'new',1,'now','now')",
            (row_id, "Lead", "lead@example.org", "Org", org_type, students, employees),
        )
    conn.commit()
    conn.close()
    db.run_migrations()
    conn = db.get_db()
    ranges = {row["id"]: row["population_range"] for row in conn.execute("SELECT id,population_range FROM demo_requests").fetchall()}
    conn.close()
    assert ranges == {"legacy-company": "200–499", "legacy-school": "500–1,000"}


def test_public_demo_submission_records_company_and_education_leads_only(db, monkeypatch):
    from fastapi.testclient import TestClient
    import backend.main as main

    async def captcha_ok(_token):
        return True

    monkeypatch.setattr(main, "verify_recaptcha_token", captcha_ok)
    monkeypatch.setattr(main, "send_html_email", lambda *args, **kwargs: (False, "email disabled in test"))
    monkeypatch.setattr(main, "DEMO_NOTIFY_EMAIL", "")
    with TestClient(main.app) as client:
        company = client.post("/api/v1/demo-requests", json={
            "full_name": "Morgan Owner", "work_email": "morgan@company.co.ke",
            "organisation": "Example Company", "organisation_type": "company",
            "population_range": "50–199", "employee_population_range": "wrong legacy value",
            "consent_to_contact": True,
        })
        school = client.post("/api/v1/demo-requests", json={
            "full_name": "School Lead", "work_email": "school@district.ac.ke",
            "organisation": "Example District", "organisation_type": "k12",
            "population_range": "500–1,000", "student_count_range": "wrong legacy value",
            "consent_to_contact": True,
        })
        missing_company_population = client.post("/api/v1/demo-requests", json={
            "full_name": "Morgan Owner", "work_email": "second@company.co.ke",
            "organisation": "Example Company", "organisation_type": "company",
            "consent_to_contact": True,
        })
    assert company.status_code == school.status_code == 201
    assert missing_company_population.status_code == 422
    assert db.get_demo_request(company.json()["id"])["population_range"] == "50–199"
    assert db.get_demo_request(company.json()["id"])["employee_population_range"] == "50–199"
    assert db.get_demo_request(school.json()["id"])["population_range"] == "500–1,000"
    conn = db.get_db()
    assert conn.execute("SELECT COUNT(*) FROM institutions WHERE type='company'").fetchone()[0] == 0
    conn.close()


def test_send_html_email_logs_demo_request_event(db, monkeypatch):
    # Hermetic: the developer's real .env may configure Resend, which would
    # make this send succeed and defeat the "failed" assertion. Force no transport.
    from backend.services import email_sender

    monkeypatch.setattr(email_sender, "get_secret", lambda name: "")
    ok, err = send_html_email(
        "jordan@acme.org",
        "Sub",
        "<p>Hi</p>",
        related_type="demo_request",
        related_id="demo-1",
        metadata={"event": "confirmation"},
    )
    assert ok is False  # no Resend configured in tests
    assert "not configured" in err
    events = (
        db.get_db()
        .execute("SELECT * FROM email_events WHERE related_type = 'demo_request'")
        .fetchall()
    )
    assert len(events) == 1
    assert events[0]["related_id"] == "demo-1"
    assert events[0]["event"] == "failed"


def test_consent_to_contact_flag_round_trips_via_create(db):
    req = _create(db)
    assert req["consent_to_contact"] in (0, 1)
