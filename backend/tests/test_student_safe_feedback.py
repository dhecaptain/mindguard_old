"""Student feedback must never expose private counsellor note content."""

from backend.auth import hash_password


def test_shared_feedback_uses_separate_student_message(db):
    counsellor = db.create_user(
        "feedback-counsellor@example.test",
        "Feedback Counsellor",
        hash_password("pw-12345"),
        role_type="counsellor",
    )
    student = db.create_user(
        "feedback-student@example.test",
        "Feedback Student",
        hash_password("pw-12345"),
        role_type="student",
    )

    private_note = db.create_note(
        student["id"],
        counsellor["id"],
        "PRIVATE CASE DETAILS MUST NOT BE SHOWN",
        share_with_student=True,
        student_title="A safe check-in",
        student_message="Please remember your next check-in is available when you are ready.",
    )

    assert private_note["body"] == "PRIVATE CASE DETAILS MUST NOT BE SHOWN"
    feedback = db.get_student_feedback(student["id"])
    assert len(feedback) == 1
    assert feedback[0]["body"] == "Please remember your next check-in is available when you are ready."
    assert "PRIVATE CASE DETAILS" not in feedback[0]["body"]
