"""Institution retention and archived-student anonymisation."""

import logging
from datetime import datetime, timedelta, timezone

from backend import database
from backend.services.crypto import encrypt_pii, hash_student_id

logger = logging.getLogger(__name__)


def _due(row: dict, now: datetime) -> bool:
    archived_at = row.get("archived_at")
    if not archived_at:
        return False
    try:
        archived = datetime.fromisoformat(archived_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    if archived.tzinfo is None:
        archived = archived.replace(tzinfo=timezone.utc)
    retention_days = max(1, int(row.get("retention_days") or 30))
    return now >= archived + timedelta(days=retention_days)


def run_retention_cleanup(institution_id: str | None = None, limit: int = 100) -> dict:
    now = datetime.now(timezone.utc)
    conn = database.get_db()
    clauses = ["s.archived_at IS NOT NULL", "s.deleted_at IS NULL"]
    params: list = []
    if institution_id:
        clauses.append("s.institution_id = ?")
        params.append(institution_id)
    rows = conn.execute(
        "SELECT s.id, s.user_id, s.archived_at, i.retention_days "
        "FROM students s JOIN institutions i ON i.id = s.institution_id "
        f"WHERE {' AND '.join(clauses)} ORDER BY s.archived_at ASC LIMIT ?",
        params + [max(1, min(limit, 1000))],
    ).fetchall()
    conn.close()

    candidates = [dict(row) for row in rows if _due(dict(row), now)]
    anonymized = 0
    for candidate in candidates:
        sid = candidate["id"]
        conn = database.get_db()
        try:
            conn.execute("BEGIN")
            redacted = encrypt_pii("Archived student")
            conn.execute(
                "UPDATE students SET student_id_hash = ?, first_name_encrypted = ?, "
                "email_encrypted = ?, date_of_birth_encrypted = ?, parent_email_encrypted = NULL, "
                "parent_first_name_encrypted = NULL, updated_at = ? WHERE id = ?",
                (hash_student_id(f"archived:{sid}"), redacted, redacted, redacted, now.isoformat(), sid),
            )
            if candidate.get("user_id"):
                conn.execute(
                    "UPDATE users SET email = ?, name = 'Archived student', dob = NULL, parent_email = NULL, "
                    "parent_guardian_id = NULL, status = 'archived' WHERE id = ?",
                    (f"archived+{candidate['user_id']}@redacted.invalid", candidate["user_id"]),
                )
                conn.execute("UPDATE analyses SET text = NULL WHERE user_id = ?", (candidate["user_id"],))
                conn.execute("UPDATE communications SET message = '[redacted after retention]' WHERE sender_id = ? OR receiver_id = ?", (candidate["user_id"], candidate["user_id"]))
                conn.execute("UPDATE notes SET body = '[redacted after retention]' WHERE student_id = ?", (candidate["user_id"],))
                conn.execute("UPDATE linked_accounts SET active = 0, credentials_json = NULL WHERE student_id = ?", (candidate["user_id"],))
                conn.execute("UPDATE analysis_sessions SET findings_json = '{}', insights = NULL, recommendations = NULL, counsellor_notes = NULL WHERE student_id = ?", (candidate["user_id"],))
                conn.execute("UPDATE consents SET recipient_email = ?, magic_token = NULL, signed_token_hash = NULL WHERE student_id = ?", (redacted, candidate["user_id"]))
                conn.execute("UPDATE appointments SET notes = NULL, location = NULL WHERE student_id = ?", (candidate["user_id"],))
            conn.execute("UPDATE students SET archived_at = COALESCE(archived_at, ?) WHERE id = ?", (now.isoformat(), sid))
            conn.commit()
            anonymized += 1
        except Exception:
            conn.rollback()
            logger.exception("retention anonymisation failed for student=%s", sid)
        finally:
            conn.close()
    return {"eligible": len(candidates), "anonymized": anonymized}
