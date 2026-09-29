"""CSRF protection, auth guards, login throttling and security headers."""

import functools
import hmac
import secrets
import threading
import time
from urllib.parse import urlsplit

from flask import abort, current_app, g, redirect, request, session, url_for

CSRF_SESSION_KEY = "_csrf"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


# ------------------------------------------------------------------ #
# CSRF                                                                #
# ------------------------------------------------------------------ #

def csrf_token():
    token = session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[CSRF_SESSION_KEY] = token
    return token


def csrf_protect():
    """Reject state-changing requests whose token does not match the session."""
    if request.method not in UNSAFE_METHODS:
        return
    expected = session.get(CSRF_SESSION_KEY)
    sent = request.form.get("csrf_token") or request.headers.get("X-CSRFToken")
    if not expected or not sent or not hmac.compare_digest(expected, sent):
        abort(400, description="Your session expired or the form was tampered with. Please try again.")


# ------------------------------------------------------------------ #
# Auth                                                                #
# ------------------------------------------------------------------ #

def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if g.get("user") is None:
            return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
        return view(*args, **kwargs)

    return wrapped


def safe_next_url(target, fallback):
    """Only allow same-site relative redirects (blocks //evil.com and friends)."""
    if not target or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return fallback
    parts = urlsplit(target)
    if parts.scheme or parts.netloc:
        return fallback
    return target


class LoginThrottle:
    """In-memory failed-login counter keyed by client IP and by email.

    Adequate for a single-process deployment; a multi-worker setup would move
    this into Redis or the database.
    """

    def __init__(self):
        self._failures = {}
        self._lock = threading.Lock()

    def _recent(self, key, now, window):
        return [t for t in self._failures.get(key, []) if now - t < window]

    def is_blocked(self, *keys):
        cfg = current_app.config
        now = time.monotonic()
        with self._lock:
            return any(
                len(self._recent(k, now, cfg["LOGIN_WINDOW_SECONDS"])) >= cfg["LOGIN_MAX_ATTEMPTS"]
                for k in keys
            )

    def record_failure(self, *keys):
        now = time.monotonic()
        window = current_app.config["LOGIN_WINDOW_SECONDS"]
        with self._lock:
            for key in keys:
                self._failures[key] = self._recent(key, now, window) + [now]

    def reset(self, *keys):
        with self._lock:
            for key in keys:
                self._failures.pop(key, None)

    def clear(self):
        with self._lock:
            self._failures.clear()


login_throttle = LoginThrottle()


# ------------------------------------------------------------------ #
# Headers                                                             #
# ------------------------------------------------------------------ #

CONTENT_SECURITY_POLICY = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' https://fonts.gstatic.com",
    "img-src 'self' data:",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])


def set_security_headers(response):
    headers = response.headers
    headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
    headers.setdefault("X-Content-Type-Options", "nosniff")
    headers.setdefault("X-Frame-Options", "DENY")
    headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if current_app.config.get("PRODUCTION"):
        headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if g.get("user") is not None:
        # Personal financial pages must not be cached by shared proxies.
        headers.setdefault("Cache-Control", "no-store")
    return response
