"""SMTP delivery path, exercised against a fake server."""

import smtplib

from services import mailer


class FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port, self.calls = host, port, []
        FakeSMTP.instances.append(self)

    def starttls(self, context=None):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append(("login", user, password))

    def send_message(self, msg):
        self.calls.append(("send", msg["To"], msg["Subject"]))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def smtp_app(app):
    app.config.update(MAIL_BACKEND=None, MAIL_SERVER="smtp.gmail.com", MAIL_PORT="587",
                      MAIL_USERNAME="me@gmail.com", MAIL_PASSWORD="app-password")
    return app


def test_smtp_sends_with_tls_and_login(app, monkeypatch):
    FakeSMTP.instances.clear()
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    with smtp_app(app).app_context():
        assert mailer.mail_backend() == "smtp"
        assert mailer.send_mail("user@example.com", "Hello", "Body", "<p>Body</p>") is True
    server = FakeSMTP.instances[0]
    assert (server.host, server.port) == ("smtp.gmail.com", 587)
    assert server.calls == ["starttls", ("login", "me@gmail.com", "app-password"),
                            ("send", "user@example.com", "Hello")]


def test_smtp_ssl_port(app, monkeypatch):
    FakeSMTP.instances.clear()
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    with smtp_app(app).app_context():
        app.config["MAIL_PORT"] = "465"
        assert mailer.send_mail("user@example.com", "Hi", "Body") is True
    assert FakeSMTP.instances[0].port == 465
    assert "starttls" not in FakeSMTP.instances[0].calls


def test_smtp_failure_returns_false(app, monkeypatch):
    def boom(*args, **kwargs):
        raise smtplib.SMTPAuthenticationError(535, b"bad credentials")

    monkeypatch.setattr(smtplib, "SMTP", boom)
    with smtp_app(app).app_context():
        assert mailer.send_mail("user@example.com", "Hi", "Body") is False


def test_console_backend_in_development(app, capsys):
    app.config.update(MAIL_BACKEND=None, MAIL_SERVER=None)
    with app.app_context():
        assert mailer.mail_enabled() is True
        mailer.send_mail("user@example.com", "Dev mail", "Link: http://x")
    assert "Dev mail" in capsys.readouterr().out
