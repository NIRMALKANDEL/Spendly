import os
import secrets
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"


def _env_flag(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_secret_key():
    """Use SECRET_KEY from the environment, else a key persisted in instance/.

    Persisting the fallback key means sessions survive a dev-server restart
    without anyone having to commit a secret to the repo.
    """
    key = os.environ.get("SECRET_KEY")
    if key:
        return key
    INSTANCE_DIR.mkdir(exist_ok=True)
    key_file = INSTANCE_DIR / "secret_key"
    if key_file.exists():
        return key_file.read_text().strip()
    key = secrets.token_hex(32)
    key_file.write_text(key)
    return key


class Config:
    DATABASE = os.environ.get("DATABASE_PATH", str(INSTANCE_DIR / "spendly.db"))
    PRODUCTION = _env_flag("PRODUCTION")

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _env_flag("SESSION_COOKIE_SECURE", PRODUCTION)
    PERMANENT_SESSION_LIFETIME = timedelta(days=14)

    # Uploads (CSV import) are capped well below anything abusive.
    MAX_CONTENT_LENGTH = 2 * 1024 * 1024

    # Login throttling: this many failures inside the window locks the key out.
    LOGIN_MAX_ATTEMPTS = 5
    LOGIN_WINDOW_SECONDS = 15 * 60

    # Demo accounts are throwaway and purged after this long.
    DEMO_TTL_HOURS = 24

    # Email (password reset + verification). Unset MAIL_SERVER = print to log.
    MAIL_SERVER = os.environ.get("MAIL_SERVER")
    MAIL_PORT = os.environ.get("MAIL_PORT", "587")
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")
    MAIL_FROM = os.environ.get("MAIL_FROM")
    MAIL_BACKEND = os.environ.get("MAIL_BACKEND")

    PASSWORD_RESET_MAX_AGE = 60 * 60          # 1 hour
    EMAIL_VERIFY_MAX_AGE = 3 * 24 * 60 * 60   # 3 days
    EMAIL_RESEND_COOLDOWN_SECONDS = 60
    EMAIL_MAX_PER_WINDOW = 3      # reset/verify emails per address per 15 min
    EMAIL_IP_MAX_PER_WINDOW = 10  # ...and per client IP

    # Daily SQLite snapshots; the newest BACKUP_KEEP files are kept.
    BACKUP_DIR = os.environ.get("BACKUP_DIR", str(INSTANCE_DIR / "backups"))
    BACKUP_KEEP = int(os.environ.get("BACKUP_KEEP", "14"))
    AUTO_BACKUP = _env_flag("AUTO_BACKUP", True)

    # Receipt scanning. On-device OCR always works; set RECEIPT_AI_PROVIDER=anthropic
    # plus ANTHROPIC_API_KEY to read receipt images with Claude instead.
    RECEIPT_AI_PROVIDER = os.environ.get("RECEIPT_AI_PROVIDER", "").strip().lower()
    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
    RECEIPT_AI_MODEL = os.environ.get("RECEIPT_AI_MODEL", "claude-opus-5-5")
    SHARE_MAX_BYTES = 12 * 1024 * 1024  # images shared from payment apps

    # Shown on the privacy page so users know whom to contact.
    CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL")
