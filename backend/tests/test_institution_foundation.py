"""Regression coverage for the first institution tenancy primitives."""

from backend.services import crypto


def test_institution_lifecycle_and_versioned_settings(db):
    institution = db.create_institution("Tenant A", "k12", created_by=None)
    assert institution["status"] == "PROVISIONING"
    updated = db.update_institution(institution["id"], status="ACTIVE", retention_days=90)
    assert updated["status"] == "ACTIVE"
    assert updated["retention_days"] == 90
    assert updated["settings_version"] >= 2


def test_roster_student_has_explicit_authenticated_user_link(db):
    institution = db.create_institution("Tenant A", "k12")
    user = db.create_user("student@example.test", "Student", "hash", role_type="student", institution_id=institution["id"])
    student_id = db.create_student(
        institution["id"], crypto.hash_student_id("S-1"), crypto.encrypt_pii("Student"),
        crypto.encrypt_pii("student@example.test"), crypto.encrypt_pii("2010-01-01"), True,
        None, user_id=user["id"],
    )["id"]
    assert db.get_student_by_user_id(user["id"])["id"] == student_id


def test_archive_student_removes_it_from_active_roster_and_blocks_user(db):
    institution = db.create_institution("Tenant A", "k12")
    user = db.create_user("student@example.test", "Student", "hash", role_type="student", institution_id=institution["id"])
    student_id = db.create_student(
        institution["id"], crypto.hash_student_id("S-1"), crypto.encrypt_pii("Student"),
        crypto.encrypt_pii("student@example.test"), crypto.encrypt_pii("2010-01-01"), True,
        None, user_id=user["id"],
    )["id"]
    assert db.archive_student(student_id) is True
    assert db.get_student_by_id(student_id) is None
    assert db.get_user_by_id(user["id"])["status"] == "archived"


def test_demo_request_tracks_meeting_and_institution_onboarding(db):
    demo = db.create_demo_request(
        "Owner", "owner@example.test", "Tenant A", "k12",
        role_title="Principal", country="KE", student_count_range="Under 500",
    )
    updated = db.update_demo_request(
        demo["id"], status="demo_scheduled", meeting_at="2026-10-01T09:00:00Z",
        meeting_url="https://meet.example.test/demo",
    )
    assert updated["status"] == "demo_scheduled"
    assert updated["meeting_url"].startswith("https://")
