from conftest import PASSWORD, Client, user_id

from database.db import get_db


def test_landing_page_renders(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Know where your" in resp.data


def test_register_logs_user_in(client):
    resp = client.register()
    assert resp.status_code == 302
    assert resp.location.endswith("/dashboard")
    assert client.get("/dashboard").status_code == 200


def test_password_is_hashed(app, client):
    client.register()
    with app.app_context():
        row = get_db().execute("SELECT password_hash FROM users").fetchone()
    assert PASSWORD not in row["password_hash"]
    assert row["password_hash"].startswith(("scrypt:", "pbkdf2:"))


def test_register_rejects_duplicate_email_case_insensitive(client):
    client.register()
    client.post("/logout")
    client.ensure_csrf()
    resp = client.register(email="ASHA@example.com")
    assert resp.status_code == 400
    assert b"already exists" in resp.data


def test_register_validates_input(client):
    cases = [
        ({"name": "", "email": "a@b.co", "password": "abc12345", "confirm_password": "abc12345"}, b"Name is required"),
        ({"name": "A", "email": "not-an-email", "password": "abc12345", "confirm_password": "abc12345"}, b"valid email"),
        ({"name": "A", "email": "a@b.co", "password": "short1", "confirm_password": "short1"}, b"at least 8"),
        ({"name": "A", "email": "a@b.co", "password": "lettersonly", "confirm_password": "lettersonly"}, b"letter and one number"),
        ({"name": "A", "email": "a@b.co", "password": "abc12345", "confirm_password": "abc12346"}, b"do not match"),
    ]
    for data, message in cases:
        resp = client.post("/register", data)
        assert resp.status_code == 400
        assert message in resp.data


def test_login_and_logout(client):
    client.register()
    client.post("/logout")
    client.ensure_csrf()
    assert client.get("/dashboard").status_code == 302
    resp = client.login()
    assert resp.status_code == 302
    assert client.get("/dashboard").status_code == 200


def test_login_wrong_password(client):
    client.register()
    client.post("/logout")
    client.ensure_csrf()
    resp = client.login(password="wrong-pass1")
    assert resp.status_code == 401
    assert b"Incorrect email or password" in resp.data


def test_login_unknown_email_gives_same_message(client):
    resp = client.login(email="nobody@example.com")
    assert resp.status_code == 401
    assert b"Incorrect email or password" in resp.data


def test_login_is_throttled_after_repeated_failures(client):
    client.register()
    client.post("/logout")
    client.ensure_csrf()
    for _ in range(5):
        client.login(password="wrong-pass1")
    resp = client.login()  # even the right password is refused while locked
    assert resp.status_code == 429


def test_login_redirects_to_safe_next_only(client):
    client.register()
    client.post("/logout")
    client.ensure_csrf()
    resp = client.post("/login?next=/goals/", {"email": "asha@example.com", "password": PASSWORD})
    assert resp.location.endswith("/goals/")
    client.post("/logout")
    client.ensure_csrf()
    resp = client.post("/login?next=//evil.example/x", {"email": "asha@example.com", "password": PASSWORD})
    assert "evil.example" not in resp.location


def test_protected_pages_require_login(client):
    for url in ["/dashboard", "/transactions/", "/budgets/", "/goals/", "/recurring/", "/analytics/", "/settings/"]:
        resp = client.get(url)
        assert resp.status_code == 302
        assert "/login" in resp.location


def test_logout_requires_post(client):
    client.register()
    assert client.get("/logout").status_code == 405


def test_demo_creates_isolated_account_with_data(app, client):
    resp = client.post("/demo")
    assert resp.status_code == 302
    page = client.get("/dashboard")
    assert b"Demo account" in page.data
    with app.app_context():
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE is_demo = 1").fetchone()
        count = db.execute("SELECT COUNT(*) FROM transactions WHERE user_id = ?", (user["id"],)).fetchone()[0]
    assert count > 100


def test_old_demo_accounts_are_purged(app, client):
    client.post("/demo")
    with app.app_context():
        db = get_db()
        db.execute("UPDATE users SET created_at = datetime('now', '-2 days') WHERE is_demo = 1")
        db.commit()
    other = Client(app.test_client())
    other.post("/demo")
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM users WHERE is_demo = 1").fetchone()[0] == 1


def test_session_of_deleted_user_is_cleared(app, client):
    client.register()
    uid = user_id(app)
    with app.app_context():
        db = get_db()
        db.execute("DELETE FROM users WHERE id = ?", (uid,))
        db.commit()
    assert client.get("/dashboard").status_code == 302
