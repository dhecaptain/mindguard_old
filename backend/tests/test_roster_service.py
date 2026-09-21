"""Tests for CSV roster ingestion (Delivery Brief §5)."""

from backend.services import crypto, roster_service

CSV_HEADER = "student_id,student_first_name,student_email,date_of_birth,grade_level,parent_email\n"


def _seed_admin(db) -> None:
    u = db.create_user("admin@school.edu", "Admin", "x", role_type="admin")
    conn = db.get_db()
    conn.execute("UPDATE users SET id = 'admin-001' WHERE id = ?", (u["id"],))
    conn.commit()
    conn.close()


def _csv(body: str) -> bytes:
    return (CSV_HEADER + body).encode("utf-8")


def test_parse_roster_csv_ok():
    rows, err = roster_service.parse_roster_csv(
        _csv("S-1,Jane,jane@school.edu,2010-01-01,9,mom@school.edu\n")
    )
    assert err is None
    assert len(rows) == 1
    assert rows[0]["student_id"] == "S-1"


def test_parse_rejects_missing_required_column():
    raw = "student_id,student_first_name\nS-1,Jane\n".encode()
    rows, err = roster_service.parse_roster_csv(raw)
    assert rows == []
    assert "student_email" in err and "date_of_birth" in err


def test_parse_rejects_bad_encoding():
    rows, err = roster_service.parse_roster_csv(b"\xff\xfe\x00garbage")
    assert rows == []
    assert "UTF-8" in err


def test_upsert_creates_encrypted_rows(db):
    _seed_admin(db)
    inst = db.create_institution("Riverside High", "secondary")
    summary = roster_service.upsert_roster(
        inst["id"],
        _csv("S-1,Jane,jane@school.edu,2010-01-01,9,mom@school.edu\n"),
        "admin-001",
    )
    assert (
        summary["created"] == 1 and summary["updated"] == 0 and summary["errors"] == []
    )
    students = db.list_students(institution_id=inst["id"])
    assert len(students) == 1
    stored = students[0]
    assert stored["student_id_hash"] == crypto.hash_student_id("S-1")
    assert stored["student_id_hash"] == crypto.hash_student_id("  s-1  ")
    assert stored["first_name_encrypted"].startswith("gcm1:")
    assert "Jane" not in stored["first_name_encrypted"]
    assert crypto.decrypt_pii(stored["first_name_encrypted"]) == "Jane"
    assert crypto.decrypt_pii(stored["email_encrypted"]) == "jane@school.edu"
    assert stored["is_minor"] == 1


def test_minor_threshold_computes_age(db):
    _seed_admin(db)
    inst = db.create_institution("Uni", "university")
    summary = roster_service.upsert_roster(
        inst["id"],
        _csv(
            "U-1,Alex,alex@uni.edu,2002-05-05,,,\nU-2,Bob,bob@uni.edu,2011-03-03,,mom@school.edu\n"
        ),
        "admin-001",
        minor_age_threshold=18,
    )
    assert summary["errors"] == []
    students = {
        s["student_id_hash"]: s for s in db.list_students(institution_id=inst["id"])
    }
    alex = db.get_student_by_id(students[crypto.hash_student_id("U-1")]["id"])
    bob = db.get_student_by_id(students[crypto.hash_student_id("U-2")]["id"])
    assert alex["is_minor"] == 0
    assert bob["is_minor"] == 1


def test_upsert_is_idempotent(db):
    _seed_admin(db)
    inst = db.create_institution("Riverside High", "secondary")
    raw = _csv("S-1,Jane,jane@school.edu,2010-01-01,9,mom@school.edu\n")
    first = roster_service.upsert_roster(inst["id"], raw, "admin-001")
    second = roster_service.upsert_roster(inst["id"], raw, "admin-001")
    assert first["created"] == 1
    assert second["created"] == 0 and second["updated"] == 1
    assert len(db.list_students(institution_id=inst["id"])) == 1


def test_bad_row_does_not_abort_upload_if_under_10_percent(db):
    _seed_admin(db)
    inst = db.create_institution("Riverside High", "secondary")
    # 10 rows: 1 bad (not-a-date), 9 good. Error rate = 10%. Ingestion should proceed.
    csv_rows = ["S-1,Jane,jane1@school.edu,not-a-date,9,\n"]
    for i in range(2, 11):
        csv_rows.append(f"S-{i},Student{i},student{i}@school.edu,2000-01-01,10,\n")
    summary = roster_service.upsert_roster(
        inst["id"],
        _csv("".join(csv_rows)),
        "admin-001",
    )
    assert summary["created"] == 9
    assert len(summary["errors"]) == 1
    assert "unparseable" in summary["errors"][0]["error"]


def test_bad_row_aborts_upload_if_over_10_percent(db):
    _seed_admin(db)
    inst = db.create_institution("Riverside High", "secondary")
    # 2 rows: 1 bad, 1 good. Error rate = 50%. Ingestion should be rejected.
    summary = roster_service.upsert_roster(
        inst["id"],
        _csv(
            "S-1,Jane,jane1@school.edu,not-a-date,9,\nS-2,Bob,bob@school.edu,2000-01-01,10,\n"
        ),
        "admin-001",
    )
    assert summary["created"] == 0
    assert "rejected" in summary["parse_error"].lower()


def test_missing_optional_parent_email_for_adult_ok(db):
    _seed_admin(db)
    inst = db.create_institution("Riverside High", "secondary")
    summary = roster_service.upsert_roster(
        inst["id"], _csv("S-9,Ava,ava@school.edu,2000-01-01,9,\n"), "admin-001"
    )
    assert summary["errors"] == [] and summary["created"] == 1
    student = db.list_students(institution_id=inst["id"])[0]
    assert student["parent_email_encrypted"] is None
