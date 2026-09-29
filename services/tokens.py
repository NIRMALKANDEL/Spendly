"""Signed, expiring tokens for email links (password reset, email verification).

Tokens are signed with SECRET_KEY, so they can't be forged, and carry a
fingerprint of the state they act on:
  - reset tokens embed part of the current password hash, so a link stops
    working once the password changes (single use);
  - verification tokens embed the email address, so a link for an old address
    can't verify a new one.
"""

import hashlib

from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

RESET = "password-reset"
VERIFY = "email-verify"


def _serializer(purpose):
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=f"spendly-{purpose}")


def _fingerprint(value):
    return hashlib.sha256(value.encode()).hexdigest()[:16]


def make_reset_token(user):
    return _serializer(RESET).dumps({"uid": user["id"], "pw": _fingerprint(user["password_hash"])})


def make_verify_token(user):
    return _serializer(VERIFY).dumps({"uid": user["id"], "email": user["email"].lower()})


def _load(purpose, token, max_age):
    try:
        return _serializer(purpose).loads(token, max_age=max_age)
    except SignatureExpired:
        return "expired"
    except BadSignature:
        return None


def check_reset_token(db, token):
    """Return (user, error). error is None, 'expired' or 'invalid'."""
    data = _load(RESET, token, current_app.config["PASSWORD_RESET_MAX_AGE"])
    if data == "expired":
        return None, "expired"
    if not isinstance(data, dict):
        return None, "invalid"
    user = db.execute("SELECT * FROM users WHERE id = ?", (data.get("uid"),)).fetchone()
    if user is None or data.get("pw") != _fingerprint(user["password_hash"]):
        return None, "invalid"
    return user, None


def check_verify_token(db, token):
    data = _load(VERIFY, token, current_app.config["EMAIL_VERIFY_MAX_AGE"])
    if data == "expired":
        return None, "expired"
    if not isinstance(data, dict):
        return None, "invalid"
    user = db.execute("SELECT * FROM users WHERE id = ?", (data.get("uid"),)).fetchone()
    if user is None or data.get("email") != user["email"].lower():
        return None, "invalid"
    return user, None


def session_fingerprint(user):
    """Stored in the session; changes whenever the password changes, which
    signs out every other device after a reset or password change."""
    return _fingerprint("session:" + user["password_hash"])
