"""Unit tests for pure helpers: money, dates, finance maths and analytics."""

from datetime import date

import pytest

from conftest import user_id

from database.db import get_db
from services import analytics, finance
from services.dates import add_months, months_between
from services.money import cents_to_input, format_money, parse_amount
from services.security import safe_next_url


# ------------------------------------------------------------------ #
# Money                                                               #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("raw,cents", [
    ("100", 10000), ("1,250.5", 125050), ("0.01", 1), ("₹ 2,000", 200000), (" 7.10 ", 710), ("1e3", 100000),
])
def test_parse_amount(raw, cents):
    assert parse_amount(raw) == cents


@pytest.mark.parametrize("raw", ["", None, "abc", "0", "-1", "1.001", "NaN", "Infinity", "1e30"])
def test_parse_amount_rejects(raw):
    with pytest.raises(ValueError):
        parse_amount(raw)


def test_parse_amount_allow_zero():
    assert parse_amount("0", allow_zero=True) == 0


@pytest.mark.parametrize("cents,currency,expected", [
    (12345600, "INR", "₹1,23,456"),
    (1234567890, "INR", "₹1,23,45,678.90"),
    (99900, "INR", "₹999"),
    (12345678, "USD", "$123,456.78"),
    (-50000, "EUR", "−€500"),
    (0, "GBP", "£0"),
    (500, "NPR", "रू5"),
])
def test_format_money(cents, currency, expected):
    assert format_money(cents, currency) == expected


def test_format_money_forced_decimals():
    assert format_money(100000, "INR", decimals=True) == "₹1,000.00"
    assert format_money(100050, "INR", decimals=False) == "₹1,000"


def test_cents_to_input():
    assert cents_to_input(125050) == "1250.50"
    assert cents_to_input(10000) == "100"
    assert cents_to_input(None) == ""


# ------------------------------------------------------------------ #
# Dates                                                               #
# ------------------------------------------------------------------ #

def test_add_months_clamps_and_keeps_anchor():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2026, 2, 28), 1, anchor_day=31) == date(2026, 3, 31)
    assert add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)
    assert add_months(date(2026, 11, 15), 3) == date(2027, 2, 15)
    assert add_months(date(2026, 1, 15), -2) == date(2025, 11, 15)


def test_months_between():
    assert months_between(date(2026, 9, 15), date(2027, 3, 15)) == 6
    assert months_between(date(2026, 9, 15), date(2027, 3, 14)) == 5
    assert months_between(date(2026, 9, 15), date(2026, 1, 1)) == 0


# ------------------------------------------------------------------ #
# Finance                                                             #
# ------------------------------------------------------------------ #

def test_future_value_zero_rate():
    assert finance.future_value(1000, 100, 0, 12) == 2200


def test_future_value_compound():
    # 10,000/month for 10 years at 12% p.a. (1%/month) ≈ 23,00,387
    assert finance.future_value(0, 10000, 12, 120) == pytest.approx(2300386.89, rel=1e-6)


def test_required_monthly_round_trips_with_future_value():
    monthly = finance.required_monthly_saving(500000, 50000, 7, 36)
    assert finance.future_value(50000, monthly, 7, 36) == pytest.approx(500000)


def test_required_monthly_edge_cases():
    assert finance.required_monthly_saving(1000, 2000, 5, 12) == 0
    assert finance.required_monthly_saving(1200, 0, 0, 12) == 100
    assert finance.required_monthly_saving(500, 100, 5, 0) == 400


def test_months_to_goal():
    assert finance.months_to_goal(1200, 0, 100, 0) == 12
    assert finance.months_to_goal(100, 200, 10, 5) == 0
    assert finance.months_to_goal(1000, 0, 0, 0) is None
    n = finance.months_to_goal(200000, 20000, 8000, 5)
    assert finance.future_value(20000, 8000, 5, n) >= 200000
    assert finance.future_value(20000, 8000, 5, n - 1) < 200000


def test_loan_emi():
    # Standard example: 10 lakh at 9.5% over 60 months ≈ 21,002
    assert finance.loan_emi(1000000, 9.5, 60) == pytest.approx(21001.62, abs=0.5)
    assert finance.loan_emi(1200, 0, 12) == 100
    with pytest.raises(ValueError):
        finance.loan_emi(1000, 5, 0)


def test_savings_rate():
    assert finance.savings_rate(1000, 750) == 25
    assert finance.savings_rate(0, 100) is None


# ------------------------------------------------------------------ #
# Security helpers                                                    #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("target,expected", [
    ("/goals/", "/goals/"),
    ("/transactions/?page=2", "/transactions/?page=2"),
    ("//evil.com", "/home"),
    ("https://evil.com", "/home"),
    ("/\\evil.com", "/home"),
    ("javascript:alert(1)", "/home"),
    ("", "/home"),
    (None, "/home"),
])
def test_safe_next_url(target, expected):
    assert safe_next_url(target, "/home") == expected


# ------------------------------------------------------------------ #
# Analytics                                                           #
# ------------------------------------------------------------------ #

def seed(app, rows):
    uid = user_id(app)
    with app.app_context():
        db = get_db()
        db.executemany(
            "INSERT INTO transactions (user_id, kind, amount_cents, category, date) VALUES (?, ?, ?, ?, ?)",
            [(uid, *r) for r in rows],
        )
        db.commit()
    return uid


def test_analytics_totals_and_categories(app, auth_client):
    uid = seed(app, [
        ("income", 100000, "Salary", "2026-09-01"),
        ("expense", 30000, "Food", "2026-09-02"),
        ("expense", 10000, "Food", "2026-09-03"),
        ("expense", 20000, "Rent", "2026-09-04"),
        ("expense", 99999, "Rent", "2026-08-31"),  # outside range
    ])
    with app.app_context():
        db = get_db()
        t = analytics.totals(db, uid, date(2026, 9, 1), date(2026, 9, 30))
        cats = analytics.category_totals(db, uid, date(2026, 9, 1), date(2026, 9, 30))
    assert (t["income"], t["expense"], t["net"], t["savings_rate"]) == (100000, 60000, 40000, 40)
    assert [(c["category"], c["total"]) for c in cats] == [("Food", 40000), ("Rent", 20000)]
    assert cats[0]["share"] == pytest.approx(66.67, abs=0.01)


def test_monthly_series_fills_gaps(app, auth_client):
    uid = seed(app, [("expense", 500, "Food", "2026-07-10"), ("income", 900, "Salary", "2026-09-01")])
    with app.app_context():
        series = analytics.monthly_series(get_db(), uid, ["2026-07", "2026-08", "2026-09"])
    assert [(m["key"], m["expense"], m["income"]) for m in series] == [
        ("2026-07", 500, 0), ("2026-08", 0, 0), ("2026-09", 0, 900)]
    assert series[0]["label"] == "Jul 2026"


def test_weekday_totals(app, auth_client):
    # 2026-09-14 is a Monday, 2026-09-19 a Saturday.
    uid = seed(app, [("expense", 700, "Food", "2026-09-14"), ("expense", 300, "Food", "2026-09-19")])
    with app.app_context():
        week = analytics.weekday_totals(get_db(), uid, date(2026, 9, 14), date(2026, 9, 20))
    assert week[0]["day"] == "Mon" and week[0]["total"] == 700
    assert week[5]["day"] == "Sat" and week[5]["total"] == 300
    assert week[6]["total"] == 0


def test_cumulative_daily(app, auth_client):
    uid = seed(app, [("expense", 100, "Food", "2026-09-01"), ("expense", 50, "Food", "2026-09-03")])
    with app.app_context():
        series = analytics.cumulative_daily(get_db(), uid, date(2026, 9, 1), through_day=4)
    assert series == [100, 100, 150, 150]


def test_range_insights_mentions_top_category(app, auth_client):
    uid = seed(app, [("expense", 5000, "Rent", "2026-09-01"), ("expense", 1000, "Food", "2026-09-02"),
                     ("income", 10000, "Salary", "2026-09-01")])
    with app.app_context():
        insights = analytics.range_insights(get_db(), uid, date(2026, 9, 1), date(2026, 9, 15),
                                            lambda c: format_money(c))
    texts = " ".join(i["text"] for i in insights)
    assert "Rent is your largest spending category at 83%" in texts
    assert "You kept 40% of your income" in texts
