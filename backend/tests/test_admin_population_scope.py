import asyncio

from starlette.requests import Request

from backend.auth import hash_password
from backend.services import crypto


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/admin/assignments",
            "headers": [],
            "client": ("127.0.0.1", 1234),
            "query_string": b"",
            "server": ("testserver", 80),
            "scheme": "http",
        }
    )


def test_admin_student_listing_separates_public_users(db):
    public = db.create_user(
        "public@example.com", "Public User", hash_password("pw-12345")
    )
    db.update_user_onboarding(public["id"], "adult")
    counsellor = db.create_user(
        "staff@example.com", "Staff", hash_password("pw-12345"), role_type="counsellor"
    )
    institution_student = db.create_user(
        "roster@example.com", "Roster Student", hash_password("pw-12345")
    )
    db.create_consent(
        institution_student["id"], counsellor["id"], "roster@example.com", "student", []
    )

    listed = {row["id"] for row in db.get_students()}
    individuals = {row["id"] for row in db.get_individual_users()}

    assert institution_student["id"] in listed
    assert public["id"] not in listed
    assert public["id"] in individuals
    assert institution_student["id"] not in individuals


def test_staff_accounts_are_created_as_staff(db):
    staff = db.create_user(
        "newstaff@example.com",
        "New Staff",
        hash_password("pw-12345"),
        role_type="school_admin",
    )
    assert staff["user_category"] == "staff"
    assert staff["onboarding_completed_at"]


def test_assignment_derives_institution_from_counsellor_and_roster(db):
    from backend.main import create_assignment

    admin = db.create_user(
        "admin@example.com", "Admin", hash_password("pw-12345"), role_type="admin"
    )
    institution = db.create_institution("Tenant", "k12", created_by=admin["id"])
    counsellor = db.create_user(
        "counsellor@example.com",
        "Counsellor",
        hash_password("pw-12345"),
        role_type="counsellor",
        institution_id=institution["id"],
    )
    student = db.create_user(
        "student@example.com", "Student", hash_password("pw-12345")
    )
    db.create_student(
        institution["id"],
        crypto.hash_student_id("S-100"),
        crypto.encrypt_pii("Student"),
        crypto.encrypt_pii("student@example.com"),
        crypto.encrypt_pii("2008-01-01"),
        False,
        admin["id"],
        user_id=student["id"],
    )

    result = asyncio.run(
        create_assignment(
            {"counsellor_id": counsellor["id"], "student_id": student["id"]},
            _request(),
            admin,
        )
    )

    assert result["assignment"]["institution_id"] == institution["id"]
