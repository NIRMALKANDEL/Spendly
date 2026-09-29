"""CSRF, headers, cookies and error handling."""

from conftest import Client


def test_post_without_csrf_token_is_rejected(app):
    client = Client(app.test_client())
    resp = client.post("/register", {"name": "A", "email": "a@b.co", "password": "abc12345",
                                     "confirm_password": "abc12345"}, csrf=False)
    assert resp.status_code == 400


def test_post_with_wrong_csrf_token_is_rejected(auth_client):
    resp = auth_client.post("/transactions/new", {"csrf_token": "forged", "kind": "expense", "amount": "1",
                                                  "category": "Food", "date": "2026-09-01"})
    assert resp.status_code == 400


def test_csrf_token_is_embedded_in_forms(client):
    page = client.get("/login").data
    assert b'name="csrf_token"' in page


def test_security_headers(client):
    resp = client.get("/")
    csp = resp.headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp and "script-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert "Referrer-Policy" in resp.headers


def test_private_pages_are_not_cached(auth_client):
    assert auth_client.get("/dashboard").headers["Cache-Control"] == "no-store"


def test_session_cookie_flags(app, client):
    resp = client.raw.post("/register", data={"csrf_token": "test-csrf-token", "name": "A", "email": "a@b.co",
                                              "password": "abc12345", "confirm_password": "abc12345"})
    cookie = resp.headers.get("Set-Cookie", "")
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie


def test_custom_404_page(client):
    resp = client.get("/does-not-exist")
    assert resp.status_code == 404
    assert b"Page not found" in resp.data


def test_sql_injection_in_filters_is_harmless(auth_client):
    auth_client.add_tx(description="normal")
    for q in ["' OR 1=1 --", "\"; DROP TABLE transactions; --"]:
        assert auth_client.get("/transactions/", query_string={"q": q, "category": q}).status_code == 200
    assert b"normal" in auth_client.get("/transactions/").data


def test_invalid_sort_falls_back(auth_client):
    assert auth_client.get("/transactions/?sort=amount_cents;DROP").status_code == 200


def test_upload_size_limit(auth_client):
    import io
    big = io.BytesIO(b"a" * (3 * 1024 * 1024))
    resp = auth_client.post("/transactions/import", {"file": (big, "big.csv")}, content_type="multipart/form-data")
    assert resp.status_code in (400, 413)
