import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from database.db import get_db  # noqa: E402
from services.security import login_throttle  # noqa: E402

TODAY = date(2026, 9, 15)
CSRF = "test-csrf-token"
PASSWORD = "secret123"


@pytest.fixture
def app(tmp_path):
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "test-secret",
        "DATABASE": str(tmp_path / "test.db"),
        "FIXED_TODAY": TODAY,
    })
    login_throttle.clear()
    yield app
    login_throttle.clear()


class Client:
    """Test client wrapper that sends the CSRF token on every POST."""

    def __init__(self, flask_client):
        self.raw = flask_client
        with flask_client.session_transaction() as sess:
            sess["_csrf"] = CSRF

    def get(self, *args, **kwargs):
        return self.raw.get(*args, **kwargs)

    def post(self, url, data=None, csrf=True, **kwargs):
        data = dict(data or {})
        if csrf:
            data.setdefault("csrf_token", CSRF)
        return self.raw.post(url, data=data, **kwargs)

    def ensure_csrf(self):
        with self.raw.session_transaction() as sess:
            sess["_csrf"] = CSRF

    def register(self, name="Asha Rao", email="asha@example.com", password=PASSWORD):
        resp = self.post("/register", {"name": name, "email": email, "password": password,
                                       "confirm_password": password})
        self.ensure_csrf()  # login clears the session
        return resp

    def login(self, email="asha@example.com", password=PASSWORD):
        resp = self.post("/login", {"email": email, "password": password})
        self.ensure_csrf()
        return resp

    def add_tx(self, amount="100", kind="expense", category="Food", day="2026-09-10", description=""):
        return self.post("/transactions/new", {"kind": kind, "amount": amount, "category": category,
                                               "date": day, "description": description})


@pytest.fixture
def client(app):
    return Client(app.test_client())


@pytest.fixture
def auth_client(client):
    client.register()
    return client


@pytest.fixture
def db(app):
    with app.app_context():
        yield get_db()


def user_id(app, email="asha@example.com"):
    with app.app_context():
        return get_db().execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()["id"]
