"""Email verification, password reset, email change, sessions, backups, legal pages."""

import re
import sqlite3
from datetime import date

from conftest import PASSWORD, Client, outbox, user_id

from app import create_app
from database.db import get_db
from services import backup


def link_in(message):
    """Extract the path of the first app link in an email's plain-text body."""
    body = message.get_body(("plain",)).get_content()
    url = re.search(r"https?://\S+", body).group(0)
    return url.split("spendly.test", 1)[1]


def user_row(app, email="asha@example.com"):
    with app.app_context():
        return get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()


def fresh_client(app):
    return Client(app.test_client())


# ------------------------------------------------------------------ #
# Email verification                                                  #
# ------------------------------------------------------------------ #

def test_register_sends_verification_email(app, client):
    client.register()
    assert len(outbox(app)) == 1
    msg = outbox(app)[0]
    assert msg["To"] == "asha@example.com"
    assert "Confirm" in msg["Subject"]
    assert user_row(app)["email_verified"] == 0
    assert b"Please confirm your email" in client.get("/dashboard").data


def test_verification_link_confirms_email(app, client):
    client.register()
    resp = client.get(link_in(outbox(app)[0]))
    assert resp.status_code == 302
    assert user_row(app)["email_verified"] == 1
    assert b"Please confirm your email" not in client.get("/dashboard").data


def test_verification_link_works_when_signed_out(app, client):
    client.register()
    link = link_in(outbox(app)[0])
    assert fresh_client(app).get(link).status_code == 302
    assert user_row(app)["email_verified"] == 1


def test_tampered_verification_link_rejected(app, client):
    client.register()
    link = link_in(outbox(app)[0])
    client.get(link[:-3] + "abc")
    assert user_row(app)["email_verified"] == 0


def test_expired_verification_link_rejected(app, client):
    client.register()
    app.config["EMAIL_VERIFY_MAX_AGE"] = -1
    client.get(link_in(outbox(app)[0]))
    assert user_row(app)["email_verified"] == 0


def test_resend_verification_has_cooldown(app, client):
    client.register()
    client.post("/verify-email/resend")
    assert len(outbox(app)) == 1  # the registration email was sent seconds ago
    with app.app_context():
        db = get_db()
        db.execute("UPDATE users SET verification_sent_at = datetime('now', '-5 minutes')")
        db.commit()
    client.post("/verify-email/resend")
    assert len(outbox(app)) == 2


def test_demo_accounts_are_verified_and_get_no_email(app, client):
    client.post("/demo")
    assert outbox(app) == []
    with app.app_context():
        assert get_db().execute("SELECT email_verified FROM users").fetchone()[0] == 1


# ------------------------------------------------------------------ #
# Forgot / reset password                                             #
# ------------------------------------------------------------------ #

def request_reset(client, email="asha@example.com"):
    return client.post("/forgot-password", {"email": email})


def registered_and_signed_out(app, client):
    client.register()
    client.post("/logout")
    client.ensure_csrf()
    outbox(app).clear()


def test_login_page_links_to_forgot_password(client):
    assert b"Forgot password?" in client.get("/login").data


def test_forgot_password_sends_reset_link(app, client):
    registered_and_signed_out(app, client)
    resp = request_reset(client)
    assert resp.status_code == 200
    assert b"Check your inbox" in resp.data
    assert len(outbox(app)) == 1
    assert "/reset-password/" in link_in(outbox(app)[0])


def test_forgot_password_does_not_reveal_unknown_emails(app, client):
    resp = request_reset(client, "nobody@example.com")
    assert resp.status_code == 200
    assert b"Check your inbox" in resp.data
    assert outbox(app) == []


def test_reset_password_flow(app, client):
    registered_and_signed_out(app, client)
    request_reset(client)
    link = link_in(outbox(app)[0])
    assert client.get(link).status_code == 200
    resp = client.post(link, {"password": "brandnew99", "confirm_password": "brandnew99"})
    assert resp.status_code == 302 and resp.location.endswith("/login")
    client.ensure_csrf()
    assert client.login(password=PASSWORD).status_code == 401
    assert client.login(password="brandnew99").status_code == 302
    assert user_row(app)["email_verified"] == 1  # the emailed link proved ownership


def test_reset_link_is_single_use(app, client):
    registered_and_signed_out(app, client)
    request_reset(client)
    link = link_in(outbox(app)[0])
    client.post(link, {"password": "brandnew99", "confirm_password": "brandnew99"})
    client.ensure_csrf()
    resp = client.post(link, {"password": "another999", "confirm_password": "another999"})
    assert resp.status_code == 302 and "/forgot-password" in resp.location
    client.ensure_csrf()
    assert client.login(password="brandnew99").status_code == 302


def test_reset_link_expires(app, client):
    registered_and_signed_out(app, client)
    request_reset(client)
    app.config["PASSWORD_RESET_MAX_AGE"] = -1
    resp = client.get(link_in(outbox(app)[0]))
    assert resp.status_code == 302 and "/forgot-password" in resp.location


def test_reset_validates_new_password(app, client):
    registered_and_signed_out(app, client)
    request_reset(client)
    link = link_in(outbox(app)[0])
    assert client.post(link, {"password": "short", "confirm_password": "short"}).status_code == 400
    assert client.post(link, {"password": "goodpass1", "confirm_password": "goodpass2"}).status_code == 400


def test_reset_emails_are_rate_limited(app, client):
    registered_and_signed_out(app, client)
    for _ in range(6):
        request_reset(client)
    # 3 emails per address per 15 minutes; the sign-up confirmation used one.
    assert len(outbox(app)) == 2


def test_reset_signs_out_other_sessions(app, client):
    client.register()
    other = fresh_client(app)
    other.login()
    assert other.get("/dashboard").status_code == 200
    outbox(app).clear()
    fresh_client(app).post("/forgot-password", {"email": "asha@example.com"})
    fresh_client(app).post(link_in(outbox(app)[0]), {"password": "brandnew99", "confirm_password": "brandnew99"})
    assert other.get("/dashboard").status_code == 302
    assert client.get("/dashboard").status_code == 302


def test_demo_accounts_cannot_request_reset(app, client):
    client.post("/demo")
    with app.app_context():
        email = get_db().execute("SELECT email FROM users").fetchone()[0]
    fresh_client(app).post("/forgot-password", {"email": email})
    assert outbox(app) == []


def test_forgot_password_unavailable_without_mail_in_production(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "prod-secret")
    app = create_app({"PRODUCTION": True, "TESTING": True, "DATABASE": str(tmp_path / "p.db"),
                      "MAIL_BACKEND": None, "MAIL_SERVER": None})
    client = app.test_client()
    assert client.get("/forgot-password").status_code == 503
    assert b"Forgot password?" not in client.get("/login").data


# ------------------------------------------------------------------ #
# Password change / email change                                      #
# ------------------------------------------------------------------ #

def test_password_change_keeps_this_session_and_ends_others(app, client):
    client.register()
    other = fresh_client(app)
    other.login()
    client.post("/settings/password", {"current_password": PASSWORD, "new_password": "newpass123",
                                       "confirm_password": "newpass123"})
    assert client.get("/dashboard").status_code == 200
    assert other.get("/dashboard").status_code == 302


def test_change_email(app, client):
    client.register()
    outbox(app).clear()
    resp = client.post("/settings/email", {"email": "new@example.com", "password": PASSWORD})
    assert resp.status_code == 302
    row = user_row(app, "new@example.com")
    assert row is not None and row["email_verified"] == 0
    assert outbox(app)[0]["To"] == "new@example.com"


def test_change_email_requires_password_and_unique_address(app, client):
    client.register()
    fresh_client(app).register(name="Bo", email="bo@example.com")
    client.post("/settings/email", {"email": "new@example.com", "password": "wrong"})
    client.post("/settings/email", {"email": "bo@example.com", "password": PASSWORD})
    client.post("/settings/email", {"email": "not-an-email", "password": PASSWORD})
    assert user_row(app)["email"] == "asha@example.com"


def test_old_verification_link_invalid_after_email_change(app, client):
    client.register()
    old_link = link_in(outbox(app)[0])
    client.post("/settings/email", {"email": "new@example.com", "password": PASSWORD})
    client.get(old_link)
    assert user_row(app, "new@example.com")["email_verified"] == 0


# ------------------------------------------------------------------ #
# Backups                                                             #
# ------------------------------------------------------------------ #

def test_create_backup_is_a_valid_copy(app, auth_client, tmp_path):
    auth_client.add_tx(amount="42")
    path = backup.create_backup(app.config["DATABASE"], tmp_path / "b", keep=5, day=date(2026, 9, 15))
    assert path.name == "spendly-2026-09-15.db"
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT amount_cents FROM transactions").fetchone()[0] == 4200
    conn.close()


def test_backups_are_pruned(app, auth_client, tmp_path):
    for day in range(1, 8):
        backup.create_backup(app.config["DATABASE"], tmp_path / "b", keep=3, day=date(2026, 9, day))
    names = [p.name for p in backup.list_backups(tmp_path / "b")]
    assert names == ["spendly-2026-09-07.db", "spendly-2026-09-06.db", "spendly-2026-09-05.db"]


def test_daily_backup_runs_once_per_day(app, auth_client, tmp_path):
    target = tmp_path / "daily"
    first = backup.ensure_daily_backup(app.config["DATABASE"], target, 14, day=date(2026, 9, 15))
    second = backup.ensure_daily_backup(app.config["DATABASE"], target, 14, day=date(2026, 9, 15))
    assert first is not None and second is None
    assert backup.ensure_daily_backup(app.config["DATABASE"], target, 14, day=date(2026, 9, 16)) is not None


def test_backup_cli_command(app, auth_client):
    result = app.test_cli_runner().invoke(args=["backup-db"])
    assert result.exit_code == 0, result.output
    assert "Backup written" in result.output
    assert backup.list_backups(app.config["BACKUP_DIR"])


# ------------------------------------------------------------------ #
# Legal pages & migration                                             #
# ------------------------------------------------------------------ #

def test_privacy_and_terms_pages(client):
    assert b"Privacy policy" in client.get("/privacy").data
    assert b"Terms of use" in client.get("/terms").data
    register = client.get("/register").data
    assert b"/privacy" in register and b"/terms" in register


def test_legal_pages_show_contact_email(app, client):
    app.config["CONTACT_EMAIL"] = "help@example.com"
    assert b"help@example.com" in client.get("/privacy").data


def test_existing_database_is_migrated(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE COLLATE NOCASE, password_hash TEXT NOT NULL,
        currency TEXT NOT NULL DEFAULT 'INR', theme TEXT NOT NULL DEFAULT 'forest',
        mode TEXT NOT NULL DEFAULT 'system', accent TEXT, monthly_budget_cents INTEGER NOT NULL DEFAULT 0,
        is_demo INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT (datetime('now')))""")
    conn.execute("INSERT INTO users (name, email, password_hash) VALUES ('Old', 'old@example.com', 'x')")
    conn.commit()
    conn.close()
    create_app({"TESTING": True, "SECRET_KEY": "k", "DATABASE": str(path)})
    conn = sqlite3.connect(path)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
    assert {"email_verified", "verification_sent_at"} <= cols
    assert conn.execute("SELECT name FROM users").fetchone()[0] == "Old"
    conn.close()


def test_user_id_helper_still_works(app, auth_client):
    assert user_id(app) == 1
