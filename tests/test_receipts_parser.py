"""Receipt text parser: realistic OCR output from UPI apps, SMS and shared text."""

from datetime import date

import pytest

from services.receipts import clean_name, guess_category, parse_receipt_text, receipt_from_fields

TODAY = date(2026, 9, 15)

GPAY = """
To Swiggy
₹250
Completed
12 Sep 2026, 8:41 pm
UPI transaction ID
425612345678
To: SWIGGY
swiggy.stores@icici
Banking name: Bundl Technologies
From: State Bank of India •••• 1234
Google transaction ID
CICAgICw1ZLwBw
Powered by UPI | Google Pay
"""

PHONEPE = """
Transaction Successful
08:41 pm on 12 Sep 2026
Paid to
Zomato Ltd
₹ 480
zomato-order@paytm
Transfer Details
Transaction ID
T2609122041123456789
Debited from
XXXXXXXX1234 ₹480
UTR: 425698765432
Powered by UPI · PhonePe
"""

PAYTM = """
Paid Successfully to
Uber India
₹312
12 Sep, 10:15 PM
UPI Ref No: 425611112222
From: HDFC Bank - 5678
paytm
"""

BANK_SMS = ("Rs.1,250.00 debited from A/c XX1234 on 12-09-26 to VPA bigbasket@ybl "
            "(UPI Ref No 425633334444). Not you? Call 1800111109 -SBI")

SHARED_TEXT = "Paid ₹150.00 to Ramesh Kumar via Google Pay. UPI transaction ID: 425655556666"

INCOME = """
You received ₹5,000
from Anil Sharma
14 Sep 2026
UPI transaction ID 425677778888
Google Pay
"""


def test_google_pay_screenshot():
    r = parse_receipt_text(GPAY, TODAY)
    assert r.kind == "expense"
    assert r.amount_cents == 25000
    assert r.date == "2026-09-12"
    assert r.payee == "Swiggy"
    assert r.reference == "425612345678"
    assert r.category == "Food"
    assert r.app == "Google Pay"
    assert r.found == {"amount", "date", "payee", "reference", "category"}


def test_phonepe_screenshot():
    r = parse_receipt_text(PHONEPE, TODAY)
    assert (r.kind, r.amount_cents, r.date) == ("expense", 48000, "2026-09-12")
    assert r.payee == "Zomato Ltd"
    assert r.reference == "425698765432"  # the UPI UTR, which every app shows the same way
    assert r.category == "Food"
    assert r.app == "PhonePe"


def test_paytm_screenshot_without_year():
    r = parse_receipt_text(PAYTM, TODAY)
    assert (r.amount_cents, r.date, r.payee) == (31200, "2026-09-12", "Uber India")
    assert r.reference == "425611112222"
    assert r.category == "Transport"
    assert r.app == "Paytm"


def test_bank_sms():
    r = parse_receipt_text(BANK_SMS, TODAY)
    assert (r.kind, r.amount_cents, r.date) == ("expense", 125000, "2026-09-12")
    assert r.payee == "bigbasket"
    assert r.category == "Groceries"
    assert r.reference == "425633334444"


def test_text_shared_from_app():
    r = parse_receipt_text(SHARED_TEXT, TODAY)
    assert (r.amount_cents, r.payee, r.reference) == (15000, "Ramesh Kumar", "425655556666")
    assert r.date is None  # not in the text; the form defaults to today
    assert r.to_form(TODAY)["date"] == "2026-09-15"


def test_money_received():
    r = parse_receipt_text(INCOME, TODAY)
    assert r.kind == "income"
    assert (r.amount_cents, r.payee, r.date) == (500000, "Anil Sharma", "2026-09-14")


def test_rupee_sign_misread_as_percent():
    r = parse_receipt_text("%250\nPaid to Swiggy\nCompleted", TODAY)
    assert r.amount_cents == 25000


def test_rupee_sign_misread_as_digit_is_corrected_by_details():
    # Headline "₹250" OCR'd as "2250", but the details section repeats "₹250".
    text = "Paid to Swiggy\n2250\nCompleted\nAmount ₹250.00"
    assert parse_receipt_text(text, TODAY).amount_cents == 25000


def test_rupee_sign_dropped_entirely():
    r = parse_receipt_text("Paid to Chai Point\n85\nPayment successful\n13 Sep 2026", TODAY)
    assert r.amount_cents == 8500
    assert r.category == "Food"


def test_ids_phone_numbers_and_years_are_not_amounts():
    text = "Paid to 9876543210\nUPI transaction ID\n425612345678\n2026\nCompleted"
    assert parse_receipt_text(text, TODAY).amount_cents is None


def test_indian_digit_grouping():
    assert parse_receipt_text("Paid to Landlord\n₹1,25,000", TODAY).amount_cents == 12500000


@pytest.mark.parametrize("text,expected", [
    ("12 September 2026", "2026-09-12"),
    ("Sep 12, 2026", "2026-09-12"),
    ("12/09/2026", "2026-09-12"),
    ("2026-09-12", "2026-09-12"),
    ("3rd Sep 2026", "2026-09-03"),
    ("20 Dec", "2025-12-20"),  # no year and in the future -> last year
    ("Yesterday, 9:10 pm", "2026-09-14"),
    ("31 Feb 2026", None),
    ("12 Oct 2026", None),  # future dates are rejected
])
def test_date_formats(text, expected):
    r = parse_receipt_text("Paid to X\n₹10\n" + text, TODAY)
    assert r.date == expected


@pytest.mark.parametrize("payee,category", [
    ("Blinkit", "Groceries"), ("Rapido", "Transport"), ("Airtel Prepaid", "Bills"),
    ("Apollo Pharmacy", "Health"), ("Netflix", "Entertainment"), ("Myntra", "Shopping"),
    ("IRCTC", "Travel"), ("Udemy", "Education"), ("Ramesh Kumar", "Other"),
])
def test_category_guesses(payee, category):
    assert guess_category("expense", payee, "") == category


def test_category_keywords_match_whole_words():
    assert guess_category("expense", "Olathe Traders", "") == "Other"  # not "ola"
    assert guess_category("income", "Acme Payroll", "") == "Salary"


def test_clean_name():
    assert clean_name("SWIGGY") == "Swiggy"
    assert clean_name("ramesh.k@okaxis") == "ramesh k"
    assert clean_name("Completed") is None
    assert clean_name("₹250") is None
    assert clean_name("Mr. Anil Sharma") == "Anil Sharma"


def test_empty_and_garbage_input():
    r = parse_receipt_text("", TODAY)
    assert r.amount_cents is None and r.found == set()
    r = parse_receipt_text("lorem ipsum dolor", TODAY)
    assert r.amount_cents is None and r.category == "Other"
    assert parse_receipt_text("x" * 100_000, TODAY).amount_cents is None


def test_receipt_from_fields_validates_everything():
    r = receipt_from_fields({"type": "expense", "amount": "480.50", "date": "2026-09-12",
                             "payee": "Zomato", "reference": "4256-1234-5678", "category": "Food"}, TODAY)
    assert (r.amount_cents, r.date, r.payee, r.reference, r.category) == (48050, "2026-09-12", "Zomato",
                                                                          "425612345678", "Food")
    bad = receipt_from_fields({"amount": "-5", "date": "2099-01-01", "category": "Hacking",
                               "payee": "<script>"}, TODAY)
    assert bad.amount_cents is None and bad.date is None and bad.category == "Other"


# Real Tesseract output captured from mock GPay / PhonePe / Paytm screenshots
# (two passes, sparse-text mode) — regression tests for OCR quirks.
OCR_GPAY = "To Swiggy\n\n349\n\nVv Completed\n\n24 Sep 2026, 8:41 pm\n\n426712345678\n" \
           "To Swiggy\n\n3349\n\nVv Completed\n24 Sep 2026, 8:41 pm\n426712345678"
OCR_PHONEPE = "Transaction Successful\n\n08:15 pm on 23 Sep 2026\n\nPaid to\n\nBlinkit £4 1,284\n" \
              "blinkit.grofers@hdfcbank\nDebited from\nXXXXXXXX1234 31,284\nUTR: 426798765432"
OCR_PAYTM = "Paid Successfully to\n\nUber India\n\n¥212\n\n22 Sep, 10:15 PM\n\nUPI Ref No: 426611112222"


def test_ocr_gpay_amount_without_rupee_sign():
    r = parse_receipt_text(OCR_GPAY, date(2026, 9, 30))
    assert (r.amount_cents, r.payee, r.date, r.reference) == (34900, "Swiggy", "2026-09-24", "426712345678")


def test_ocr_phonepe_amount_glued_to_payee():
    r = parse_receipt_text(OCR_PHONEPE, date(2026, 9, 30))
    assert (r.amount_cents, r.payee, r.date) == (128400, "Blinkit", "2026-09-23")
    assert r.category == "Groceries"


def test_ocr_paytm_yen_for_rupee():
    r = parse_receipt_text(OCR_PAYTM, date(2026, 9, 30))
    assert (r.amount_cents, r.payee, r.date) == (21200, "Uber India", "2026-09-22")


def test_lookalike_does_not_swallow_digits():
    assert parse_receipt_text("Paid to X\n%250", TODAY).amount_cents == 25000
