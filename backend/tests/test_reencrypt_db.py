"""Tests for the ENCRYPTION_KEY rotation script (Remediation P2-6)."""

import pytest

import backend.scripts.reencrypt_db as reencrypt
import backend.services.crypto as crypto
from backend.database import init_db


def _old_key() -> str:
    return "a" * 64


def _new_key() -> str:
    return "b" * 64


def _seed_pii(db):
    u = db.create_user("student@school.edu", "Alex", "x", role_type="student")
    inst = db.create_institution("Riverside High", "secondary")
    db.create_student(
        institution_id=inst["id"],
        student_id_hash=crypto.hash_student_id("R-1"),
        first_name_encrypted=crypto.encrypt_pii("Alex"),
        email_encrypted=crypto.encrypt_pii("alex@school.edu"),
        date_of_birth_encrypted=crypto.encrypt_pii("2002-05-05"),
        is_minor=0,
        created_by=u["id"],
    )
    db.create_consent(
        u["id"], u["id"], "alex@school.edu", "student", ["text"], mode="ON_DEMAND"
    )
    db.create_demo_request(
        "Jane Doe",
        "jane@company.com",
        "ACME",
        "school",
        role_title="Counsellor",
        country="KE",
        student_count_range="1-500",
        message="hi",
        heard_about_us="web",
        consent_to_contact=1,
    )


def test_reencrypt_rotates_all_blobs(tmp_path, monkeypatch):
    from backend import database

    db_path = tmp_path / "mindguard.db"
    old = database.DB_PATH
    database.DB_PATH = db_path
    try:
        init_db()
        monkeypatch.setattr(reencrypt, "DB_PATH", db_path)
        monkeypatch.setattr(crypto, "_ENCRYPTION_KEY_HEX", _old_key())

        _seed_pii(database)

        blob_count = 0
        for table, columns in reencrypt.PII_COLUMNS.items():
            for column in columns:
                for row in (
                    database.get_db()
                    .execute(f"SELECT {column} FROM {table}")
                    .fetchall()
                ):
                    if row[0] and row[0].startswith("gcm1:"):
                        blob_count += 1
        assert blob_count >= 4  # student PII + consent + demo fields

        monkeypatch.setenv("OLD_ENCRYPTION_KEY", _old_key())
        monkeypatch.setenv("NEW_ENCRYPTION_KEY", _new_key())
        monkeypatch.setattr("sys.argv", ["reencrypt_db.py"])

        assert reencrypt.main() == 0

        crypto._ENCRYPTION_KEY_HEX = _new_key()
        for table, columns in reencrypt.PII_COLUMNS.items():
            for column in columns:
                for row in (
                    database.get_db()
                    .execute(f"SELECT {column} FROM {table}")
                    .fetchall()
                ):
                    if row[0] and row[0].startswith("gcm1:"):
                        crypto.decrypt_pii(row[0])  # must not raise under new key
    finally:
        database.DB_PATH = old


def test_reencrypt_rejects_bad_keys(monkeypatch):
    monkeypatch.setenv("OLD_ENCRYPTION_KEY", "not-hex")
    monkeypatch.setenv("NEW_ENCRYPTION_KEY", _new_key())
    monkeypatch.setattr("sys.argv", ["reencrypt_db.py"])
    with pytest.raises(SystemExit) as exc:
        reencrypt.main()
    assert exc.value.code == 1
