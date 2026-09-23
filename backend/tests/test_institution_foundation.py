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


def test_school_admin_profile_does_not_require_counsellor_credentials(db):
    institution = db.create_institution("Tenant A", "k12")
    admin = db.create_user("school.admin@example.test", "School Admin", "hash", role_type="school_admin", institution_id=institution["id"])
    updated = db.update_staff_profile(
        admin["id"], phone="+254700000000", country="KE", address="Nairobi"
    )
    assert updated["profile_completed_at"] is not None


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


def test_demo_meeting_response_token_is_lookupable(db):
    from backend.services.crypto import hash_token

    demo = db.create_demo_request("Owner", "owner@example.test", "Tenant A", "k12")
    token_hash = hash_token("one-time-demo-token")
    db.update_demo_request(
        demo["id"], meeting_response="PENDING", meeting_response_token_hash=token_hash,
    )
    matched = db.get_demo_request_by_response_token(token_hash)
    assert matched["id"] == demo["id"]


def test_referrals_are_scoped_and_status_changes_are_audited(db):
    first = db.create_institution("Tenant A", "k12")
    second = db.create_institution("Tenant B", "k12")
    counsellor = db.create_user("counsellor@example.test", "Counsellor", "hash", role_type="counsellor", institution_id=first["id"])
    student = db.create_user("student@example.test", "Student", "hash", role_type="student", institution_id=first["id"])
    other = db.create_user("other@example.test", "Other", "hash", role_type="student", institution_id=second["id"])
    referral = db.create_referral(counsellor["id"], student["id"], "high", "Needs follow-up", "School nurse", "2026-10-10T09:00:00Z")
    db.create_referral(counsellor["id"], other["id"], "low")
    assert len(db.get_referrals(institution_id=first["id"])) == 1
    assert len(db.get_referrals(institution_id=second["id"])) == 1
    db.update_referral(referral["id"], status="in_progress", actor_id=counsellor["id"], actor_role="counsellor", reason="Accepted by care team")
    conn = db.get_db()
    event = conn.execute("SELECT from_status, to_status, reason FROM referral_events WHERE referral_id = ?", (referral["id"],)).fetchone()
    conn.close()
    assert tuple(event) == ("open", "in_progress", "Accepted by care team")
