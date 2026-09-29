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
