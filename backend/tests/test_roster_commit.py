"""Tests for one-action roster upload + consent dispatch (Brief §2.4/§2.5)."""

from backend.services import consent_service, crypto, roster_service

CSV_HEADER = "student_id,first_name,last_name,email,date_of_birth,grade_level,parent_email\n"


def _seed_admin(db) -> None:
    u = db.create_user("admin@school.edu", "Admin", "x", role_type="admin")
    conn = db.get_db()
    conn.execute("UPDATE users SET id = 'admin-001' WHERE id = ?", (u["id"],))
    conn.commit()
    conn.close()


def _csv(body: str) -> bytes:
    return (CSV_HEADER + body).encode("utf-8")


def _students_for(db, summary) -> list:
    return [db.get_student_by_id(i) for i in summary["student_ids"]]


def _outbox_rows(db) -> list:
    """Outbox rows left by a bulk dispatch (queued for the background worker)."""
    return db.list_email_outbox()


def _current_consent(db, roster_student_id):
    """Consent linked to a roster student via students.current_consent_id."""
    row = db.get_student_by_id(roster_student_id)
    return db.get_consent_by_id(row["current_consent_id"])


def test_commit_dispatches_adult_to_student(db):
    _seed_admin(db)
    inst = db.create_institution("Riverside High", "secondary")
    summary = roster_service.upsert_roster(
        inst["id"],
        _csv("U-1,Alex,Roe,alex@uni.edu,2002-05-05,12,\n"),
        "admin-001",
    )
    result = consent_service.dispatch_consents_for_students(
        _students_for(db, summary), "admin-001"
    )
    assert result["created"] == 1
    assert result["dispatched"] == 1
    assert result["email_queued"] == 1
    assert result["courtesy_queued"] == 0
    assert result["routing_errors"] == []

    rows = _outbox_rows(db)
    assert {r["to_email"] for r in rows} == {"alex@uni.edu"}
    assert all(r["status"] == "queued" for r in rows)

    consent = _current_consent(db, summary["student_ids"][0])
    assert consent is not None
    assert consent["recipient_role"] == "student"
    assert consent["status"] == "PENDING"


def test_commit_dispatches_minor_to_parent_with_courtesy(db):
    _seed_admin(db)
    inst = db.create_institution("Riverside High", "secondary")
    summary = roster_service.upsert_roster(
        inst["id"],
        _csv("S-1,Jane,Doe,jane@school.edu,2010-01-01,9,mom@school.edu\n"),
        "admin-001",
    )
    result = consent_service.dispatch_consents_for_students(
        _students_for(db, summary), "admin-001"
    )
    assert result["created"] == 1
    assert result["courtesy_queued"] == 1
    addresses = {r["to_email"] for r in _outbox_rows(db)}
    assert "mom@school.edu" in addresses
    assert "jane@school.edu" in addresses

    consent = _current_consent(db, summary["student_ids"][0])
    assert consent is not None
    assert consent["recipient_role"] == "parent"
    assert consent["recipient_email"] == "mom@school.edu"
    assert consent["status"] == "PENDING"


def test_commit_minor_without_parent_is_imported_but_routing_is_pending(db):
    _seed_admin(db)
    inst = db.create_institution("Riverside High", "secondary")
    
    # 1. The minor is imported so other eligible rows in the same CSV are not
    # delayed. Consent remains pending until a guardian email is supplied.
    summary = roster_service.upsert_roster(
        inst["id"],
        _csv("S-1,Jane,Doe,jane@school.edu,2010-01-01,9,\n"),
        "admin-001",
    )
    assert summary["errors"] == []
    assert summary["created"] == 1

    # 2. Verification at dispatch time (defensive path):
    # Construct a student row bypassing the CSV validator to test service robustness
    student_payload = dict(
        institution_id=inst["id"],
        student_id_hash=crypto.hash_student_id("S-2"),
        first_name_encrypted=crypto.encrypt_pii("Bob"),
        email_encrypted=crypto.encrypt_pii("bob@school.edu"),
        date_of_birth_encrypted=crypto.encrypt_pii("2010-01-01"),
        is_minor=True,
        created_by="admin-001",
        parent_email_encrypted=None,
    )
    created_student = db.create_student(**student_payload)
    created_student = db.get_student_by_id(created_student["id"])

    result = consent_service.dispatch_consents_for_students(
        [created_student], "admin-001"
    )
    assert result["created"] == 0
    assert result["skipped_no_parent"] == 1
    assert len(result["routing_errors"]) == 1
    assert "parent_email" in result["routing_errors"][0]["reason"]
    # The student may still receive an activation invitation; the protected
    # wellbeing consent request is the part that must remain blocked.
    assert {row["to_email"] for row in _outbox_rows(db)} == {"bob@school.edu"}


def test_commit_skips_students_with_live_consent(db):
    _seed_admin(db)
    inst = db.create_institution("Riverside High", "secondary")
    summary = roster_service.upsert_roster(
        inst["id"],
        _csv("U-1,Alex,Roe,alex@uni.edu,2002-05-05,12,\n"),
        "admin-001",
    )
    consent_service.dispatch_consents_for_students(
        _students_for(db, summary), "admin-001"
    )
    queued_after_first = len(_outbox_rows(db))
    assert queued_after_first == 1

    result = consent_service.dispatch_consents_for_students(
        _students_for(db, summary), "admin-001"
    )
    assert result["created"] == 0
    assert result["skipped_live"] == 1
    assert len(_outbox_rows(db)) == queued_after_first


def test_commit_defaults_platforms(db):
    _seed_admin(db)
    inst = db.create_institution("Riverside High", "secondary")
    summary = roster_service.upsert_roster(
        inst["id"],
        _csv("U-1,Alex,Roe,alex@uni.edu,2002-05-05,12,\n"),
        "admin-001",
    )
    consent_service.dispatch_consents_for_students(_students_for(db, summary), "admin-001")
    import json
    consent = _current_consent(db, summary["student_ids"][0])
    assert json.loads(consent["platforms_json"]) == consent_service.DEFAULT_BULK_PLATFORMS


def test_upload_summary_reports_minor_adult_counts(db):
    _seed_admin(db)
    inst = db.create_institution("Riverside High", "secondary")
    summary = roster_service.upsert_roster(
        inst["id"],
        _csv(
            "S-1,Jane,Doe,jane@school.edu,2010-01-01,9,mom@school.edu\n"
            "U-1,Alex,Roe,alex@uni.edu,2002-05-05,12,\n"
            "S-2,Jake,Doe,jake@school.edu,2012-02-02,8,dad@school.edu\n"
        ),
        "admin-001",
    )
    assert summary["created"] == 3
    assert summary["errors"] == []
    assert summary["minors"] == 2
    assert summary["adults"] == 1
    assert summary["minors"] + summary["adults"] == summary["created"]


OVERRIDE_HEADER = (
    "student_id,first_name,last_name,email,date_of_birth,grade_level,parent_email,is_minor\n"
)


def _csv_override(body: str) -> bytes:
    return (OVERRIDE_HEADER + body).encode("utf-8")


def test_minor_override_beats_dob_calculation(db):
    _seed_admin(db)
    inst = db.create_institution("Riverside High", "secondary")
    summary = roster_service.upsert_roster(
        inst["id"],
        _csv_override(
            # Adult by DOB but explicitly flagged minor -> must route to parent.
            "O-1,Chris,Roe,chris@uni.edu,2002-05-05,12,mom@school.edu,yes\n"
            # Minor by DOB but explicitly flagged adult -> must route to self.
            "A-1,Dan,Roe,dan@uni.edu,2012-01-01,8,,no\n"
        ),
        "admin-001",
    )
    assert summary["errors"] == []
    assert summary["created"] == 2
    assert summary["minors"] == 1
    assert summary["adults"] == 1
    assert db.get_student_by_id(summary["student_ids"][0])["is_minor"] == 1
    assert db.get_student_by_id(summary["student_ids"][1])["is_minor"] == 0

    result = consent_service.dispatch_consents_for_students(
        _students_for(db, summary), "admin-001"
    )
    assert result["created"] == 2
    assert result["dispatched"] == 2
    by_recipient = {
        _current_consent(db, sid)["recipient_role"]
        for sid in summary["student_ids"]
    }
    assert by_recipient == {"parent", "student"}


def test_leap_day_birthday_age_boundary(db):
    from datetime import date

    from backend.services.roster_service import _age_years

    leap_baby = date(2000, 2, 29)
    assert _age_years(leap_baby, on=date(2016, 2, 29)) == 16
    assert _age_years(leap_baby, on=date(2018, 2, 28)) == 17
    assert _age_years(leap_baby, on=date(2018, 3, 1)) == 18

    _seed_admin(db)
    inst = db.create_institution("Riverside High", "secondary")
    summary = roster_service.upsert_roster(
        inst["id"],
        _csv("L-1,Leap,Baby,leap@school.edu,2016-02-29,4,mom@school.edu\n"),
        "admin-001",
    )
    assert summary["errors"] == []
    assert summary["minors"] == 1
    assert db.get_student_by_id(summary["student_ids"][0])["is_minor"] == 1
