import json
import logging
import os
import re
import secrets
import sqlite3
import string
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.config import CONSENT_EXPIRY_DAYS
from backend.services.crypto import decrypt_pii, encrypt_pii, hash_email, hash_token, redact_pii
from backend.services.platform_registry import normalize_platform

logger = logging.getLogger(__name__)

DB_PATH = Path(os.getenv("MINDGUARD_DB_DIR", str(Path(__file__).resolve().parent.parent))) / "mindguard.db"


def get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _decrypt_field(value) -> str | None:
    """Decrypt a `gcm1:` PII blob; leave legacy plaintext (and non-str) untouched."""
    if isinstance(value, str) and value.startswith("gcm1:"):
        return decrypt_pii(value)
    return value


def _decrypt_consent_row(row: dict) -> dict:
    if "recipient_email" in row:
        row = {**row, "recipient_email": _decrypt_field(row["recipient_email"])}
    return row


def _decrypt_demo_row(row: dict) -> dict:
    if any(k in row for k in ("full_name", "work_email", "organisation")):
        row = {
            **row,
            "full_name": _decrypt_field(row.get("full_name")),
            "work_email": _decrypt_field(row.get("work_email")),
            "organisation": _decrypt_field(row.get("organisation")),
        }
    return row


def _decrypt_email_event_row(row: dict) -> dict:
    if "recipient_email" in row:
        row = {**row, "recipient_email": _decrypt_field(row["recipient_email"])}
    return row


def _decrypt_outbox_row(row: dict) -> dict:
    if "to_email" in row:
        row = {**row, "to_email": _decrypt_field(row["to_email"])}
    if row.get("metadata_json"):
        try:
            row = {**row, "metadata_json": json.loads(row["metadata_json"])}
        except (ValueError, TypeError):
            pass
    return row


def health_check() -> dict:
    """Lightweight liveness probe: verify the DB is reachable and schema is present."""
    try:
        conn = get_db()
        row = conn.execute("SELECT COUNT(*) AS n FROM sqlite_master WHERE type='table'").fetchone()
        conn.close()
        return {"db": "ok", "tables": row["n"] if row else 0}
    except Exception as exc:
        return {"db": "error", "error": str(exc)}


def run_migrations(db_path: str | Path | None = None) -> None:
    """Apply pending Alembic migrations to the database.

    The schema is owned by versioned migrations under ``backend/alembic/``
    (see migration ``0001_baseline``, an idempotent reconciliation of the
    previously ad-hoc DDL). ``db_path`` defaults to the active ``DB_PATH`` so
    the migration always targets the same SQLite file the app uses — including
    under tests, where ``database.DB_PATH`` is patched per test.
    """
    from alembic import command
    from alembic.config import Config

    target = Path(db_path) if db_path is not None else DB_PATH
    target.parent.mkdir(parents=True, exist_ok=True)

    backend_dir = Path(__file__).resolve().parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{target}")
    command.upgrade(cfg, "head")


def init_db():
    """Ensure the schema is current by running versioned migrations."""
    run_migrations()


def _make_referral_code() -> str:
    alphabet = string.ascii_uppercase.replace('O', '').replace('I', '') + '23456789'
    return ''.join(secrets.choice(alphabet) for _ in range(8))


def seed_defaults():
    """Seed demo users if the DB is fresh.

    Known-password demo accounts (``password``) are ONLY created when the app is
    not running in production (``MINDGUARD_ENV != "production"``). In production
    the only seeded account is ``admin@mindguard.org``, which never uses a known
    default password — it is either set via ``MINDGUARD_ADMIN_PASSWORD`` or
    generated randomly and logged once.
    """
    conn = get_db()
    cur = conn.execute("SELECT COUNT(*) FROM users")
    if cur.fetchone()[0] > 0:
        conn.close()
        return

    import bcrypt
    is_production = os.getenv("MINDGUARD_ENV", "").strip().lower() == "production"

    # The admin must never ship with a known default password. Production should
    # set MINDGUARD_ADMIN_PASSWORD; otherwise we generate one and log it once so
    # the operator can capture it from the deploy log.
    admin_password = os.getenv("MINDGUARD_ADMIN_PASSWORD") or ""
    if not admin_password:
        admin_password = secrets.token_urlsafe(24)
        logger.warning(
            "MINDGUARD_ADMIN_PASSWORD is not set; generated a random password for "
            "admin@mindguard.org (%s). Set MINDGUARD_ADMIN_PASSWORD to control it.",
            admin_password,
        )
    admin_hash = bcrypt.hashpw(admin_password.encode(), bcrypt.gensalt()).decode()

    now = datetime.now(timezone.utc).isoformat()
    users = [
        ("admin-001",  "admin@mindguard.org",      "Admin User",      "admin",      admin_hash, "approved", now),
    ]
    if not is_production:
        pw = bcrypt.hashpw(b"password", bcrypt.gensalt()).decode()
        users.extend([
            ("couns-001",  "counsellor@mindguard.org",  "Sarah Counsellor","counsellor", pw, "approved", now),
            ("stud-001",   "student@mindguard.org",     "Demo Student",    "student",    pw, "approved", now),
            ("stud-002",   "diana@mindguard.org",       "Diana Opiyo",     "student",    pw, "approved", "2025-01-15T00:00:00"),
            ("stud-003",   "brian@student.ac.ke",       "Brian Mwangi",    "student",    pw, "pending",  "2025-02-03T00:00:00"),
            ("stud-004",   "fatuma@student.ac.ke",      "Fatuma Hassan",   "student",    pw, "approved", "2025-02-10T00:00:00"),
            ("stud-005",   "kevin@student.ac.ke",       "Kevin Otieno",    "student",    pw, "pending",  "2025-03-01T00:00:00"),
            ("couns-002",  "demo@mindguard.org",        "Demo User",       "counsellor", pw, "approved", now),
        ])
    conn.executemany(
        "INSERT INTO users (id, email, name, role_type, password_hash, status, created_at) VALUES (?,?,?,?,?,?,?)",
        users,
    )
    if not is_production:
        # Seed a demo conversation between student@mindguard.org and counsellor@mindguard.org
        demo_msgs = [
            ("msg-001", "couns-001", "stud-001", "Hello! Welcome to MindGuard. How are you feeling today?", now),
            ("msg-002", "stud-001", "couns-001", "Hi! I'm doing okay, just wanted to check in.", now),
            ("msg-003", "couns-001", "stud-001", "That's great to hear. I'm here whenever you need someone to talk to.", now),
        ]
        conn.executemany(
            "INSERT OR IGNORE INTO communications (id, sender_id, receiver_id, message, read, created_at) VALUES (?,?,?,?,1,?)",
            demo_msgs,
        )
    conn.commit()
    conn.close()


def get_user_by_email(email: str):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_id(user_id: str):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


# ── Token revocation (persistent blacklist) ──────────────────────────
# Revoked JWTs live in the ``revoked_tokens`` table so logout survives worker
# restarts and is shared across processes (previously an in-memory set).


def revoke_token(jti: str, expires_at: str | None = None) -> None:
    """Persist a revoked JWT, pruning expired rows opportunistically."""
    now = datetime.now(timezone.utc).isoformat()
    expiry = expires_at or (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    conn = get_db()
    conn.execute("DELETE FROM revoked_tokens WHERE expires_at < ?", (now,))
    conn.execute(
        "INSERT OR IGNORE INTO revoked_tokens (jti, revoked_at, expires_at) VALUES (?,?,?)",
        (jti, now, expiry),
    )
    conn.commit()
    conn.close()


def is_token_revoked(jti: str) -> bool:
    conn = get_db()
    row = conn.execute("SELECT 1 FROM revoked_tokens WHERE jti = ?", (jti,)).fetchone()
    conn.close()
    return row is not None


def create_user(
    email: str, name: str, password_hash: str, role_type: str = "student",
    dob: str | None = None, parent_email: str | None = None, referred_by: str | None = None,
    institution_id: str | None = None,
) -> dict:
    uid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    # Generate a unique referral code
    for _ in range(10):
        code = _make_referral_code()
        exists = conn.execute("SELECT 1 FROM users WHERE referral_code = ?", (code,)).fetchone()
        if not exists:
            break
    conn.execute(
        "INSERT INTO users (id, email, name, role_type, password_hash, status, created_at, dob, parent_email, referral_code, referred_by, institution_id) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (uid, email.strip().lower(), name, role_type, password_hash, "pending", now, dob, parent_email, code, referred_by, institution_id),
    )
    conn.commit()
    conn.close()
    return {"id": uid, "email": email, "name": name, "role_type": role_type, "status": "pending", "referral_code": code, "institution_id": institution_id}


def update_user_password(user_id: str, password_hash: str) -> bool:
    conn = get_db()
    cur = conn.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (password_hash, user_id),
    )
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok


def update_user_role(user_id: str, role_type: str) -> dict | None:
    """Set a user's role. Returns the updated user row or None if not found."""
    conn = get_db()
    cur = conn.execute(
        "UPDATE users SET role_type = ? WHERE id = ?",
        (role_type, user_id),
    )
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return get_user_by_id(user_id) if ok else None


def set_user_invitation(user_id: str, token_hash: str, expires_at: str) -> bool:
    """Store hashed invitation token for counsellor magic-link."""
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    cur = conn.execute(
        "UPDATE users SET invitation_token_hash = ?, invitation_expires_at = ?, invited_at = ? WHERE id = ?",
        (token_hash, expires_at, now, user_id),
    )
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok


def get_user_by_invitation_token_hash(token_hash: str) -> dict | None:
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM users WHERE invitation_token_hash = ? LIMIT 1",
        (token_hash,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def clear_user_invitation(user_id: str) -> bool:
    conn = get_db()
    cur = conn.execute(
        "UPDATE users SET invitation_token_hash = NULL, invitation_expires_at = NULL WHERE id = ?",
        (user_id,),
    )
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok


def update_user_onboarding(
    user_id: str,
    user_category: str,
    institution_id: str | None = None,
    parent_guardian_id: str | None = None,
) -> bool:
    """Set onboarding category and institutional/parent links."""
    allowed = {"pending", "adult", "minor", "parent", "institution_managed"}
    if user_category not in allowed:
        user_category = "pending"
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    cur = conn.execute(
        "UPDATE users SET user_category = ?, institution_id = ?, parent_guardian_id = ?, onboarding_completed_at = ? WHERE id = ?",
        (user_category, institution_id, parent_guardian_id, now, user_id),
    )
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok


def create_analysis_session(
    student_id: str,
    counsellor_id: str | None,
    institution_id: str | None,
    consent_id: str | None,
    analysis_type: str,
    platforms: list,
    findings: dict | None = None,
    risk_score: float | None = None,
    insights: str | None = None,
    recommendations: str | None = None,
    status: str = "completed",
    progress_json: dict | None = None,
    error_json: dict | None = None,
) -> dict:
    sid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    conn.execute(
        "INSERT INTO analysis_sessions (id, student_id, counsellor_id, institution_id, consent_id, started_at, completed_at, analysis_type, platforms_json, findings_json, risk_score, insights, recommendations, status, progress_json, error_json, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            sid,
            student_id,
            counsellor_id,
            institution_id,
            consent_id,
            now,
            now,
            analysis_type,
            json.dumps(platforms) if platforms else None,
            json.dumps(findings) if findings else None,
            risk_score,
            insights,
            recommendations,
            status,
            json.dumps(progress_json) if progress_json else None,
            json.dumps(error_json) if error_json else None,
            now,
            now,
        ),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM analysis_sessions WHERE id = ?", (sid,)).fetchone()
    conn.close()
    return dict(row) if row else {"id": sid}


def update_analysis_session_progress(session_id: str, status: str, progress: dict | None = None, error: dict | None = None) -> bool:
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    cur = conn.execute(
        "UPDATE analysis_sessions SET status = ?, progress_json = ?, error_json = ?, updated_at = ? WHERE id = ?",
        (
            status,
            json.dumps(progress) if progress else None,
            json.dumps(error) if error else None,
            now,
            session_id,
        ),
    )
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok


def set_analysis_session_content(
    session_id: str,
    findings: dict | None = None,
    risk_score: float | None = None,
    insights: str | None = None,
    recommendations: str | None = None,
) -> bool:
    """Write session result content without touching its status (used for honest no_data sessions)."""
    conn = get_db()
    cur = conn.execute(
        "UPDATE analysis_sessions SET findings_json = ?, risk_score = ?, insights = ?, recommendations = ?, updated_at = ? WHERE id = ?",
        (
            json.dumps(findings) if findings else None,
            risk_score,
            insights,
            recommendations,
            datetime.now(timezone.utc).isoformat(),
            session_id,
        ),
    )
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok


def set_analysis_session_completed(
    session_id: str,
    findings: dict,
    risk_score: float,
    insights: str,
    recommendations: str,
    status: str = "completed",
) -> bool:
    """Finalize a session with its truthful terminal status.

    ``partial`` is used when at least one requested platform produced usable
    data but another requested platform failed or returned no data.
    """
    if status not in {"completed", "partial"}:
        raise ValueError("Invalid completed analysis session status")
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    cur = conn.execute(
        "UPDATE analysis_sessions SET status = ?, progress_json = ?, error_json = ?,"
        " findings_json = ?, risk_score = ?, insights = ?, recommendations = ?, completed_at = ?, updated_at = ? "
        "WHERE id = ? AND status NOT IN ('completed', 'partial')",
        (
            status,
            None if status == "completed" else None,
            None,
            json.dumps(findings) if findings else None,
            risk_score,
            insights,
            recommendations,
            now,
            now,
            session_id,
        ),
    )
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok


def get_analysis_sessions_for_student(
    student_id: str, limit: int = 50, offset: int = 0, analysis_type: str | None = None
) -> list:
    conn = get_db()
    if analysis_type:
        rows = conn.execute(
            "SELECT * FROM analysis_sessions WHERE student_id = ? AND analysis_type = ? "
            "ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (student_id, analysis_type, limit, offset),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM analysis_sessions WHERE student_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (student_id, limit, offset),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_analysis_session_for_student(
    session_id: str, student_id: str, analysis_type: str | None = None
) -> dict | None:
    conn = get_db()
    if analysis_type:
        row = conn.execute(
            "SELECT * FROM analysis_sessions WHERE id = ? AND student_id = ? AND analysis_type = ?",
            (session_id, student_id, analysis_type),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM analysis_sessions WHERE id = ? AND student_id = ?",
            (session_id, student_id),
        ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_analysis_session(session_id: str) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM analysis_sessions WHERE id = ?", (session_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_user_status(user_id: str, status: str) -> bool:
    """Set a user's status (e.g. approve/revoke/suspend a counsellor)."""
    conn = get_db()
    cur = conn.execute(
        "UPDATE users SET status = ? WHERE id = ?",
        (status, user_id),
    )
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok


def update_user_institution(user_id: str, institution_id: str | None) -> bool:
    conn = get_db()
    cur = conn.execute("UPDATE users SET institution_id = ? WHERE id = ?", (institution_id, user_id))
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok


def get_user_by_referral_code(code: str) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE referral_code = ?", (code.upper(),)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_users() -> list[dict]:
    conn = get_db()
    rows = conn.execute("SELECT id, email, name, role_type, status FROM users ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def accept_user_terms(user_id: str) -> bool:
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    cur = conn.execute(
        "UPDATE users SET terms_accepted_at = ? WHERE id = ? AND terms_accepted_at IS NULL",
        (now, user_id),
    )
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok


def get_students(limit: int = 200, offset: int = 0, counsellor_id: str | None = None):
    """List student accounts.

    When ``counsellor_id`` is given, scope the list to active assignments in
    the counsellor's institution. Detailed data endpoints apply the additional
    active-consent gate. Admins pass None and see all students.
    """
    conn = get_db()
    if counsellor_id:
        counsellor = conn.execute("SELECT institution_id FROM users WHERE id = ?", (counsellor_id,)).fetchone()
        c_inst = counsellor["institution_id"] if counsellor and "institution_id" in counsellor.keys() else None
        if c_inst:
            rows = conn.execute(
                "SELECT DISTINCT u.id, u.email, u.name, u.role_type, u.status, u.created_at "
                "FROM users u "
                "JOIN counsellor_student_assignments a ON a.student_id = u.id AND a.counsellor_id = ? AND a.active = 1 "
                "WHERE u.role_type = 'student' AND u.institution_id = ? AND a.institution_id = ? "
                "ORDER BY u.created_at DESC LIMIT ? OFFSET ?",
                (counsellor_id, c_inst, c_inst, limit, offset),
            ).fetchall()
        else:
            # Legacy individual accounts may have no institution. They remain
            # assignment-scoped, while one-sided institution relationships are
            # denied by the detail authorization helper.
            rows = conn.execute(
                "SELECT DISTINCT u.id, u.email, u.name, u.role_type, u.status, u.created_at "
                "FROM users u "
                "JOIN counsellor_student_assignments a ON a.student_id = u.id AND a.counsellor_id = ? AND a.active = 1 "
                "WHERE u.role_type = 'student' AND u.institution_id IS NULL AND a.institution_id IS NULL "
                "ORDER BY u.created_at DESC LIMIT ? OFFSET ?",
                (counsellor_id, limit, offset),
            ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, email, name, role_type, status, created_at FROM users "
            "WHERE role_type = 'student' ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_student_status(student_id: str, status: str) -> bool:
    conn = get_db()
    cur = conn.execute("UPDATE users SET status = ? WHERE id = ? AND role_type = 'student'", (status, student_id))
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok


def ensure_user_approved(user_id: str) -> None:
    """Approve a user if they are still pending (used by bootstrap promotion)."""
    conn = get_db()
    conn.execute(
        "UPDATE users SET status = 'approved' WHERE id = ? AND status = 'pending'",
        (user_id,),
    )
    conn.commit()
    conn.close()


def save_analysis(user_id: str, platform: str, text: str | None, prob: float, label: str):
    aid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    conn.execute(
        "INSERT INTO analyses (id, user_id, platform, text, prob, label, created_at) VALUES (?,?,?,?,?,?,?)",
        (aid, user_id, platform, text, prob, label, now),
    )
    conn.commit()
    conn.close()
    return aid


def mark_analyses_consent_withdrawn(user_id: str, at: str | None = None) -> int:
    """Stamp every analysis for a subject as ``consent withdrawn``.

    Called when consent is revoked. Analyses are *never* deleted silently —
    they stay retrievable but are flagged so the UI can show them as
    withdrawn (Delivery Brief §2.8: "marks existing analyses as 'consent
    withdrawn' (never deletes them silently — audit integrity)").
    """
    at = at or datetime.now(timezone.utc).isoformat()
    conn = get_db()
    cur = conn.execute(
        "UPDATE analyses SET consent_withdrawn_at = ? "
        "WHERE user_id = ? AND consent_withdrawn_at IS NULL",
        (at, user_id),
    )
    conn.commit()
    n = cur.rowcount
    conn.close()
    return n


def get_analyses(user_id: str, limit: int = 20):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM analyses WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_analytics(user_id: str):
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) FROM analyses WHERE user_id = ?", (user_id,)).fetchone()[0]
    neg = conn.execute("SELECT COUNT(*) FROM analyses WHERE user_id = ? AND label = 'Suicidal'", (user_id,)).fetchone()[0]
    pos = conn.execute("SELECT COUNT(*) FROM analyses WHERE user_id = ? AND label = 'Non-Suicidal'", (user_id,)).fetchone()[0]
    recent = conn.execute(
        "SELECT * FROM analyses WHERE user_id = ? ORDER BY created_at DESC LIMIT 10",
        (user_id,),
    ).fetchall()
    conn.close()
    return {
        "total_analyses": total,
        "positive_count": pos,
        "negative_count": neg,
        "history": [dict(r) for r in recent],
    }


def create_referral(counsellor_id: str, student_id: str, urgency: str, notes: str = "") -> dict:
    """Create a referral and student notification atomically. Returns full row including student_name."""
    rid = str(uuid.uuid4())
    nid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    try:
        conn.execute("BEGIN")
        conn.execute(
            "INSERT INTO referrals (id, counsellor_id, student_id, urgency, notes, status, created_at, updated_at) "
            "VALUES (?,?,?,?,?,'open',?,?)",
            (rid, counsellor_id, student_id, urgency, notes, now, now),
        )
        conn.execute(
            "INSERT INTO notifications (id, user_id, title, message, type, read, created_at) VALUES (?,?,?,?,?,0,?)",
            (nid, student_id, "New Referral", f"A referral has been created for you with {urgency} urgency.", "referral", now),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise
    row = conn.execute(
        "SELECT r.*, u.name as student_name, u.email as student_email "
        "FROM referrals r JOIN users u ON r.student_id = u.id WHERE r.id = ?",
        (rid,),
    ).fetchone()
    conn.close()
    return dict(row) if row else {"id": rid, "counsellor_id": counsellor_id, "student_id": student_id, "urgency": urgency, "notes": notes, "status": "open", "created_at": now, "updated_at": now}


def get_referrals(counsellor_id: str | None = None):
    conn = get_db()
    if counsellor_id:
        rows = conn.execute(
            "SELECT r.*, u.name as student_name, u.email as student_email "
            "FROM referrals r JOIN users u ON r.student_id = u.id "
            "WHERE r.counsellor_id = ? ORDER BY r.created_at DESC",
            (counsellor_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT r.*, u.name as student_name, u.email as student_email "
            "FROM referrals r JOIN users u ON r.student_id = u.id ORDER BY r.created_at DESC",
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_referral(referral_id: str, status: str | None = None, notes: str | None = None) -> dict | None:
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    updates = []
    params = []
    if status:
        updates.append("status = ?")
        params.append(status)
    if notes is not None:
        updates.append("notes = ?")
        params.append(notes)
    if not updates:
        # Nothing to update — return current state
        row = conn.execute(
            "SELECT r.*, u.name as student_name, u.email as student_email "
            "FROM referrals r JOIN users u ON r.student_id = u.id WHERE r.id = ?",
            (referral_id,),
        ).fetchone()
        conn.close()
        return dict(row) if row else None
    updates.append("updated_at = ?")
    params.append(now)
    params.append(referral_id)
    try:
        conn.execute("BEGIN")
        conn.execute(f"UPDATE referrals SET {', '.join(updates)} WHERE id = ?", params)
        row = conn.execute(
            "SELECT r.*, u.name as student_name, u.email as student_email "
            "FROM referrals r JOIN users u ON r.student_id = u.id WHERE r.id = ?",
            (referral_id,),
        ).fetchone()
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise
    conn.close()
    return dict(row) if row else None


# ── Appointment scheduling functions ─────────────────────────────────

APPOINTMENT_STATUSES = {"REQUESTED", "CONFIRMED", "DECLINED", "CANCELLED", "COMPLETED", "NO_SHOW"}
APPOINTMENT_ACTIVE_STATUSES = ("REQUESTED", "CONFIRMED")


def create_appointment(
    student_id: str,
    counsellor_id: str,
    created_by: str,
    title: str,
    start_at: str,
    end_at: str,
    timezone_name: str = "UTC",
    mode: str = "video",
    location: str | None = None,
    notes: str | None = None,
) -> dict:
    aid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    try:
        conn.execute("BEGIN")
        conflict = conn.execute(
            """SELECT id FROM appointments
               WHERE status IN ('REQUESTED', 'CONFIRMED')
                 AND (student_id IN (?, ?) OR counsellor_id IN (?, ?))
                 AND start_at < ? AND end_at > ? LIMIT 1""",
            (student_id, counsellor_id, student_id, counsellor_id, end_at, start_at),
        ).fetchone()
        if conflict:
            raise ValueError("The requested time conflicts with an existing appointment")
        conn.execute(
            """INSERT INTO appointments
               (id, student_id, counsellor_id, created_by, title, start_at, end_at,
                timezone, mode, location, notes, status, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,'REQUESTED',?,?)""",
            (aid, student_id, counsellor_id, created_by, title, start_at, end_at,
             timezone_name, mode, location, notes, now, now),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise
    row = conn.execute(
        """SELECT a.*, s.name AS student_name, s.email AS student_email,
                  c.name AS counsellor_name, c.email AS counsellor_email
           FROM appointments a
           JOIN users s ON s.id = a.student_id
           JOIN users c ON c.id = a.counsellor_id
           WHERE a.id = ?""",
        (aid,),
    ).fetchone()
    conn.close()
    return dict(row)


def get_appointment(appointment_id: str) -> dict | None:
    conn = get_db()
    row = conn.execute(
        """SELECT a.*, s.name AS student_name, s.email AS student_email,
                  c.name AS counsellor_name, c.email AS counsellor_email
           FROM appointments a
           JOIN users s ON s.id = a.student_id
           JOIN users c ON c.id = a.counsellor_id
           WHERE a.id = ?""",
        (appointment_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def list_appointments(user_id: str | None = None, *, status: str | None = None) -> list:
    conn = get_db()
    clauses, params = [], []
    if user_id:
        clauses.append("(a.student_id = ? OR a.counsellor_id = ?)")
        params.extend([user_id, user_id])
    if status:
        clauses.append("a.status = ?")
        params.append(status)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    rows = conn.execute(
        """SELECT a.*, s.name AS student_name, s.email AS student_email,
                  c.name AS counsellor_name, c.email AS counsellor_email
           FROM appointments a
           JOIN users s ON s.id = a.student_id
           JOIN users c ON c.id = a.counsellor_id""" + where +
        " ORDER BY a.start_at ASC, a.created_at ASC",
        params,
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def update_appointment_status(
    appointment_id: str,
    status: str,
    cancellation_reason: str | None = None,
) -> dict | None:
    if status not in APPOINTMENT_STATUSES:
        raise ValueError("Invalid appointment status")
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE appointments SET status = ?, cancellation_reason = ?, updated_at = ? WHERE id = ?",
        (status, cancellation_reason, now, appointment_id),
    )
    conn.commit()
    row = conn.execute(
        """SELECT a.*, s.name AS student_name, s.email AS student_email,
                  c.name AS counsellor_name, c.email AS counsellor_email
           FROM appointments a
           JOIN users s ON s.id = a.student_id
           JOIN users c ON c.id = a.counsellor_id
           WHERE a.id = ?""",
        (appointment_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def send_message(sender_id: str, receiver_id: str, message: str) -> dict:
    mid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    conn.execute(
        "INSERT INTO communications (id, sender_id, receiver_id, message, read, created_at) VALUES (?,?,?,?,0,?)",
        (mid, sender_id, receiver_id, message, now),
    )
    conn.commit()
    conn.close()
    return {"id": mid, "sender_id": sender_id, "receiver_id": receiver_id, "message": message, "read": False, "created_at": now}


def get_conversation(user_id: str, other_id: str, limit: int = 50):
    conn = get_db()
    rows = conn.execute(
        """SELECT * FROM communications
           WHERE (sender_id = ? AND receiver_id = ?) OR (sender_id = ? AND receiver_id = ?)
           ORDER BY created_at ASC LIMIT ?""",
        (user_id, other_id, other_id, user_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_conversations(user_id: str):
    """Get all unique conversation partners with last message."""
    conn = get_db()
    partners = conn.execute(
        """SELECT DISTINCT other_id FROM (
               SELECT receiver_id AS other_id FROM communications WHERE sender_id = ?
               UNION
               SELECT sender_id AS other_id FROM communications WHERE receiver_id = ?
           )""",
        (user_id, user_id),
    ).fetchall()
    result = []
    for row in partners:
        other_id = row["other_id"]
        last = conn.execute(
            "SELECT message, created_at FROM communications "
            "WHERE (sender_id = ? AND receiver_id = ?) OR (sender_id = ? AND receiver_id = ?) "
            "ORDER BY created_at DESC LIMIT 1",
            (user_id, other_id, other_id, user_id),
        ).fetchone()
        other = conn.execute("SELECT name, email FROM users WHERE id = ?", (other_id,)).fetchone()
        unread = conn.execute(
            "SELECT COUNT(*) FROM communications WHERE sender_id = ? AND receiver_id = ? AND read = 0",
            (other_id, user_id),
        ).fetchone()[0]
        result.append({
            "other_id": other_id,
            "other_name": other["name"] if other else "Unknown",
            "other_email": other["email"] if other else "",
            "last_message": last["message"] if last else "",
            "last_time": last["created_at"] if last else "",
            "unread": unread,
        })
    result.sort(key=lambda x: x["last_time"], reverse=True)
    conn.close()
    return result


def mark_read(message_id: str, user_id: str | None = None) -> bool:
    conn = get_db()
    if user_id:
        cur = conn.execute(
            "UPDATE communications SET read = 1 WHERE id = ? AND (sender_id = ? OR receiver_id = ?)",
            (message_id, user_id, user_id),
        )
    else:
        cur = conn.execute("UPDATE communications SET read = 1 WHERE id = ?", (message_id,))
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def mark_all_read(user_id: str, other_id: str):
    conn = get_db()
    conn.execute(
        "UPDATE communications SET read = 1 WHERE sender_id = ? AND receiver_id = ?",
        (other_id, user_id),
    )
    conn.commit()
    conn.close()


def create_notification(user_id: str, title: str, message: str, ntype: str = "general"):
    nid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    conn.execute(
        "INSERT INTO notifications (id, user_id, title, message, type, read, created_at) VALUES (?,?,?,?,?,0,?)",
        (nid, user_id, title, message, ntype, now),
    )
    conn.commit()
    conn.close()
    return nid


def get_notifications(user_id: str, limit: int = 50):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM notifications WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_notification_summary(user_id: str):
    conn = get_db()
    unread = conn.execute(
        "SELECT COUNT(*) FROM notifications WHERE user_id = ? AND read = 0",
        (user_id,),
    ).fetchone()[0]
    conn.close()
    return {"unread": unread}


def mark_notification_read(nid: str, user_id: str):
    conn = get_db()
    conn.execute(
        "UPDATE notifications SET read = 1 WHERE id = ? AND user_id = ?",
        (nid, user_id),
    )
    conn.commit()
    conn.close()


def get_counsellor_dashboard(counsellor_id: str, is_admin: bool = False):
    """Get dashboard stats for a counsellor or admin.

    For admins, returns institution-wide statistics.
    For counsellors, returns statistics scoped to their assignments.
    """
    conn = get_db()

    if is_admin:
        # Admin sees institution-wide statistics
        total_students = conn.execute(
            "SELECT COUNT(*) FROM users WHERE role_type = 'student'"
        ).fetchone()[0]
        pending = conn.execute(
            "SELECT COUNT(*) FROM users WHERE role_type = 'student' AND status = 'pending'"
        ).fetchone()[0]
        crisis_flags = conn.execute(
            "SELECT COUNT(*) FROM analyses WHERE prob >= 0.75 AND created_at >= datetime('now', '-7 days')"
        ).fetchone()[0]
        active_counsellors = conn.execute(
            "SELECT COUNT(*) FROM users WHERE role_type = 'counsellor' AND status = 'approved'"
        ).fetchone()[0]
        active_consents = get_active_consent_count()
        accepted_consents = get_accepted_consent_count()
        open_referrals = conn.execute(
            "SELECT COUNT(*) FROM referrals WHERE status = 'open'"
        ).fetchone()[0]
        recent_referrals = conn.execute(
            "SELECT r.*, u.name as student_name FROM referrals r JOIN users u ON r.student_id = u.id "
            "WHERE r.status = 'open' ORDER BY r.created_at DESC LIMIT 5"
        ).fetchall()
        recent_audit = conn.execute(
            "SELECT * FROM audit_log ORDER BY occurred_at DESC LIMIT 10"
        ).fetchall()
        conn.close()
        return {
            "total_students": total_students,
            "pending_approvals": pending,
            "active_counsellors": active_counsellors,
            "active_consents": active_consents,
            "accepted_consents": accepted_consents,
            "open_referrals": open_referrals,
            "crisis_flags_7d": crisis_flags,
            "recent_referrals": [dict(r) for r in recent_referrals],
            "recent_audit": [dict(r) for r in recent_audit],
            "is_admin": True,
        }
    else:
        # Counsellor sees their assigned students only
        total_students = conn.execute(
            "SELECT COUNT(*) FROM counsellor_student_assignments WHERE counsellor_id = ? AND active = 1",
            (counsellor_id,),
        ).fetchone()[0]
        pending = conn.execute(
            "SELECT COUNT(*) FROM users u "
            "JOIN counsellor_student_assignments a ON u.id = a.student_id "
            "WHERE a.counsellor_id = ? AND a.active = 1 AND u.status = 'pending'",
            (counsellor_id,),
        ).fetchone()[0]
        crisis_flags = conn.execute(
            "SELECT COUNT(*) FROM analyses a "
            "JOIN counsellor_student_assignments asg ON a.user_id = asg.student_id "
            "WHERE asg.counsellor_id = ? AND a.prob >= 0.75 "
            "AND a.created_at >= datetime('now', '-7 days')",
            (counsellor_id,),
        ).fetchone()[0]
        open_referrals = conn.execute(
            "SELECT COUNT(*) FROM referrals WHERE counsellor_id = ? AND status = 'open'",
            (counsellor_id,),
        ).fetchone()[0]
        recent_referrals = conn.execute(
            "SELECT r.*, u.name as student_name FROM referrals r JOIN users u ON r.student_id = u.id "
            "WHERE r.counsellor_id = ? ORDER BY r.created_at DESC LIMIT 5",
            (counsellor_id,),
        ).fetchall()
        conn.close()
        return {
            "total_students": total_students,
            "pending_approvals": pending,
            "open_referrals": open_referrals,
            "crisis_flags_7d": crisis_flags,
            "recent_referrals": [dict(r) for r in recent_referrals],
            "is_admin": False,
        }


# ── Institution functions ─────────────────────────────────────────────

def create_institution(name: str, inst_type: str = "university", created_by: str | None = None) -> dict:
    iid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    conn.execute(
        "INSERT INTO institutions (id, name, type, status, created_by, created_at, updated_at) VALUES (?,?,?,'PROVISIONING',?,?,?)",
        (iid, name, inst_type, created_by, now, now),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM institutions WHERE id = ?", (iid,)).fetchone()
    conn.close()
    return dict(row)


def update_institution(institution_id: str, **kwargs) -> dict | None:
    allowed = {
        "name", "type", "status", "retention_days", "alert_threshold", "confidence_floor",
        "minor_age_threshold", "consent_template_id", "consent_reminder_days", "consent_expiry_days",
        "settings_version",
    }
    updates = []
    params = []
    for field, value in kwargs.items():
        if field in allowed:
            updates.append(f"{field} = ?")
            params.append(value)
    if not updates:
        return get_institution_by_id(institution_id)
    updates.extend(["updated_at = ?", "settings_version = COALESCE(settings_version, 1) + 1"])
    params.append(datetime.now(timezone.utc).isoformat())
    params.append(institution_id)
    conn = get_db()
    conn.execute(f"UPDATE institutions SET {', '.join(updates)} WHERE id = ?", params)
    conn.commit()
    row = conn.execute("SELECT * FROM institutions WHERE id = ?", (institution_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_institution_by_id(inst_id: str) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM institutions WHERE id = ?", (inst_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_institutions(limit: int = 500) -> list:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM institutions ORDER BY name COLLATE NOCASE ASC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Consent functions ─────────────────────────────────────────────────

def create_consent(
    student_id: str,
    counsellor_id: str,
    recipient_email: str,
    recipient_role: str,
    platforms: list,
    mode: str = "ON_DEMAND",
) -> dict:
    cid = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    # Pending expiry and the magic-link TTL share the same window
    # (Delivery Brief §4.1–4.2: "This link expires in 30 days", and
    # institutions.consent_expiry_days defaults to 30).
    consent_expiry = timedelta(days=CONSENT_EXPIRY_DAYS)
    magic_token_expires_at = (now + consent_expiry).isoformat()
    expires_at = (now + consent_expiry).isoformat()
    now_iso = now.isoformat()
    conn = get_db()
    conn.execute(
        """INSERT INTO consents (
            id, student_id, counsellor_id, recipient_email, recipient_role,
            status, platforms_json, mode, magic_token, magic_token_expires_at,
            expires_at, created_at, updated_at, recipient_email_hash
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            cid, student_id, counsellor_id, encrypt_pii(recipient_email), recipient_role,
            "DRAFT", json.dumps(platforms), mode, None,
            magic_token_expires_at, expires_at, now_iso, now_iso,
            hash_email(recipient_email),
        ),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM consents WHERE id = ?", (cid,)).fetchone()
    conn.close()
    return _decrypt_consent_row(dict(row))


def get_consent_by_id(consent_id: str) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM consents WHERE id = ?", (consent_id,)).fetchone()
    conn.close()
    return _decrypt_consent_row(dict(row)) if row else None


def get_consent_by_token(token: str) -> dict | None:
    """Resolve a consent by its presented portal token.

    Signed tokens match via their SHA-256 hash (raw token is never persisted);
    legacy pre-M3 plain-UUID tokens match the stored ``magic_token``.
    """
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM consents WHERE signed_token_hash = ? OR magic_token = ? LIMIT 1",
        (hash_token(token), token),
    ).fetchone()
    conn.close()
    return _decrypt_consent_row(dict(row)) if row else None


def update_consent_status(consent_id: str, status: str, **kwargs) -> dict | None:
    """Update consent status and any additional keyword fields. Sets updated_at automatically."""
    now = datetime.now(timezone.utc).isoformat()
    allowed_fields = {
        "magic_token", "magic_token_expires_at", "signature_name", "signature_ip",
        "dispatched_at", "viewed_at", "accepted_at", "declined_at", "revoked_at",
        "expires_at", "platforms_json",
        "signed_token_hash", "reminders_sent", "response_ip", "response_user_agent",
        "template_version", "notes",
    }
    updates = ["status = ?", "updated_at = ?"]
    params = [status, now]
    for field, value in kwargs.items():
        if field in allowed_fields:
            updates.append(f"{field} = ?")
            params.append(value)
    params.append(consent_id)
    conn = get_db()
    conn.execute(f"UPDATE consents SET {', '.join(updates)} WHERE id = ?", params)
    conn.commit()
    row = conn.execute("SELECT * FROM consents WHERE id = ?", (consent_id,)).fetchone()
    conn.close()
    return _decrypt_consent_row(dict(row)) if row else None


def get_consents_by_counsellor(counsellor_id: str) -> list:
    conn = get_db()
    rows = conn.execute(
        "SELECT c.*, u.name as student_name, u.email as student_email "
        "FROM consents c JOIN users u ON c.student_id = u.id "
        "WHERE c.counsellor_id = ? ORDER BY c.created_at DESC",
        (counsellor_id,),
    ).fetchall()
    conn.close()
    return [_decrypt_consent_row(dict(r)) for r in rows]


def query_consents(
    counsellor_id: str,
    status: str | None = None,
    search: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list, int]:
    """Paginated consent list for a counsellor with optional filters.

    ``search`` matches (case-insensitively) against student name, student
    email, recipient email, and the student/consent ids. ``date_from`` /
    ``date_to`` are ``YYYY-MM-DD`` bounds on ``created_at`` (UTC, inclusive).
    Returns (rows, total) where rows is the requested page.
    """
    where = ["c.counsellor_id = ?"]
    params: list = [counsellor_id]
    if status:
        where.append("c.status = ?")
        params.append(status.upper())
    if search:
        term = f"%{search.strip()}%"
        where.append(
            "(LOWER(u.name) LIKE ? OR LOWER(u.email) LIKE ? OR "
            "c.recipient_email_hash = ? OR LOWER(c.student_id) LIKE ? OR "
            "LOWER(c.id) LIKE ?)"
        )
        params += [term, term, hash_email(search.strip()), term, term]
    if date_from:
        where.append("c.created_at >= ?")
        params.append(str(date_from))
    if date_to:
        where.append("c.created_at <= ?")
        params.append(f"{str(date_to)}T23:59:59.999999")
    where_sql = " AND ".join(where)
    # Latest delivery outcome for the consent's own recipient email
    # (only email_events rows carrying a real delivery outcome).
    delivery_subquery = (
        "SELECT e.event FROM email_events e "
        "WHERE e.related_type = 'consent' AND e.related_id = c.id "
        "AND e.recipient_email_hash = c.recipient_email_hash "
        "AND e.event IN ('delivered','bounced','complained') "
        "ORDER BY e.created_at DESC LIMIT 1"
    )
    delivery_at_subquery = (
        "SELECT e.created_at FROM email_events e "
        "WHERE e.related_type = 'consent' AND e.related_id = c.id "
        "AND e.recipient_email_hash = c.recipient_email_hash "
        "AND e.event IN ('delivered','bounced','complained') "
        "ORDER BY e.created_at DESC LIMIT 1"
    )

    conn = get_db()
    total = conn.execute(
        f"SELECT COUNT(*) FROM consents c JOIN users u ON c.student_id = u.id WHERE {where_sql}",
        params,
    ).fetchone()[0]
    limit = max(1, min(int(limit), 1000))
    offset = max(0, int(offset))
    rows = conn.execute(
        f"SELECT c.*, u.name as student_name, u.email as student_email, "
        f"({delivery_subquery}) AS delivery_status, "
        f"({delivery_at_subquery}) AS last_delivery_event_at "
        f"FROM consents c JOIN users u ON c.student_id = u.id "
        f"WHERE {where_sql} ORDER BY c.created_at DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    ).fetchall()
    conn.close()
    return [_decrypt_consent_row(dict(r)) for r in rows], total


def get_consent_with_student(consent_id: str) -> dict | None:
    """Single consent joined with the student's user name/email."""
    delivery_subquery = (
        "SELECT e.event FROM email_events e "
        "WHERE e.related_type = 'consent' AND e.related_id = c.id "
        "AND e.recipient_email_hash = c.recipient_email_hash "
        "AND e.event IN ('delivered','bounced','complained') "
        "ORDER BY e.created_at DESC LIMIT 1"
    )
    delivery_at_subquery = (
        "SELECT e.created_at FROM email_events e "
        "WHERE e.related_type = 'consent' AND e.related_id = c.id "
        "AND e.recipient_email_hash = c.recipient_email_hash "
        "AND e.event IN ('delivered','bounced','complained') "
        "ORDER BY e.created_at DESC LIMIT 1"
    )
    conn = get_db()
    row = conn.execute(
        "SELECT c.*, u.name as student_name, u.email as student_email, "
        f"({delivery_subquery}) AS delivery_status, "
        f"({delivery_at_subquery}) AS last_delivery_event_at "
        "FROM consents c JOIN users u ON c.student_id = u.id WHERE c.id = ?",
        (consent_id,),
    ).fetchone()
    conn.close()
    return _decrypt_consent_row(dict(row)) if row else None


def get_audit_log_for_target(target_type: str, target_id: str, limit: int = 200) -> list:
    """Immutable audit entries for a single target (e.g. a consent), newest first."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM audit_log WHERE target_type = ? AND target_id = ? "
        "ORDER BY occurred_at DESC LIMIT ?",
        (target_type, target_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_consents_by_student(student_id: str) -> list:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM consents WHERE student_id = ? ORDER BY created_at DESC",
        (student_id,),
    ).fetchall()
    conn.close()
    return [_decrypt_consent_row(dict(r)) for r in rows]


def get_all_consents(limit: int = 5000) -> list:
    """All consents, newest first (used by the reminder/expiry scheduler)."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM consents ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [_decrypt_consent_row(dict(r)) for r in rows]


def get_institution_id_for_consent(consent_id: str) -> str | None:
    """Resolve the institution a consent belongs to, via the roster student row.

    Roster students link back to their consent through ``students.current_consent_id``,
    which lets dispatch look up the institution's active template.
    """
    conn = get_db()
    row = conn.execute(
        "SELECT institution_id FROM students "
        "WHERE current_consent_id = ? AND deleted_at IS NULL LIMIT 1",
        (consent_id,),
    ).fetchone()
    conn.close()
    return row["institution_id"] if row else None


# ── Linked account functions ──────────────────────────────────────────

def create_linked_account(
    student_id: str,
    consent_id: str | None,
    platform: str,
    mode: str,
    handle: str | None,
) -> dict:
    aid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    conn.execute(
        "INSERT INTO linked_accounts (id, student_id, consent_id, platform, mode, handle, status, created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (aid, student_id, consent_id, platform, mode, handle, "active", now),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM linked_accounts WHERE id = ?", (aid,)).fetchone()
    conn.close()
    return dict(row)


def get_linked_accounts(student_id: str) -> list:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM linked_accounts WHERE student_id = ? ORDER BY created_at DESC",
        (student_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def revoke_linked_account(account_id: str, student_id: str | None = None) -> bool:
    conn = get_db()
    if student_id:
        cur = conn.execute(
            "UPDATE linked_accounts SET status = 'revoked' WHERE id = ? AND student_id = ?",
            (account_id, student_id),
        )
    else:
        cur = conn.execute(
            "UPDATE linked_accounts SET status = 'revoked' WHERE id = ?",
            (account_id,),
        )
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok


# ── Alert functions ───────────────────────────────────────────────────

def create_alert(
    student_id: str,
    counsellor_id: str,
    risk_score: float,
    threshold_at_fire: float,
    platform: str | None,
) -> dict | None:
    """Create alert unless student has an open alert with cooldown_until in the future."""
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    # Check existing open alert with active cooldown
    existing = conn.execute(
        "SELECT * FROM alerts WHERE student_id = ? AND status = 'OPEN' ORDER BY created_at DESC LIMIT 1",
        (student_id,),
    ).fetchone()
    if existing:
        existing = dict(existing)
        cooldown = existing.get("cooldown_until", "")
        if cooldown and now < cooldown:
            conn.close()
            return None

    alert_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO alerts (
            id, student_id, counsellor_id, fired_at, risk_score, threshold_at_fire,
            platform, status, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?)""",
        (alert_id, student_id, counsellor_id, now, risk_score, threshold_at_fire,
         platform, "OPEN", now),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_alerts(counsellor_id: str | None, status: str | None = None, institution_id: str | None = None) -> list:
    conn = get_db()
    clauses = []
    params = []
    if counsellor_id:
        clauses.append("a.counsellor_id = ?")
        params.append(counsellor_id)
    if institution_id:
        clauses.append("u.institution_id = ?")
        params.append(institution_id)
    if status:
        clauses.append("a.status = ?")
        params.append(status)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    rows = conn.execute(
        "SELECT a.*, u.name as student_name, u.email as student_email "
        "FROM alerts a JOIN users u ON a.student_id = u.id " + where + " ORDER BY a.fired_at DESC",
        params,
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_open_alert_for_student(student_id: str) -> dict | None:
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM alerts WHERE student_id = ? AND status = 'OPEN' ORDER BY created_at DESC LIMIT 1",
        (student_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_alert_by_id(alert_id: str) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def has_consent_relationship(student_id: str, counsellor_id: str) -> bool:
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    row = conn.execute(
        "SELECT 1 FROM consents c "
        "LEFT JOIN users consent_owner ON consent_owner.id = c.counsellor_id "
        "WHERE c.student_id = ? "
        "AND (c.counsellor_id = ? OR consent_owner.role_type = 'admin') "
        "AND c.status = 'ACCEPTED' "
        "AND (c.expires_at IS NULL OR c.expires_at = '' OR c.expires_at > ?) LIMIT 1",
        (student_id, counsellor_id, now),
    ).fetchone()
    conn.close()
    return row is not None


def has_active_assignment(counsellor_id: str, student_id: str, institution_id: str | None = None) -> bool:
    conn = get_db()
    if institution_id:
        row = conn.execute(
            "SELECT 1 FROM counsellor_student_assignments WHERE counsellor_id = ? AND student_id = ? AND institution_id = ? AND active = 1 LIMIT 1",
            (counsellor_id, student_id, institution_id),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT 1 FROM counsellor_student_assignments WHERE counsellor_id = ? AND student_id = ? AND active = 1 LIMIT 1",
            (counsellor_id, student_id),
        ).fetchone()
    conn.close()
    return row is not None


def dispose_alert(
    alert_id: str,
    disposition: str,
    reason_code: str,
    reason_note: str,
    dispositioned_by: str,
    supersedes_id: str | None = None,
) -> dict | None:
    now = datetime.now(timezone.utc)
    cooldown_until = (now + timedelta(hours=12)).isoformat()
    now_iso = now.isoformat()
    conn = get_db()
    conn.execute(
        """UPDATE alerts SET
            status = 'CLOSED',
            disposition = ?,
            disposition_reason = ?,
            disposition_note = ?,
            dispositioned_by = ?,
            dispositioned_at = ?,
            supersedes_id = ?,
            cooldown_until = ?
        WHERE id = ?""",
        (disposition, reason_code, reason_note, dispositioned_by,
         now_iso, supersedes_id, cooldown_until, alert_id),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def transition_alert(alert_id: str, status: str, actor_id: str, reason: str | None = None) -> dict | None:
    allowed = {"ACKNOWLEDGED", "ESCALATED", "IN_PROGRESS", "CLOSED", "FALSE_POSITIVE"}
    if status not in allowed:
        raise ValueError("Invalid alert workflow status")
    now = datetime.now(timezone.utc).isoformat()
    updates = ["status = ?"]
    params: list = [status]
    if status == "ACKNOWLEDGED":
        updates.extend(["acknowledged_by = ?", "acknowledged_at = ?"])
        params.extend([actor_id, now])
    elif status == "ESCALATED":
        updates.append("escalated_at = ?")
        params.append(now)
    elif status == "IN_PROGRESS":
        updates.append("in_progress_at = ?")
        params.append(now)
    elif status in ("CLOSED", "FALSE_POSITIVE"):
        updates.extend(["closed_reason = ?", "dispositioned_by = ?", "dispositioned_at = ?"])
        params.extend([reason, actor_id, now])
    params.append(alert_id)
    conn = get_db()
    conn.execute(f"UPDATE alerts SET {', '.join(updates)} WHERE id = ?", params)
    conn.commit()
    row = conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


# ── Audit log functions ───────────────────────────────────────────────

def write_audit(
    actor_id: str | None,
    actor_role: str | None,
    action: str,
    target_type: str | None,
    target_id: str | None,
    payload: dict | None = None,
    ip: str | None = None,
) -> str:
    aid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    conn.execute(
        "INSERT INTO audit_log (id, actor_id, actor_role, action, target_type, target_id, payload_json, ip, occurred_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (aid, actor_id, actor_role, action, target_type, target_id,
         json.dumps(redact_pii(payload)) if payload else None, ip, now),
    )
    conn.commit()
    conn.close()
    return aid


def get_audit_log(counsellor_id: str, limit: int = 100) -> list:
    """Return audit entries relevant to this staff member, newest first.

    The baseline schema keeps institution ownership on roster ``students``
    rows — there is no ``users.institution_id`` column, so scoping by it would
    crash with ``no such column`` (this took down the counsellor Audit Log
    page). Scope instead to what the schema guarantees:
      * entries where this user is the actor, plus
      * entries targeting students who have a consent with this counsellor, plus
      * consent-workflow entries on consents this counsellor owns.
    """
    conn = get_db()
    query = """
        SELECT * FROM audit_log
        WHERE actor_id = ?
           OR (target_type = 'user' AND target_id IN (
               SELECT c.student_id FROM consents c WHERE c.counsellor_id = ?
           ))
           OR (target_type = 'consent' AND target_id IN (
               SELECT id FROM consents WHERE counsellor_id = ?
           ))
        ORDER BY occurred_at DESC LIMIT ?
    """
    rows = conn.execute(query, (counsellor_id, counsellor_id, counsellor_id, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_audit_log(limit: int = 100, action: str | None = None) -> list:
    """Return the full audit trail (admin / compliance view), newest first."""
    conn = get_db()
    if action:
        rows = conn.execute(
            "SELECT * FROM audit_log WHERE action = ? ORDER BY occurred_at DESC LIMIT ?",
            (action, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY occurred_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Notes functions ───────────────────────────────────────────────────

def create_note(student_id: str, author_id: str, body: str) -> dict:
    nid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    conn.execute(
        "INSERT INTO notes (id, student_id, author_id, body, created_at, updated_at) VALUES (?,?,?,?,?,?)",
        (nid, student_id, author_id, body, now, now),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM notes WHERE id = ?", (nid,)).fetchone()
    conn.close()
    return dict(row)


def get_notes(student_id: str) -> list:
    conn = get_db()
    rows = conn.execute(
        "SELECT n.*, u.name as author_name FROM notes n JOIN users u ON n.author_id = u.id "
        "WHERE n.student_id = ? ORDER BY n.created_at DESC",
        (student_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Rolling risk functions ────────────────────────────────────────────

def update_rolling_risk(
    student_id: str,
    score: float,
    top_platform: str | None,
    n_posts: int,
    window_days: int = 14,
) -> dict:
    rid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    conn.execute(
        "INSERT INTO rolling_risk (id, student_id, computed_at, score, window_days, top_platform, n_posts) "
        "VALUES (?,?,?,?,?,?,?)",
        (rid, student_id, now, score, window_days, top_platform, n_posts),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM rolling_risk WHERE id = ?", (rid,)).fetchone()
    conn.close()
    return dict(row)


def get_rolling_risk(student_id: str) -> dict | None:
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM rolling_risk WHERE student_id = ? ORDER BY computed_at DESC LIMIT 1",
        (student_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_rolling_risk_history(student_id: str, limit: int = 90) -> list:
    """Return chronological rolling risk history for timeline display."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM rolling_risk WHERE student_id = ? ORDER BY computed_at ASC LIMIT ?",
        (student_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ═════════════════════════════════════════════════════════════════════
# Group functions
# ═════════════════════════════════════════════════════════════════════


def create_group(name: str, description: str, created_by: str) -> dict:
    gid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    conn.execute(
        "INSERT INTO groups (id, name, description, created_by, is_active, created_at, updated_at) "
        "VALUES (?,?,?,?,1,?,?)",
        (gid, name, description, created_by, now, now),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM groups WHERE id = ?", (gid,)).fetchone()
    conn.close()
    return dict(row)


def get_group_by_id(group_id: str) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM groups WHERE id = ? AND is_active = 1", (group_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_group(group_id: str, name: str | None = None, description: str | None = None) -> dict | None:
    now = datetime.now(timezone.utc).isoformat()
    updates = ["updated_at = ?"]
    params = [now]
    if name is not None:
        updates.append("name = ?")
        params.append(name)
    if description is not None:
        updates.append("description = ?")
        params.append(description)
    params.append(group_id)
    conn = get_db()
    conn.execute(f"UPDATE groups SET {', '.join(updates)} WHERE id = ?", params)
    conn.commit()
    row = conn.execute("SELECT * FROM groups WHERE id = ?", (group_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_group(group_id: str) -> bool:
    conn = get_db()
    cur = conn.execute("UPDATE groups SET is_active = 0 WHERE id = ?", (group_id,))
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok


def add_group_member(group_id: str, user_id: str, role: str = "member") -> dict | None:
    mid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO group_members (id, group_id, user_id, role, joined_at) VALUES (?,?,?,?,?)",
            (mid, group_id, user_id, role, now),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        return None
    row = conn.execute("SELECT * FROM group_members WHERE id = ?", (mid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def remove_group_member(group_id: str, user_id: str) -> bool:
    conn = get_db()
    cur = conn.execute(
        "DELETE FROM group_members WHERE group_id = ? AND user_id = ?",
        (group_id, user_id),
    )
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok


def get_group_members(group_id: str) -> list:
    conn = get_db()
    rows = conn.execute(
        "SELECT gm.*, u.name, u.email FROM group_members gm "
        "JOIN users u ON gm.user_id = u.id WHERE gm.group_id = ? ORDER BY gm.joined_at ASC",
        (group_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_groups_for_user(user_id: str) -> list:
    conn = get_db()
    rows = conn.execute(
        """SELECT g.*,
                  (SELECT COUNT(*) FROM group_members WHERE group_id = g.id) as member_count
           FROM groups g
           JOIN group_members gm ON gm.group_id = g.id
           WHERE gm.user_id = ? AND g.is_active = 1
           ORDER BY g.updated_at DESC""",
        (user_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def is_group_member(group_id: str, user_id: str) -> bool:
    conn = get_db()
    row = conn.execute(
        "SELECT 1 FROM group_members WHERE group_id = ? AND user_id = ?",
        (group_id, user_id),
    ).fetchone()
    conn.close()
    return row is not None


def get_group_unread_count(group_id: str, user_id: str) -> int:
    conn = get_db()
    row = conn.execute(
        """SELECT COUNT(*) FROM group_messages gm
           WHERE gm.group_id = ?
           AND gm.sender_id != ?
           AND gm.id NOT IN (
               SELECT message_id FROM group_message_read WHERE user_id = ?
           )""",
        (group_id, user_id, user_id),
    ).fetchone()
    conn.close()
    return row[0] if row else 0


def send_group_message(group_id: str, sender_id: str, message: str) -> dict:
    mid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    conn.execute(
        "INSERT INTO group_messages (id, group_id, sender_id, message, created_at) VALUES (?,?,?,?,?)",
        (mid, group_id, sender_id, message, now),
    )
    conn.commit()
    conn.close()
    return {"id": mid, "group_id": group_id, "sender_id": sender_id, "message": message, "created_at": now}


def get_group_messages(group_id: str, limit: int = 50, before_id: str | None = None) -> list:
    conn = get_db()
    if before_id:
        before = conn.execute("SELECT created_at FROM group_messages WHERE id = ?", (before_id,)).fetchone()
        if before:
            rows = conn.execute(
                """SELECT gm.*, u.name as sender_name FROM group_messages gm
                   JOIN users u ON gm.sender_id = u.id
                   WHERE gm.group_id = ? AND gm.created_at < ?
                   ORDER BY gm.created_at DESC LIMIT ?""",
                (group_id, before["created_at"], limit),
            ).fetchall()
        else:
            rows = []
    else:
        rows = conn.execute(
            """SELECT gm.*, u.name as sender_name FROM group_messages gm
               JOIN users u ON gm.sender_id = u.id
               WHERE gm.group_id = ? ORDER BY gm.created_at DESC LIMIT ?""",
            (group_id, limit),
        ).fetchall()
    conn.close()
    messages = [dict(r) for r in rows]
    messages.reverse()
    return messages


def mark_group_message_read(message_id: str, user_id: str) -> None:
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT OR IGNORE INTO group_message_read (id, message_id, user_id, read_at) VALUES (?,?,?,?)",
        (str(uuid.uuid4()), message_id, user_id, now),
    )
    conn.commit()
    conn.close()


def mark_all_group_messages_read(group_id: str, user_id: str) -> None:
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    rows = conn.execute(
        "SELECT id FROM group_messages WHERE group_id = ? AND sender_id != ?",
        (group_id, user_id),
    ).fetchall()
    for r in rows:
        conn.execute(
            "INSERT OR IGNORE INTO group_message_read (id, message_id, user_id, read_at) VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), r["id"], user_id, now),
        )
    conn.commit()
    conn.close()


# ═════════════════════════════════════════════════════════════════════
# Notification preference functions
# ═════════════════════════════════════════════════════════════════════

NOTIFICATION_TYPES = {
    "message", "group_message", "alert", "referral",
    "broadcast", "consent", "approval", "system",
}


def get_notification_preferences(user_id: str) -> list:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM notification_preferences WHERE user_id = ?",
        (user_id,),
    ).fetchall()
    conn.close()
    existing = {r["type"]: dict(r) for r in rows}
    result = []
    for ntype in sorted(NOTIFICATION_TYPES):
        if ntype in existing:
            pref = existing[ntype]
            muted = json.loads(pref.get("muted_groups") or "[]")
            result.append({"type": ntype, "enabled": bool(pref["enabled"]), "muted_groups": muted})
        else:
            result.append({"type": ntype, "enabled": True, "muted_groups": []})
    return result


def set_notification_preference(user_id: str, ntype: str, enabled: bool | None = None, muted_groups: list | None = None) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    existing = conn.execute(
        "SELECT * FROM notification_preferences WHERE user_id = ? AND type = ?",
        (user_id, ntype),
    ).fetchone()
    if existing:
        updates = []
        params = []
        if enabled is not None:
            updates.append("enabled = ?")
            params.append(1 if enabled else 0)
        if muted_groups is not None:
            updates.append("muted_groups = ?")
            params.append(json.dumps(muted_groups))
        if updates:
            params.append(user_id)
            params.append(ntype)
            conn.execute(f"UPDATE notification_preferences SET {', '.join(updates)} WHERE user_id = ? AND type = ?", params)
            conn.commit()
    else:
        muted_json = json.dumps(muted_groups if muted_groups is not None else [])
        enabled_val = 1 if enabled is None or enabled else 0
        conn.execute(
            "INSERT INTO notification_preferences (id, user_id, type, enabled, muted_groups, created_at) VALUES (?,?,?,?,?,?)",
            (str(uuid.uuid4()), user_id, ntype, enabled_val, muted_json, now),
        )
        conn.commit()
    conn.close()
    return {"type": ntype, "enabled": enabled if enabled is not None else True, "muted_groups": muted_groups or []}


def should_notify(user_id: str, ntype: str, group_id: str | None = None) -> bool:
    conn = get_db()
    row = conn.execute(
        "SELECT enabled, muted_groups FROM notification_preferences WHERE user_id = ? AND type = ?",
        (user_id, ntype),
    ).fetchone()
    conn.close()
    if not row:
        return True
    if not row["enabled"]:
        return False
    if group_id and ntype == "group_message":
        muted = json.loads(row["muted_groups"] or "[]")
        if group_id in muted:
            return False
    return True


# ═════════════════════════════════════════════════════════════════════
# Consent & roster data model (Delivery Brief §3) — M1
# ═════════════════════════════════════════════════════════════════════

# ── Students ─────────────────────────────────────────────────────────

def create_student(
    institution_id: str,
    student_id_hash: str,
    first_name_encrypted: str,
    email_encrypted: str,
    date_of_birth_encrypted: str,
    is_minor: bool,
    created_by: str,
    parent_email_encrypted: str | None = None,
    parent_first_name_encrypted: str | None = None,
    grade_level: str | None = None,
    user_id: str | None = None,
) -> dict:
    sid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    conn.execute(
        """INSERT INTO students (
            id, institution_id, student_id_hash, first_name_encrypted,
            email_encrypted, date_of_birth_encrypted, is_minor,
            parent_email_encrypted, parent_first_name_encrypted, grade_level,
            created_by, created_at, updated_at, user_id
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            sid, institution_id, student_id_hash, first_name_encrypted,
            email_encrypted, date_of_birth_encrypted, 1 if is_minor else 0,
            parent_email_encrypted, parent_first_name_encrypted, grade_level,
            created_by, now, now, user_id,
        ),
    )
    conn.commit()
    conn.close()
    return {"id": sid}


def get_student_by_id(student_id: str) -> dict | None:
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM students WHERE id = ? AND deleted_at IS NULL AND archived_at IS NULL",
        (student_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_student_by_user_id(user_id: str) -> dict | None:
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM students WHERE user_id = ? AND deleted_at IS NULL AND archived_at IS NULL LIMIT 1",
        (user_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_student_by_student_id_hash(student_id_hash: str) -> dict | None:
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM students WHERE student_id_hash = ? AND deleted_at IS NULL AND archived_at IS NULL",
        (student_id_hash,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def list_students(institution_id: str | None = None, limit: int = 200, offset: int = 0) -> list:
    conn = get_db()
    if institution_id:
        rows = conn.execute(
            "SELECT * FROM students WHERE institution_id = ? AND deleted_at IS NULL AND archived_at IS NULL "
            "ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (institution_id, limit, offset),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM students WHERE deleted_at IS NULL AND archived_at IS NULL "
            "ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_student(student_id: str, **kwargs) -> dict | None:
    """Update allowed student fields. Values are already encrypted/hashed by the caller."""
    allowed_fields = {
        "institution_id", "student_id_hash", "first_name_encrypted",
        "email_encrypted", "date_of_birth_encrypted", "is_minor",
        "parent_email_encrypted", "parent_first_name_encrypted", "grade_level",
        "current_consent_id", "deleted_at", "archived_at", "user_id",
    }
    updates = ["updated_at = ?"]
    params = [datetime.now(timezone.utc).isoformat()]
    for field, value in kwargs.items():
        if field in allowed_fields:
            updates.append(f"{field} = ?")
            params.append(value)
    if len(updates) == 1:
        return get_student_by_id(student_id)
    params.append(student_id)
    conn = get_db()
    conn.execute(f"UPDATE students SET {', '.join(updates)} WHERE id = ?", params)
    conn.commit()
    conn.close()
    return get_student_by_id(student_id)


def soft_delete_student(student_id: str) -> bool:
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    cur = conn.execute(
        "UPDATE students SET deleted_at = ?, updated_at = ? WHERE id = ? AND deleted_at IS NULL",
        (now, now, student_id),
    )
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok


def archive_student(student_id: str) -> bool:
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    cur = conn.execute(
        "UPDATE students SET archived_at = ?, updated_at = ? WHERE id = ? AND deleted_at IS NULL AND archived_at IS NULL",
        (now, now, student_id),
    )
    row = conn.execute("SELECT user_id FROM students WHERE id = ?", (student_id,)).fetchone()
    if row and row["user_id"]:
        conn.execute("UPDATE users SET status = 'archived' WHERE id = ? AND role_type = 'student'", (row["user_id"],))
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok


def set_student_current_consent(student_id: str, consent_id: str | None) -> bool:
    conn = get_db()
    cur = conn.execute(
        "UPDATE students SET current_consent_id = ?, updated_at = ? WHERE id = ?",
        (consent_id, datetime.now(timezone.utc).isoformat(), student_id),
    )
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok


# ── Consent templates ────────────────────────────────────────────────

def create_consent_template(
    version: str,
    language: str,
    institution_id: str | None = None,
    subject_email_html: str | None = None,
    parent_email_html: str | None = None,
    consent_page_html: str | None = None,
) -> dict:
    tid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    conn.execute(
        """INSERT INTO consent_templates (
            id, institution_id, version, language, subject_email_html,
            parent_email_html, consent_page_html, is_active, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (
            tid, institution_id, version, language, subject_email_html,
            parent_email_html, consent_page_html, 1, now, now,
        ),
    )
    conn.commit()
    conn.close()
    return {"id": tid}


def get_consent_template(template_id: str) -> dict | None:
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM consent_templates WHERE id = ?",
        (template_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_active_consent_template(institution_id: str | None = None) -> dict | None:
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM consent_templates WHERE is_active = 1 "
        "AND (institution_id = ? OR institution_id IS NULL) ORDER BY created_at DESC LIMIT 1",
        (institution_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def list_consent_templates(institution_id: str | None = None) -> list:
    conn = get_db()
    if institution_id:
        rows = conn.execute(
            "SELECT * FROM consent_templates WHERE institution_id = ? ORDER BY created_at DESC",
            (institution_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM consent_templates ORDER BY created_at DESC",
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def set_consent_template_active(template_id: str, is_active: bool) -> bool:
    conn = get_db()
    cur = conn.execute(
        "UPDATE consent_templates SET is_active = ?, updated_at = ? WHERE id = ?",
        (1 if is_active else 0, datetime.now(timezone.utc).isoformat(), template_id),
    )
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok


# ── Consent events (append-only audit trail) ─────────────────────────

def create_consent_event(
    consent_id: str,
    event_type: str,
    actor_type: str = "system",
    actor_id: str | None = None,
    metadata: dict | None = None,
) -> str:
    eid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    conn.execute(
        "INSERT INTO consent_events (id, consent_id, event_type, actor_type, actor_id, metadata_json, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (eid, consent_id, event_type, actor_type, actor_id,
         json.dumps(redact_pii(metadata)) if metadata else None, now),
    )
    conn.commit()
    conn.close()
    return eid


def get_consent_events(consent_id: str, limit: int = 200) -> list:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM consent_events WHERE consent_id = ? ORDER BY created_at ASC LIMIT ?",
        (consent_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Demo requests ────────────────────────────────────────────────────

DEMO_REQUEST_STATUSES = {
    "new", "contacted", "qualified", "demo_scheduled",
    "institution_provisioning", "onboarding", "closed_won", "closed_lost",
}


def create_demo_request(
    full_name: str,
    work_email: str,
    organisation: str,
    organisation_type: str = "other",
    role_title: str | None = None,
    country: str | None = None,
    student_count_range: str | None = None,
    message: str | None = None,
    heard_about_us: str | None = None,
    consent_to_contact: bool = True,
) -> dict:
    rid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    conn.execute(
        """INSERT INTO demo_requests (
            id, full_name, work_email, organisation, organisation_type,
            role_title, country, student_count_range, message, heard_about_us,
            status, consent_to_contact, created_at, updated_at, work_email_hash
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            rid, encrypt_pii(full_name), encrypt_pii(work_email), encrypt_pii(organisation), organisation_type,
            role_title, country, student_count_range, message, heard_about_us,
            "new", 1 if consent_to_contact else 0, now, now, hash_email(work_email),
        ),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM demo_requests WHERE id = ?", (rid,)).fetchone()
    conn.close()
    return _decrypt_demo_row(dict(row)) if row else {"id": rid}


def get_demo_request(demo_request_id: str) -> dict | None:
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM demo_requests WHERE id = ?",
        (demo_request_id,),
    ).fetchone()
    conn.close()
    return _decrypt_demo_row(dict(row)) if row else None


def list_demo_requests(status: str | None = None, limit: int = 100, offset: int = 0) -> list:
    delivery_subquery = (
        "SELECT e.event FROM email_events e "
        "WHERE e.related_type = 'demo_request' AND e.related_id = d.id "
        "AND e.recipient_email_hash = d.work_email_hash "
        "AND e.event IN ('delivered','bounced','complained') "
        "ORDER BY e.created_at DESC LIMIT 1"
    )
    delivery_at_subquery = (
        "SELECT e.created_at FROM email_events e "
        "WHERE e.related_type = 'demo_request' AND e.related_id = d.id "
        "AND e.recipient_email_hash = d.work_email_hash "
        "AND e.event IN ('delivered','bounced','complained') "
        "ORDER BY e.created_at DESC LIMIT 1"
    )
    conn = get_db()
    if status:
        rows = conn.execute(
            "SELECT d.*, "
            f"({delivery_subquery}) AS delivery_status, "
            f"({delivery_at_subquery}) AS last_delivery_event_at "
            "FROM demo_requests d WHERE d.status = ? "
            "ORDER BY d.created_at DESC LIMIT ? OFFSET ?",
            (status, limit, offset),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT d.*, "
            f"({delivery_subquery}) AS delivery_status, "
            f"({delivery_at_subquery}) AS last_delivery_event_at "
            "FROM demo_requests d "
            "ORDER BY d.created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    conn.close()
    return [_decrypt_demo_row(dict(r)) for r in rows]


def update_demo_request(demo_request_id: str, **kwargs) -> dict | None:
    allowed_fields = {
        "status", "assigned_to", "notes", "meeting_at", "meeting_url",
        "institution_id", "converted_by", "converted_at", "meeting_response",
        "meeting_response_token_hash", "meeting_response_note",
    }
    updates = ["updated_at = ?"]
    params = [datetime.now(timezone.utc).isoformat()]
    for field, value in kwargs.items():
        if field in allowed_fields:
            updates.append(f"{field} = ?")
            params.append(value)
    if len(updates) == 1:
        return get_demo_request(demo_request_id)
    params.append(demo_request_id)
    conn = get_db()
    conn.execute(f"UPDATE demo_requests SET {', '.join(updates)} WHERE id = ?", params)
    conn.commit()
    conn.close()
    return get_demo_request(demo_request_id)


def get_demo_request_by_response_token(token_hash: str) -> dict | None:
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM demo_requests WHERE meeting_response_token_hash = ?",
        (token_hash,),
    ).fetchone()
    conn.close()
    return _decrypt_demo_row(dict(row)) if row else None


# ── Email events (deliverability tracking) ───────────────────────────

def create_email_event(
    related_type: str,
    related_id: str | None,
    event: str,
    esp_message_id: str | None = None,
    recipient_email: str | None = None,
    metadata: dict | None = None,
) -> str:
    eid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    conn.execute(
        "INSERT INTO email_events (id, related_type, related_id, event, esp_message_id, recipient_email, recipient_email_hash, metadata_json, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (eid, related_type, related_id, event, esp_message_id,
         encrypt_pii(recipient_email) if recipient_email else None,
         hash_email(recipient_email) if recipient_email else None,
         json.dumps(metadata) if metadata else None, now),
    )
    conn.commit()
    conn.close()
    return eid


def get_email_events_by_esp_message_id(esp_message_id: str, limit: int = 50) -> list:
    """email_events rows for a given ESP message id (the ESP's ``email_id``).

    Used by the ESP webhook handler to correlate a bounce/complaint/delivery
    event back to the original send record. Ordered newest first.
    """
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM email_events WHERE esp_message_id = ? ORDER BY created_at DESC LIMIT ?",
        (esp_message_id, limit),
    ).fetchall()
    conn.close()
    return [_decrypt_email_event_row(dict(r)) for r in rows]


def enqueue_email(
    to_email: str,
    subject: str,
    body_html: str,
    related_type: str | None = None,
    related_id: str | None = None,
    metadata: dict | None = None,
) -> str:
    """Persist an outgoing email to the outbox (write-ahead, Remediation P1-1).

    The message is durably recorded (recipient encrypted at rest) before any
    transport attempt so a crash mid-send is recovered by the worker, which
    drains rows still in ``queued``. Returns the outbox row id.
    """
    eid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    conn.execute(
        "INSERT INTO email_outbox (id, to_email, to_email_hash, subject, body_html, "
        "related_type, related_id, metadata_json, status, attempts, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,'queued',0,?)",
        (eid, encrypt_pii(to_email), hash_email(to_email), subject, body_html,
         related_type, related_id, json.dumps(metadata) if metadata else None, now),
    )
    conn.commit()
    conn.close()
    return eid


def _outbox_set(outbox_id: str, **updates) -> None:
    sets = ", ".join(f"{col} = ?" for col in updates)
    conn = get_db()
    conn.execute(f"UPDATE email_outbox SET {sets} WHERE id = ?", (*updates.values(), outbox_id))
    conn.commit()
    conn.close()


def mark_email_outbox_sent(outbox_id: str, esp_message_id: str | None = None) -> None:
    """Mark an outbox row delivered (terminal state)."""
    now = datetime.now(timezone.utc).isoformat()
    _outbox_set(outbox_id, status="sent", esp_message_id=esp_message_id, sent_at=now,
                error=None, next_attempt_at=None)


def mark_email_outbox_failed(outbox_id: str, error: str, retry_at: str | None = None) -> None:
    """Mark an outbox row failed; ``retry_at`` is when the worker may retry it."""
    _outbox_set(outbox_id, status="failed", error=error, next_attempt_at=retry_at)


def mark_email_outbox_abandoned(outbox_id: str, error: str) -> None:
    """Mark an outbox row permanently abandoned (never retried, preserves history)."""
    _outbox_set(outbox_id, status="abandoned", error=error, next_attempt_at=None)


def fetch_due_email_outbox(batch_size: int = 50, max_attempts: int = 5) -> list:
    """Rows the worker may process now: queued, or failed and due for retry."""
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM email_outbox WHERE (status = 'queued' OR "
        "(status = 'failed' AND attempts < ? AND next_attempt_at <= ?)) "
        "ORDER BY created_at ASC LIMIT ?",
        (max_attempts, now, batch_size),
    ).fetchall()
    conn.close()
    return [_decrypt_outbox_row(dict(r)) for r in rows]


def bump_email_outbox_attempts(outbox_id: str) -> None:
    conn = get_db()
    conn.execute(
        "UPDATE email_outbox SET attempts = attempts + 1 WHERE id = ?",
        (outbox_id,),
    )
    conn.commit()
    conn.close()


def list_email_outbox(limit: int = 200, status: str | None = None) -> list:
    """Observability helper (tests, admin ops): most-recent outbox rows first."""
    conn = get_db()
    if status:
        rows = conn.execute(
            "SELECT * FROM email_outbox WHERE status = ? ORDER BY created_at DESC LIMIT ?",
            (status, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM email_outbox ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    conn.close()
    return [_decrypt_outbox_row(dict(r)) for r in rows]


def count_pending_email_outbox() -> int:
    """Queued + retryable failed rows awaiting (re)delivery by the worker."""
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM email_outbox WHERE status = 'queued' "
        "OR (status = 'failed' AND attempts < 5 AND next_attempt_at <= ?)",
        (now,),
    ).fetchone()
    conn.close()
    return row["n"] if row else 0


def get_email_events(related_type: str | None = None, related_id: str | None = None, limit: int = 200) -> list:
    conn = get_db()
    if related_type and related_id:
        rows = conn.execute(
            "SELECT * FROM email_events WHERE related_type = ? AND related_id = ? ORDER BY created_at DESC LIMIT ?",
            (related_type, related_id, limit),
        ).fetchall()
    elif related_type:
        rows = conn.execute(
            "SELECT * FROM email_events WHERE related_type = ? ORDER BY created_at DESC LIMIT ?",
            (related_type, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM email_events ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    conn.close()
    return [_decrypt_email_event_row(dict(r)) for r in rows]


# ── Student social accounts ─────────────────────────────────────────

_MASTODON_HANDLE_RE = re.compile(r"^@([^@]+)@([^@]+)$")


def _normalize_mastodon_handle(handle: str | None) -> tuple[str | None, str | None, str | None]:
    """Parse a Mastodon handle ``@username@instance`` and return
    ``(canonical_handle, instance, profile_url)``.

    If the handle is not a Mastodon handle, returns ``(handle, None, None)``.
    """
    if not handle:
        return None, None, None
    m = _MASTODON_HANDLE_RE.match(handle)
    if m:
        username, instance = m.group(1), m.group(2)
        canonical = f"@{username}@{instance}"
        profile_url = f"https://{instance}/@{username}"
        return canonical, instance, profile_url
    return handle, None, None


def save_social_account(
    student_id: str,
    platform: str,
    handle: str | None,
    profile_url: str | None,
    credentials: dict | None = None,
    verification_status: str = "pending",
    verified_handle: str | None = None,
    verified_profile_url: str | None = None,
) -> dict:
    """Save or update a student's social media account.

    ``credentials`` (e.g. ``{"app_password": "..."}`` for Bluesky) is
    encrypted at rest with AES-256-GCM and never returned by
    :func:`get_social_accounts`. ``platform`` is normalized to its canonical
    lowercase slug so legacy display-name rows ("Instagram") and slugs
    ("instagram") are unified.
    """
    slug = normalize_platform(platform) or platform.strip().lower()
    if not slug:
        raise ValueError("platform is required")
    # Normalize Mastodon handles: @username@instance -> derive profile_url
    normalized_handle: str | None
    instance: str | None
    derived_profile_url: str | None
    normalized_handle, instance, derived_profile_url = _normalize_mastodon_handle(handle)

    # Use the derived profile_url for Mastodon if we don't already have one
    if slug == "mastodon" and not profile_url and derived_profile_url:
        profile_url = derived_profile_url
    # Also normalize the handle stored in DB so future lookups work
    if slug == "mastodon" and normalized_handle:
        handle = normalized_handle

    if credentials in (None, {},):
        creds_blob: str | None = None
    else:
        try:
            creds_blob = encrypt_pii(json.dumps(credentials, sort_keys=True))
        except Exception:
            raise ValueError("Could not encrypt credentials securely")

    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    existing = conn.execute(
        "SELECT id FROM student_social_accounts WHERE student_id = ? AND platform = ?",
        (student_id, slug),
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE student_social_accounts SET handle = ?, profile_url = ?, updated_at = ?, active = 1, "
            "credentials_json = COALESCE(?, credentials_json), verification_status = ?, "
            "verified_handle = COALESCE(?, verified_handle), verified_profile_url = COALESCE(?, verified_profile_url) "
            "WHERE student_id = ? AND platform = ?",
            (handle, profile_url, now, creds_blob, verification_status,
             verified_handle, verified_profile_url, student_id, slug),
        )
    else:
        conn.execute(
            "INSERT INTO student_social_accounts "
            "(id, student_id, platform, handle, profile_url, credentials_json, verification_status,"
            " verified_handle, verified_profile_url, last_verified_at, analysis_status, active, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'not_run', 1, ?, ?)",
            (str(uuid.uuid4()), student_id, slug, handle, profile_url, creds_blob,
             verification_status, verified_handle, verified_profile_url, now, now, now),
        )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM student_social_accounts WHERE student_id = ? AND platform = ?",
        (student_id, slug),
    ).fetchone()
    conn.close()
    return _strip_credentials(dict(row)) if row else {"id": "", "platform": slug}


def get_social_accounts(student_id: str) -> list:
    """All social accounts for a student (credentials excluded, never leaked)."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM student_social_accounts WHERE student_id = ? AND active = 1 ORDER BY created_at DESC",
        (student_id,),
    ).fetchall()
    conn.close()
    return [_strip_credentials(dict(r)) for r in rows]


def get_social_account_credentials(student_id: str, platform: str) -> dict:
    """Decrypted credentials for a user's platform account (internal use only).

    Returns an empty dict when no credentials are stored. The caller is
    responsible for never logging or re-exposing the returned secrets.
    """
    slug = normalize_platform(platform) or platform.strip().lower()
    conn = get_db()
    row = conn.execute(
        "SELECT credentials_json FROM student_social_accounts "
        "WHERE student_id = ? AND platform = ? AND active = 1",
        (student_id, slug),
    ).fetchone()
    conn.close()
    if not row or not row["credentials_json"]:
        return {}
    blob = row["credentials_json"]
    if blob.startswith("gcm1:"):
        try:
            blob = decrypt_pii(blob)
        except Exception:
            return {}
    try:
        creds = json.loads(blob)
        return creds if isinstance(creds, dict) else {}
    except (ValueError, TypeError):
        return {}


def set_social_account_verification(
    student_id: str,
    platform: str,
    verification_status: str,
    verified_handle: str | None = None,
    verified_profile_url: str | None = None,
    analysis_status: str | None = None,
) -> dict | None:
    slug = normalize_platform(platform) or platform.strip().lower()
    updates = ["verification_status = ?", "last_verified_at = ?"]
    params: list = [verification_status, datetime.now(timezone.utc).isoformat()]
    if verified_handle is not None:
        updates.append("verified_handle = ?")
        params.append(verified_handle)
    if verified_profile_url is not None:
        updates.append("verified_profile_url = ?")
        params.append(verified_profile_url)
    if analysis_status is not None:
        updates.append("analysis_status = ?")
        params.append(analysis_status)
    params.extend([student_id, slug])
    conn = get_db()
    cur = conn.execute(
        f"UPDATE student_social_accounts SET {', '.join(updates)} "
        "WHERE student_id = ? AND platform = ?",
        params,
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM student_social_accounts WHERE student_id = ? AND platform = ?",
        (student_id, slug),
    ).fetchone()
    conn.close()
    ok = cur.rowcount > 0
    return (_strip_credentials(dict(row)) if row and ok else None)


def set_social_account_analysis_status(student_id: str, platform: str, analysis_status: str) -> dict | None:
    slug = normalize_platform(platform) or platform.strip().lower()
    conn = get_db()
    cur = conn.execute(
        "UPDATE student_social_accounts SET analysis_status = ?, updated_at = ? "
        "WHERE student_id = ? AND platform = ? AND active = 1",
        (analysis_status, datetime.now(timezone.utc).isoformat(), student_id, slug),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM student_social_accounts WHERE student_id = ? AND platform = ?",
        (student_id, slug),
    ).fetchone()
    conn.close()
    return _strip_credentials(dict(row)) if row and cur.rowcount > 0 else None


def _strip_credentials(row: dict) -> dict:
    """Drop credential secrets from any social-account row before it leaves the DB layer."""
    out = {k: v for k, v in row.items() if k != "credentials_json"}
    out["has_credentials"] = bool(row.get("credentials_json"))
    return out


def delete_social_account(student_id: str, platform: str) -> bool:
    """Delete (deactivate) a social account and wipe any stored credentials."""
    slug = normalize_platform(platform) or platform.strip().lower()
    conn = get_db()
    cur = conn.execute(
        "UPDATE student_social_accounts SET active = 0, credentials_json = NULL, updated_at = ? "
        "WHERE student_id = ? AND platform = ?",
        (datetime.now(timezone.utc).isoformat(), student_id, slug),
    )
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok


# ── Counsellor-student assignments ──────────────────────────────────

def assign_student_to_counsellor(
    counsellor_id: str,
    student_id: str,
    institution_id: str | None = None,
    assigned_by: str | None = None,
) -> dict | None:
    """Assign a student to a counsellor."""
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    existing = conn.execute(
        "SELECT id FROM counsellor_student_assignments WHERE counsellor_id = ? AND student_id = ? AND active = 1",
        (counsellor_id, student_id),
    ).fetchone()
    if existing:
        conn.close()
        return get_assignment(existing["id"])
    new_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO counsellor_student_assignments (id, counsellor_id, student_id, institution_id, assigned_by, assigned_at, active) "
        "VALUES (?, ?, ?, ?, ?, ?, 1)",
        (new_id, counsellor_id, student_id, institution_id, assigned_by, now),
    )
    conn.commit()
    conn.close()
    return get_assignment(new_id)


def unassign_student_from_counsellor(assignment_id: str) -> bool:
    """Unassign a student from a counsellor (soft delete)."""
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    cur = conn.execute(
        "UPDATE counsellor_student_assignments SET active = 0, unassigned_at = ? WHERE id = ?",
        (now, assignment_id),
    )
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok


def get_assignment(assignment_id: str) -> dict | None:
    """Get a specific assignment."""
    conn = get_db()
    row = conn.execute(
        "SELECT csa.*, u_c.name as counsellor_name, u_c.email as counsellor_email, "
        "u_s.name as student_name, u_s.email as student_email, "
        "i.name as institution_name "
        "FROM counsellor_student_assignments csa "
        "JOIN users u_c ON csa.counsellor_id = u_c.id "
        "JOIN users u_s ON csa.student_id = u_s.id "
        "LEFT JOIN institutions i ON csa.institution_id = i.id "
        "WHERE csa.id = ?",
        (assignment_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_assignments_for_counsellor(counsellor_id: str, active_only: bool = True) -> list:
    """Get all assignments for a counsellor."""
    conn = get_db()
    if active_only:
        rows = conn.execute(
            "SELECT csa.*, u_s.name as student_name, u_s.email as student_email, "
            "i.name as institution_name "
            "FROM counsellor_student_assignments csa "
            "JOIN users u_s ON csa.student_id = u_s.id "
            "LEFT JOIN institutions i ON csa.institution_id = i.id "
            "WHERE csa.counsellor_id = ? AND csa.active = 1 "
            "ORDER BY csa.assigned_at DESC",
            (counsellor_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT csa.*, u_s.name as student_name, u_s.email as student_email, "
            "i.name as institution_name "
            "FROM counsellor_student_assignments csa "
            "JOIN users u_s ON csa.student_id = u_s.id "
            "LEFT JOIN institutions i ON csa.institution_id = i.id "
            "WHERE csa.counsellor_id = ? "
            "ORDER BY csa.assigned_at DESC",
            (counsellor_id,),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_assignments_for_student(student_id: str, active_only: bool = True) -> list:
    """Get all counsellors assigned to a student."""
    conn = get_db()
    if active_only:
        rows = conn.execute(
            "SELECT csa.*, u_c.name as counsellor_name, u_c.email as counsellor_email, "
            "i.name as institution_name "
            "FROM counsellor_student_assignments csa "
            "JOIN users u_c ON csa.counsellor_id = u_c.id "
            "LEFT JOIN institutions i ON csa.institution_id = i.id "
            "WHERE csa.student_id = ? AND csa.active = 1 "
            "ORDER BY csa.assigned_at DESC",
            (student_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT csa.*, u_c.name as counsellor_name, u_c.email as counsellor_email, "
            "i.name as institution_name "
            "FROM counsellor_student_assignments csa "
            "JOIN users u_c ON csa.counsellor_id = u_c.id "
            "LEFT JOIN institutions i ON csa.institution_id = i.id "
            "WHERE csa.student_id = ? "
            "ORDER BY csa.assigned_at DESC",
            (student_id,),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def count_counsellors() -> int:
    """Count active counsellors."""
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) FROM users WHERE role_type = 'counsellor' AND status = 'approved'"
    ).fetchone()
    conn.close()
    return row[0] if row else 0


def get_active_consent_count() -> int:
    """Count active consents."""
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) FROM consents WHERE status IN ('PENDING', 'VIEWED', 'ACCEPTED') "
        "AND (expires_at IS NULL OR expires_at > ?)",
        (datetime.now(timezone.utc).isoformat(),),
    ).fetchone()
    conn.close()
    return row[0] if row else 0


def get_accepted_consent_count() -> int:
    """Count accepted consents."""
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) FROM consents WHERE status = 'ACCEPTED' "
        "AND (expires_at IS NULL OR expires_at > ?)",
        (datetime.now(timezone.utc).isoformat(),),
    ).fetchone()
    conn.close()
    return row[0] if row else 0
