import os
from pathlib import Path
from dotenv import load_dotenv

from backend.secrets_manager import get_secret

load_dotenv()

# Sensitive values are resolved through backend.secrets_manager so that switching to a
# secret manager (AWS Secrets Manager, vault, ...) is a config change, not a
# code change (Delivery Brief §11).
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_ANON_KEY = get_secret("SUPABASE_ANON_KEY")
SUPABASE_SERVICE_KEY = get_secret("SUPABASE_SERVICE_KEY")

HF_TOKEN = get_secret("HF_TOKEN")
HF_REPO_ID = os.getenv("HF_REPO_ID", "kopiyodiana/mindguard-mental-roberta")
HF_CACHE_DIR = os.getenv(
    "HF_CACHE_DIR",
    str(Path(__file__).resolve().parent.parent / ".cache" / "huggingface"),
)

BASE_MODEL = "roberta-base"
MAX_LENGTH = 256

MODEL_LOCAL_DIR = str(Path(__file__).resolve().parent.parent / "mindguard_model_local")
TOKENIZER_DIR = str(Path(__file__).resolve().parent.parent / "mindguard_tokenizer")

REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = get_secret("REDDIT_CLIENT_SECRET")
YOUTUBE_API_KEY = get_secret("YOUTUBE_API_KEY")

# ── Consent, PII & email delivery (Delivery Brief §7–8) ──────────────
# AES-256-GCM key, 64 hex chars. Production MUST set this via a secret manager.
ENCRYPTION_KEY = get_secret("ENCRYPTION_KEY")

# JWT signing secret. Enforced (boot fails without it) in backend.auth.
JWT_SECRET = get_secret("JWT_SECRET")

RESEND_API_KEY = get_secret("RESEND_API_KEY")
RESEND_WEBHOOK_SECRET = get_secret("RESEND_WEBHOOK_SECRET")
WEBHOOK_TOLERANCE_SECONDS = int(os.getenv("WEBHOOK_TOLERANCE_SECONDS", "300"))
EMAIL_FROM = os.getenv("EMAIL_FROM", "MindGuard <noreply@mindguard.ai>")
DEMO_NOTIFY_EMAIL = get_secret("DEMO_NOTIFY_EMAIL")

# Public app base URL used in consent/demo email links.
APP_BASE_URL = os.getenv("APP_BASE_URL", "").rstrip("/")

# reCAPTCHA v3 site verification (Request Demo form, Brief §5.5/§13.2).
RECAPTCHA_SECRET = get_secret("RECAPTCHA_SECRET")

# Gate analysis behind accepted, non-expired, non-revoked consent.
ENFORCE_CONSENT_ANALYSIS = os.getenv("ENFORCE_CONSENT_ANALYSIS", "true").strip().lower() == "true"

CONSENT_EXPIRY_DAYS = int(os.getenv("CONSENT_EXPIRY_DAYS", "30"))
CONSENT_REMINDER_DAYS = [int(d) for d in os.getenv("CONSENT_REMINDER_DAYS", "7,14").split(",") if d.strip().isdigit()]
