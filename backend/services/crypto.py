"""Cryptographic helpers for PII-at-rest encryption and signed consent tokens.

Security model (Delivery Brief §8):
- PII (name, email, DOB, parent fields) is encrypted at rest with AES-256-GCM.
- School student IDs are stored only as SHA-256 hashes.
- Consent tokens are HMAC-SHA256 signed with a 32-byte random nonce; the raw
  token is never stored — only its SHA-256 hash — so a DB leak cannot be replayed.

Key handling:
- `ENCRYPTION_KEY` (64 hex chars = 32 bytes) is authoritative in production and
  should be set via a secret manager / Railway variable, never in code.
- For local development only: if unset, a key is generated once and persisted at
  `<MINDGUARD_DB_DIR>/.encryption_key` (mode 0600). A warning is logged.
"""

import base64
import hashlib
import hmac
import logging
import os
import re
import secrets
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend.config import ENCRYPTION_KEY

logger = logging.getLogger(__name__)

_ENCRYPTION_KEY_HEX = ENCRYPTION_KEY
_KEY_FILE = (
    Path(
        os.getenv(
            "MINDGUARD_DB_DIR", str(Path(__file__).resolve().parent.parent.parent)
        )
    )
    / ".encryption_key"
)

_PII_PREFIX = "gcm1:"
_TOKEN_VERSION = "v1"


def _bytes_from_hex(hexstr: str) -> bytes | None:
    try:
        raw = bytes.fromhex(hexstr.strip())
    except ValueError:
        return None
    return raw if len(raw) == 32 else None


def _load_or_create_key() -> bytes:
    if _ENCRYPTION_KEY_HEX:
        key = _bytes_from_hex(_ENCRYPTION_KEY_HEX)
        if key is None:
            raise RuntimeError("ENCRYPTION_KEY must be 64 hex characters (32 bytes).")
        return key
    if _KEY_FILE.exists():
        key = _bytes_from_hex(_KEY_FILE.read_text().strip())
        if key:
            return key
    key = secrets.token_bytes(32)
    try:
        _KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        _KEY_FILE.write_text(key.hex(), encoding="utf-8")
        os.chmod(_KEY_FILE, 0o600)
    except OSError:
        pass
    logger.warning(
        "ENCRYPTION_KEY not set; generated a dev-only key at %s. "
        "Set ENCRYPTION_KEY in production.",
        _KEY_FILE,
    )
    return key


def _key() -> bytes:
    key = _load_or_create_key()
    if not key:
        raise RuntimeError("Encryption key could not be loaded or created.")
    return key


# ── PII encryption (AES-256-GCM) ─────────────────────────────────────


def encrypt_pii(plaintext: str) -> str:
    """Encrypt a PII string. Returns a base64 blob; not reversible without the key."""
    if plaintext is None:
        return ""
    cipher = AESGCM(_key())
    nonce = secrets.token_bytes(12)
    ct = cipher.encrypt(nonce, str(plaintext).encode("utf-8"), None)
    blob = base64.b64encode(nonce + ct).decode("ascii")
    return f"{_PII_PREFIX}{blob}"


def decrypt_pii(blob: str) -> str:
    """Decrypt a blob produced by encrypt_pii. Raises ValueError on tampering."""
    if not blob:
        return ""
    if not blob.startswith(_PII_PREFIX):
        raise ValueError("Not an encrypted PII blob.")
    raw = base64.b64decode(blob[len(_PII_PREFIX) :], validate=True)
    if len(raw) < 12 + 16:
        raise ValueError("Encrypted blob too short.")
    nonce, ct = raw[:12], raw[12:]
    cipher = AESGCM(_key())
    return cipher.decrypt(nonce, ct, None).decode("utf-8")


# ── One-way hashes (never reversible) ────────────────────────────────


def hash_student_id(student_id: str) -> str:
    """SHA-256 of the school's student ID (normalised). Stored, never the raw ID."""
    normalized = str(student_id).strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def hash_token(token: str) -> str:
    """SHA-256 of a consent token, stored at rest so a leak cannot be replayed."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_email(email: str) -> str:
    """Deterministic SHA-256 of a normalised email.

    Used for equality joins (consent ↔ delivery event) and exact-match search
    over recipient emails whose plaintext is encrypted at rest.
    """
    return hashlib.sha256(str(email or "").strip().lower().encode("utf-8")).hexdigest()


# ── PII redaction for semi-structured audit/event payloads ────────────

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_CONSENT_URL_RE = re.compile(
    r"(/consent/)(v1\.[A-Za-z0-9._\-]+|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
)
_REDACT_KEYS = {
    "signature",
    "recipient",
    "recipient_email",
    "student_email",
    "parent_email",
    "student_name",
    "parent_name",
    "recipient_name",
}


def _redact_string(value: str) -> str:
    value = _EMAIL_RE.sub(
        lambda m: (
            f"redacted-{hashlib.sha256(m.group(0).encode('utf-8')).hexdigest()[:12]}@redacted"
        ),
        value,
    )
    return _CONSENT_URL_RE.sub(r"\1[redacted]", value)


def redact_pii(obj):
    """Recursively redact PII from a JSON-serialisable object.

    Email addresses become deterministic ``redacted-<hash12>@redacted`` tokens,
    consent magic-link URLs lose their token, and well-known PII keys
    (``signature``, ``recipient_email``, ...) are collapsed to ``[redacted]``.
    """
    if isinstance(obj, dict):
        out = {}
        for key, value in obj.items():
            if key in _REDACT_KEYS and isinstance(value, (str,)):
                out[key] = (
                    _redact_string(value) if _EMAIL_RE.search(value) else "[redacted]"
                )
            else:
                out[key] = redact_pii(value)
        return out
    if isinstance(obj, list):
        return [redact_pii(item) for item in obj]
    if isinstance(obj, str):
        return _redact_string(obj)
    return obj


# ── Signed consent tokens (HMAC-SHA256 + 32-byte nonce) ──────────────


def create_signed_token(consent_id: str) -> str:
    """Create a single-use signed token for a consent record.

    Format: v1.<b64url(nonce32)>.<b64url(hmac)>.<b64url(consent_id)>
    """
    nonce = secrets.token_bytes(32)
    mac = hmac.new(_key(), consent_id.encode("utf-8") + nonce, hashlib.sha256).digest()

    def b64(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

    return f"{_TOKEN_VERSION}.{b64(nonce)}.{b64(mac)}.{b64(consent_id.encode('utf-8'))}"


def verify_signed_token(token: str, consent_id: str) -> bool:
    """Constant-time verification that the token was issued by this server for consent_id."""
    try:
        version, nonce_b64, mac_b64, cid_b64 = token.split(".")
        if version != _TOKEN_VERSION:
            return False

        def pad(value: str) -> str:
            return value + "=" * (-len(value) % 4)

        nonce = base64.urlsafe_b64decode(pad(nonce_b64))
        mac = base64.urlsafe_b64decode(pad(mac_b64))
        cid = base64.urlsafe_b64decode(pad(cid_b64)).decode("utf-8")
        if cid != consent_id or len(nonce) != 32:
            return False
        expected = hmac.new(
            _key(), consent_id.encode("utf-8") + nonce, hashlib.sha256
        ).digest()
        return hmac.compare_digest(expected, mac)
    except (ValueError, TypeError, IndexError, UnicodeDecodeError):
        return False
