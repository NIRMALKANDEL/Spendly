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
# The OS share sheet posts here without our token; the view only renders a page.
CSRF_EXEMPT_ENDPOINTS = {"receipts.share"}


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
    if request.method not in UNSAFE_METHODS or request.endpoint in CSRF_EXEMPT_ENDPOINTS:
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
    """In-memory attempt counter keyed by client IP and/or email.

    Adequate for a single-process deployment; a multi-worker setup would move
    this into Redis or the database. Limits are read from app config so tests
    and deployments can tune them.
    """

    def __init__(self, max_setting="LOGIN_MAX_ATTEMPTS", window_setting="LOGIN_WINDOW_SECONDS"):
        self.max_setting = max_setting
        self.window_setting = window_setting
        self._failures = {}
        self._lock = threading.Lock()

    def _recent(self, key, now, window):
        return [t for t in self._failures.get(key, []) if now - t < window]

    def is_blocked(self, *keys):
        cfg = current_app.config
        now = time.monotonic()
        with self._lock:
            return any(
                len(self._recent(k, now, cfg[self.window_setting])) >= cfg[self.max_setting]
                for k in keys
            )

    def record_failure(self, *keys):
        now = time.monotonic()
        window = current_app.config[self.window_setting]
        with self._lock:
            for key in keys:
                self._failures[key] = self._recent(key, now, window) + [now]

    # Counting sent emails uses the same bookkeeping as counting failures.
    record = record_failure

    def reset(self, *keys):
        with self._lock:
            for key in keys:
                self._failures.pop(key, None)

    def clear(self):
        with self._lock:
            self._failures.clear()


login_throttle = LoginThrottle()
# Password-reset / verification emails: limited per address and, more loosely, per IP.
email_throttle = LoginThrottle("EMAIL_MAX_PER_WINDOW", "LOGIN_WINDOW_SECONDS")
email_ip_throttle = LoginThrottle("EMAIL_IP_MAX_PER_WINDOW", "LOGIN_WINDOW_SECONDS")


# ------------------------------------------------------------------ #
# Headers                                                             #
# ------------------------------------------------------------------ #

CONTENT_SECURITY_POLICY = "; ".join([
    "default-src 'self'",
    # wasm-unsafe-eval only permits compiling WebAssembly (on-device receipt OCR),
    # not eval() of JavaScript.
    "script-src 'self' 'wasm-unsafe-eval'",
    "worker-src 'self'",
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
