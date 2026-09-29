"""Budgets, goals, recurring transactions, analytics pages and settings."""

from datetime import date

from conftest import PASSWORD, TODAY, Client, user_id

from database.db import get_db
from services.recurring import run_due


# ------------------------------------------------------------------ #
# Budgets                                                             #
# ------------------------------------------------------------------ #

def test_save_and_clear_budgets(app, auth_client):
    resp = auth_client.post("/budgets/", {"overall": "30000", "budget_Food": "5000", "budget_Rent": ""})
    assert resp.status_code == 302
    with app.app_context():
        db = get_db()
        assert db.execute("SELECT monthly_budget_cents FROM users").fetchone()[0] == 3000000
        assert db.execute("SELECT category, amount_cents FROM budgets").fetchall()[0]["amount_cents"] == 500000
    auth_client.post("/budgets/", {"overall": "", "budget_Food": ""})
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM budgets").fetchone()[0] == 0


def test_budget_page_shows_over_budget(auth_client):
    auth_client.post("/budgets/", {"budget_Food": "100"})
    auth_client.add_tx(amount="150", category="Food", day="2026-09-05")
    page = auth_client.get("/budgets/").data
    assert b"Over budget" in page
    dash = auth_client.get("/dashboard").data
    assert b"Over budget in Food" in dash


def test_invalid_budget_is_rejected(app, auth_client):
    auth_client.post("/budgets/", {"budget_Food": "lots"})
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM budgets").fetchone()[0] == 0


def test_budget_month_navigation_does_not_go_to_future(auth_client):
    assert auth_client.get("/budgets/?month=2030-01").status_code == 200
    assert auth_client.get("/budgets/?month=garbage").status_code == 200


# ------------------------------------------------------------------ #
# Goals                                                               #
# ------------------------------------------------------------------ #

def goal(app):
    with app.app_context():
        return get_db().execute("SELECT * FROM goals").fetchone()


def test_create_goal_and_contribute(app, auth_client):
    resp = auth_client.post("/goals/", {"name": "Laptop", "target": "90000", "saved": "10000",
                                        "target_date": "2027-03-15"})
    assert resp.status_code == 302
    g = goal(app)
    assert (g["target_cents"], g["saved_cents"]) == (9000000, 1000000)

    page = auth_client.get("/goals/").data
    assert b"Laptop" in page
    assert "₹13,334".encode() in page  # 80,000 over 6 months, rounded up

    auth_client.post(f"/goals/{g['id']}/contribute", {"amount": "5000", "action": "add"})
    assert goal(app)["saved_cents"] == 1500000
    auth_client.post(f"/goals/{g['id']}/contribute", {"amount": "2000", "action": "withdraw"})
    assert goal(app)["saved_cents"] == 1300000


def test_cannot_withdraw_more_than_saved(app, auth_client):
    auth_client.post("/goals/", {"name": "Trip", "target": "1000", "saved": "100"})
    g = goal(app)
    auth_client.post(f"/goals/{g['id']}/contribute", {"amount": "500", "action": "withdraw"})
    assert goal(app)["saved_cents"] == 10000


def test_goal_validation(auth_client):
    assert auth_client.post("/goals/", {"name": "", "target": "100"}).status_code == 400
    assert auth_client.post("/goals/", {"name": "X", "target": "0"}).status_code == 400
    assert auth_client.post("/goals/", {"name": "X", "target": "100", "target_date": "nope"}).status_code == 400


def test_edit_and_delete_goal(app, auth_client):
    auth_client.post("/goals/", {"name": "Bike", "target": "5000"})
    g = goal(app)
    auth_client.post(f"/goals/{g['id']}/edit", {"name": "E-bike", "target": "8000", "saved": "100"})
    assert goal(app)["name"] == "E-bike"
    auth_client.post(f"/goals/{g['id']}/delete")
    assert goal(app) is None


def test_goals_are_private(app, auth_client):
    auth_client.post("/goals/", {"name": "Secret", "target": "5000"})
    g = goal(app)
    other = Client(app.test_client())
    other.register(email="other@example.com")
    assert other.get(f"/goals/{g['id']}/edit").status_code == 404
    assert other.post(f"/goals/{g['id']}/contribute", {"amount": "1"}).status_code == 404
    assert other.post(f"/goals/{g['id']}/delete").status_code == 404
    assert b"Secret" not in other.get("/goals/").data


# ------------------------------------------------------------------ #
# Recurring                                                           #
# ------------------------------------------------------------------ #

def test_recurring_backfills_past_occurrences(app, auth_client):
    resp = auth_client.post("/recurring/", {"kind": "expense", "amount": "500", "category": "Bills",
                                            "date": "2026-07-31", "frequency": "monthly",
                                            "description": "Internet"})
    assert resp.status_code == 302
    with app.app_context():
        db = get_db()
        dates = [r["date"] for r in db.execute("SELECT date FROM transactions ORDER BY date")]
        rule = db.execute("SELECT * FROM recurring").fetchone()
    # Jul 31, then clamped to Aug 31, and Sep 30 is after "today" (Sep 15).
    assert dates == ["2026-07-31", "2026-08-31"]
    assert rule["next_date"] == "2026-09-30"


def test_recurring_runs_once_due(app, auth_client):
    auth_client.post("/recurring/", {"kind": "income", "amount": "1000", "category": "Salary",
                                     "date": "2026-09-20", "frequency": "weekly"})
    uid = user_id(app)
    with app.app_context():
        db = get_db()
        assert db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0
        assert run_due(db, uid, date(2026, 10, 4)) == 3  # Sep 20, 27, Oct 4
        assert run_due(db, uid, date(2026, 10, 4)) == 0  # idempotent


def test_pause_and_resume_recurring_skips_missed(app, auth_client):
    auth_client.post("/recurring/", {"kind": "expense", "amount": "100", "category": "Bills",
                                     "date": "2026-09-01", "frequency": "weekly"})
    with app.app_context():
        rule_id = get_db().execute("SELECT id FROM recurring").fetchone()["id"]
    auth_client.post(f"/recurring/{rule_id}/toggle")  # pause
    app.config["FIXED_TODAY"] = date(2026, 10, 21)  # between weekly occurrences
    auth_client.get("/dashboard")
    with app.app_context():
        before = get_db().execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    auth_client.post(f"/recurring/{rule_id}/toggle")  # resume
    auth_client.get("/dashboard")
    with app.app_context():
        after = get_db().execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        rule = get_db().execute("SELECT * FROM recurring").fetchone()
    assert after == before
    assert rule["next_date"] == "2026-10-27"
    app.config["FIXED_TODAY"] = TODAY


def test_recurring_requires_valid_frequency(auth_client):
    resp = auth_client.post("/recurring/", {"kind": "expense", "amount": "100", "category": "Bills",
                                            "date": "2026-09-01", "frequency": "hourly"})
    assert resp.status_code == 400


def test_deleting_recurring_keeps_history(app, auth_client):
    auth_client.post("/recurring/", {"kind": "expense", "amount": "100", "category": "Bills",
                                     "date": "2026-09-01", "frequency": "monthly"})
    with app.app_context():
        rule_id = get_db().execute("SELECT id FROM recurring").fetchone()["id"]
    auth_client.post(f"/recurring/{rule_id}/delete")
    with app.app_context():
        row = get_db().execute("SELECT * FROM transactions").fetchone()
    assert row is not None and row["recurring_id"] is None


# ------------------------------------------------------------------ #
# Dashboard / analytics / calculators                                 #
# ------------------------------------------------------------------ #

def test_empty_dashboard_shows_onboarding(auth_client):
    page = auth_client.get("/dashboard").data
    assert b"Let's set up your money map" in page


def test_dashboard_totals(auth_client):
    auth_client.add_tx(amount="1000", kind="income", category="Salary", day="2026-09-01")
    auth_client.add_tx(amount="250", category="Food", day="2026-09-02")
    page = auth_client.get("/dashboard").data.decode()
    assert "₹1,000" in page and "₹250" in page and "₹750" in page and "75%" in page


def test_analytics_ranges(client):
    client.post("/demo")
    client.ensure_csrf()
    for query in ["", "?range=3m", "?range=6m", "?range=ytd", "?range=all",
                  "?range=custom&start=2026-06-01&end=2026-03-01", "?range=bogus"]:
        resp = client.get("/analytics/" + query)
        assert resp.status_code == 200, query
        assert b"chart-data" in resp.data


def test_analytics_empty_state(auth_client):
    assert b"No transactions in this period" in auth_client.get("/analytics/").data


def test_calculators_are_public(client):
    resp = client.get("/calculators")
    assert resp.status_code == 200
    assert b"Loan EMI" in resp.data


# ------------------------------------------------------------------ #
# Settings                                                            #
# ------------------------------------------------------------------ #

def current_user(app):
    with app.app_context():
        return get_db().execute("SELECT * FROM users").fetchone()


def test_update_profile_and_currency(app, auth_client):
    auth_client.post("/settings/profile", {"name": "Asha R", "currency": "USD"})
    assert current_user(app)["currency"] == "USD"
    auth_client.add_tx(amount="1234567")
    assert b"$1,234,567" in auth_client.get("/transactions/").data
    auth_client.post("/settings/profile", {"name": "Asha R", "currency": "XYZ"})
    assert current_user(app)["currency"] == "USD"


def test_appearance_settings(app, auth_client):
    auth_client.post("/settings/appearance", {"theme": "ocean", "mode": "dark",
                                              "use_custom_accent": "1", "accent": "#AA3366"})
    user = current_user(app)
    assert (user["theme"], user["mode"], user["accent"]) == ("ocean", "dark", "#aa3366")
    page = auth_client.get("/dashboard").data
    assert b'data-theme="ocean"' in page and b'data-mode="dark"' in page and b"--accent: #aa3366" in page


def test_appearance_rejects_injection(app, auth_client):
    auth_client.post("/settings/appearance", {"theme": "forest", "mode": "light",
                                              "use_custom_accent": "1", "accent": "red;}body{display:none"})
    assert current_user(app)["accent"] is None


def test_mode_toggle_endpoint(app, auth_client):
    resp = auth_client.raw.post("/settings/mode", json={"mode": "dark"}, headers={"X-CSRFToken": "test-csrf-token"})
    assert resp.status_code == 200 and resp.json["ok"]
    assert current_user(app)["mode"] == "dark"
    resp = auth_client.raw.post("/settings/mode", json={"mode": "neon"}, headers={"X-CSRFToken": "test-csrf-token"})
    assert resp.status_code == 400


def test_change_password(auth_client):
    auth_client.post("/settings/password", {"current_password": "wrong", "new_password": "newpass123",
                                            "confirm_password": "newpass123"})
    auth_client.post("/settings/password", {"current_password": PASSWORD, "new_password": "newpass123",
                                            "confirm_password": "newpass123"})
    auth_client.post("/logout")
    auth_client.ensure_csrf()
    assert auth_client.login(password=PASSWORD).status_code == 401
    assert auth_client.login(password="newpass123").status_code == 302


def test_export_json(auth_client):
    auth_client.add_tx(amount="42")
    resp = auth_client.get("/settings/export.json")
    assert resp.status_code == 200
    assert resp.json["transactions"][0]["amount_cents"] == 4200
    assert "password_hash" not in resp.get_data(as_text=True)


def test_delete_account_requires_password_and_cascades(app, auth_client):
    auth_client.add_tx()
    auth_client.post("/settings/delete", {"password": "wrong"})
    assert current_user(app) is not None
    auth_client.post("/settings/delete", {"password": PASSWORD})
    assert current_user(app) is None
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0
