import io

from conftest import Client

from database.db import get_db


def all_tx(app):
    with app.app_context():
        return get_db().execute("SELECT * FROM transactions ORDER BY id").fetchall()


def test_add_expense_stores_cents(app, auth_client):
    resp = auth_client.add_tx(amount="1,250.50", description="Groceries run", category="Groceries")
    assert resp.status_code == 302
    rows = all_tx(app)
    assert len(rows) == 1
    assert rows[0]["amount_cents"] == 125050
    assert rows[0]["category"] == "Groceries"
    assert rows[0]["kind"] == "expense"


def test_add_income(app, auth_client):
    auth_client.add_tx(amount="65000", kind="income", category="Salary")
    assert all_tx(app)[0]["kind"] == "income"


def test_category_must_match_kind(app, auth_client):
    resp = auth_client.add_tx(kind="income", category="Food")
    assert resp.status_code == 400
    assert all_tx(app) == []


def test_invalid_amounts_rejected(app, auth_client):
    for amount in ["", "abc", "0", "-5", "1.234", "nan", "inf", "99999999999"]:
        resp = auth_client.add_tx(amount=amount)
        assert resp.status_code == 400, amount
    assert all_tx(app) == []


def test_invalid_dates_rejected(auth_client):
    for day in ["", "2026-13-01", "1999-12-31", "2030-01-01", "yesterday"]:
        assert auth_client.add_tx(day=day).status_code == 400, day


def test_description_length_limit(auth_client):
    assert auth_client.add_tx(description="x" * 201).status_code == 400
    assert auth_client.add_tx(description="x" * 200).status_code == 302


def test_description_is_html_escaped(auth_client):
    auth_client.add_tx(description="<script>alert(1)</script>")
    page = auth_client.get("/transactions/")
    assert b"<script>alert(1)</script>" not in page.data
    assert b"&lt;script&gt;" in page.data


def test_edit_transaction(app, auth_client):
    auth_client.add_tx(amount="100")
    tx_id = all_tx(app)[0]["id"]
    assert auth_client.get(f"/transactions/{tx_id}/edit").status_code == 200
    resp = auth_client.post(f"/transactions/{tx_id}/edit", {
        "kind": "expense", "amount": "250", "category": "Transport", "date": "2026-09-11", "description": "Cab"})
    assert resp.status_code == 302
    row = all_tx(app)[0]
    assert (row["amount_cents"], row["category"], row["description"]) == (25000, "Transport", "Cab")


def test_delete_transaction(app, auth_client):
    auth_client.add_tx()
    tx_id = all_tx(app)[0]["id"]
    assert auth_client.post(f"/transactions/{tx_id}/delete").status_code == 302
    assert all_tx(app) == []


def test_delete_requires_post(app, auth_client):
    auth_client.add_tx()
    tx_id = all_tx(app)[0]["id"]
    assert auth_client.get(f"/transactions/{tx_id}/delete").status_code == 405


def test_users_cannot_touch_each_others_transactions(app, auth_client):
    auth_client.add_tx(amount="100")
    tx_id = all_tx(app)[0]["id"]

    mallory = Client(app.test_client())
    mallory.register(name="Mallory", email="mallory@example.com")
    assert mallory.get(f"/transactions/{tx_id}/edit").status_code == 404
    assert mallory.post(f"/transactions/{tx_id}/edit", {
        "kind": "expense", "amount": "1", "category": "Food", "date": "2026-09-10"}).status_code == 404
    assert mallory.post(f"/transactions/{tx_id}/delete").status_code == 404
    assert b"Transactions" in mallory.get("/transactions/").data
    assert all_tx(app)[0]["amount_cents"] == 10000


def test_list_filters_and_search(auth_client):
    auth_client.add_tx(amount="100", category="Food", description="Pizza night", day="2026-09-01")
    auth_client.add_tx(amount="200", category="Transport", description="Metro", day="2026-09-05")
    auth_client.add_tx(amount="5000", kind="income", category="Salary", day="2026-09-02")

    page = auth_client.get("/transactions/?q=pizza").data
    assert b"Pizza night" in page and b"Metro" not in page

    page = auth_client.get("/transactions/?kind=income").data
    assert b"Salary" in page and b"Metro" not in page

    page = auth_client.get("/transactions/?start=2026-09-04&end=2026-09-30").data
    assert b"Metro" in page and b"Pizza night" not in page


def test_search_treats_wildcards_literally(auth_client):
    auth_client.add_tx(description="plain")
    page = auth_client.get("/transactions/?q=%25").data
    assert b"No transactions match" in page


def test_pagination(auth_client):
    for i in range(25):
        auth_client.add_tx(amount=str(i + 1), description=f"item-{i}")
    first = auth_client.get("/transactions/").data
    second = auth_client.get("/transactions/?page=2").data
    assert b"Page 1 of 2" in first
    assert b"item-0<" in second  # oldest lands on page 2 with newest-first sort
    assert auth_client.get("/transactions/?page=999").status_code == 200


def test_export_csv_escapes_formulas(auth_client):
    auth_client.add_tx(amount="99.5", description="=HYPERLINK(\"http://x\")")
    resp = auth_client.get("/transactions/export.csv")
    assert resp.status_code == 200
    assert resp.mimetype == "text/csv"
    text = resp.data.decode("utf-8-sig")
    assert text.splitlines()[0] == "date,type,category,amount,description"
    assert "99.50" in text
    assert "'=HYPERLINK" in text


def test_import_csv_round_trip(app, auth_client):
    csv_text = (
        "date,type,category,amount,description\n"
        "2026-09-01,income,Salary,65000,September salary\n"
        "2026-09-03,expense,groceries,1840.50,Weekly groceries\n"
    )
    resp = auth_client.post("/transactions/import",
                            {"file": (io.BytesIO(csv_text.encode()), "data.csv")},
                            content_type="multipart/form-data")
    assert resp.status_code == 302
    rows = all_tx(app)
    assert [(r["kind"], r["category"], r["amount_cents"]) for r in rows] == [
        ("income", "Salary", 6500000), ("expense", "Groceries", 184050)]


def test_import_rejects_whole_file_on_bad_row(app, auth_client):
    csv_text = "date,category,amount\n2026-09-01,Food,100\n2026-09-02,Food,abc\n"
    resp = auth_client.post("/transactions/import",
                            {"file": (io.BytesIO(csv_text.encode()), "data.csv")},
                            content_type="multipart/form-data")
    assert resp.status_code == 400
    assert b"Row 3" in resp.data
    assert all_tx(app) == []


def test_import_requires_columns(app, auth_client):
    resp = auth_client.post("/transactions/import",
                            {"file": (io.BytesIO(b"foo,bar\n1,2\n"), "data.csv")},
                            content_type="multipart/form-data")
    assert resp.status_code == 302
    assert all_tx(app) == []
