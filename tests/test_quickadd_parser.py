"""One-line quick entries."""

from datetime import date

import pytest

from services.quickadd import parse_quick

TODAY = date(2026, 9, 30)  # a Wednesday


def q(text):
    fields, error = parse_quick(text, TODAY)
    assert error is None, error
    return fields


@pytest.mark.parametrize("text,amount,category,description", [
    ("250 swiggy", "250.00", "Food", "Swiggy"),
    ("lunch 180", "180.00", "Food", "Lunch"),
    ("uber 320", "320.00", "Transport", "Uber"),
    ("petrol 500", "500.00", "Transport", "Petrol"),
    ("₹1,250 blinkit", "1250.00", "Groceries", "Blinkit"),
    ("milk 60", "60.00", "Groceries", "Milk"),
    ("rs 99.50 netflix", "99.50", "Entertainment", "Netflix"),
    ("2k rent", "2000.00", "Rent", ""),
    ("300 shopping", "300.00", "Shopping", ""),
    ("medicine 240 for mom", "240.00", "Health", "Medicine mom"),
    ("electricity bill 1800", "1800.00", "Bills", "Electricity bill"),
    ("gave ramesh 500", "500.00", "Other", "Ramesh"),
])
def test_expenses(text, amount, category, description):
    f = q(text)
    assert (f["kind"], f["amount"], f["category"], f["description"]) == ("expense", amount, category, description)
    assert f["date"] == "2026-09-30"


@pytest.mark.parametrize("text,category", [
    ("salary 65000", "Salary"),
    ("+5000 freelance", "Freelance"),
    ("got 2000 birthday gift", "Gift"),
    ("received 1.5 lakh bonus", "Salary"),
    ("refund 499", "Other"),
])
def test_income(text, category):
    f = q(text)
    assert f["kind"] == "income" and f["category"] == category


def test_lakh_amount():
    assert q("received 1.5 lakh bonus")["amount"] == "150000.00"


@pytest.mark.parametrize("text,day", [
    ("lunch 180 yesterday", "2026-09-29"),
    ("dinner 400 day before yesterday", "2026-09-28"),
    ("movie 300 monday", "2026-09-28"),
    ("movie 300 wednesday", "2026-09-30"),
    ("movie 300 last wednesday", "2026-09-23"),
    ("groceries 900 on 12 sep", "2026-09-12"),
    ("groceries 900 sep 12", "2026-09-12"),
    ("tea 20 on 25/9", "2026-09-25"),
    ("gift 500 on 20 dec", "2025-12-20"),  # future date without a year -> last year
])
def test_dates(text, day):
    f = q(text)
    assert f["date"] == day
    assert "sep" not in f["description"].lower()


def test_date_numbers_are_not_the_amount():
    f = q("12 sep groceries 900")
    assert (f["amount"], f["date"]) == ("900.00", "2026-09-12")


@pytest.mark.parametrize("text", ["", "   ", "lunch", "yesterday coffee"])
def test_errors(text):
    fields, error = parse_quick(text, TODAY)
    assert fields is None and error


def test_long_input_is_truncated():
    f = q("250 " + "x" * 500)
    assert len(f["description"]) <= 200
