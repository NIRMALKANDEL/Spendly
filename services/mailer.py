"""Outgoing email.

Backends (config MAIL_BACKEND):
  smtp    — real delivery (e.g. Gmail: smtp.gmail.com:587 with an app password)
  console — prints the message to the server log; the local-development default
  memory  — appends to app.extensions["mail_outbox"]; used by tests
"""

import logging
import smtplib
import ssl
from email.message import EmailMessage

from flask import current_app

log = logging.getLogger(__name__)


def mail_backend():
    cfg = current_app.config
    return cfg.get("MAIL_BACKEND") or ("smtp" if cfg.get("MAIL_SERVER") else "console")


def mail_enabled():
    """True when emails actually reach people (or are captured in dev/tests).

    In production without SMTP settings there is no way to deliver mail, so
    features that depend on it (verification, password reset) are hidden.
    """
    backend = mail_backend()
    if backend == "console":
        return not current_app.config.get("PRODUCTION")
    return True


def send_mail(to, subject, text, html=None):
    """Send one message. Returns True on success; never raises to the caller."""
    cfg = current_app.config
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg.get("MAIL_FROM") or cfg.get("MAIL_USERNAME") or "Spendly <no-reply@localhost>"
    msg["To"] = to
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")

    backend = mail_backend()
    if backend == "memory":
        current_app.extensions.setdefault("mail_outbox", []).append(msg)
        return True
    if backend == "console":
        log.warning("Email (console backend) to %s: %s\n%s", to, subject, text)
        print(f"\n--- EMAIL to {to}: {subject} ---\n{text}\n--- END EMAIL ---\n", flush=True)
        return True

    try:
        port = int(cfg.get("MAIL_PORT") or 587)
        context = ssl.create_default_context()
        if port == 465:
            server = smtplib.SMTP_SSL(cfg["MAIL_SERVER"], port, timeout=15, context=context)
        else:
            server = smtplib.SMTP(cfg["MAIL_SERVER"], port, timeout=15)
            server.starttls(context=context)
        with server:
            if cfg.get("MAIL_USERNAME"):
                server.login(cfg["MAIL_USERNAME"], cfg.get("MAIL_PASSWORD") or "")
            server.send_message(msg)
        return True
    except (OSError, smtplib.SMTPException):
        log.exception("Failed to send email to %s", to)
        return False
