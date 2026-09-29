"""Receipt scanning routes, duplicate protection, share target and AI reader."""

import io
import json
from types import SimpleNamespace

import anthropic
import pytest

from conftest import TODAY, Client

from database.db import get_db
from services import receipt_ai
from services.receipt_ai import ReceiptAIError, extract_receipt

GPAY_TEXT = """To Swiggy
₹250
Completed
12 Sep 2026, 8:41 pm
UPI transaction ID
425612345678
Google Pay"""

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 64


def saved(app):
    with app.app_context():
        return get_db().execute("SELECT * FROM transactions ORDER BY id").fetchall()


def review_first(app):
    """Turn auto-save off so clear receipts show the review form."""
    with app.app_context():
        db = get_db()
        db.execute("UPDATE users SET auto_save_receipts = 0")
        db.commit()


def save_from_receipt(client, **overrides):
    data = {"source": "receipt", "kind": "expense", "amount": "250", "category": "Food",
            "date": "2026-09-12", "description": "Swiggy", "reference": "425612345678"}
    data.update(overrides)
    return client.post("/transactions/new", data)


# ------------------------------------------------------------------ #
# Scan + review                                                       #
# ------------------------------------------------------------------ #

def test_scan_page_requires_login(client):
    assert client.get("/receipts/scan").status_code == 302


def test_scan_page_renders_with_local_ocr(auth_client):
    page = auth_client.get("/receipts/scan").data
    assert b"Scan a receipt" in page
    assert b'data-ai="0"' in page
    assert b"vendor/tesseract/tesseract.min.js" in page
    assert b"never uploaded" in page


def test_review_prefills_form_from_ocr_text(app, auth_client):
    review_first(app)
    resp = auth_client.post("/receipts/review", {"mode": "ocr", "text": GPAY_TEXT})
    assert resp.status_code == 200
    page = resp.get_data(as_text=True)
    assert 'value="250"' in page
    assert 'value="2026-09-12"' in page
    assert 'value="Swiggy"' in page
    assert 'name="reference" value="425612345678"' in page
    assert '<option value="Food" selected>' in page
    assert "Google Pay" in page and "Read on your device" in page
    assert 'action="/transactions/new"' in page


def test_review_nothing_is_saved_until_confirmed(app, auth_client):
    review_first(app)
    auth_client.post("/receipts/review", {"mode": "ocr", "text": GPAY_TEXT})
    assert saved(app) == []


def test_review_without_text_returns_to_scan(auth_client):
    resp = auth_client.post("/receipts/review", {"mode": "ocr", "text": "   "})
    assert resp.status_code == 422
    assert b"find any text in that image" in resp.data


def test_review_marks_missing_amount(auth_client):
    page = auth_client.post("/receipts/review", {"mode": "text", "text": "Paid to Ramesh"}).get_data(as_text=True)
    assert "needs-attention" in page
    assert "Read from the pasted text" in page


def test_review_escapes_recognised_text(auth_client):
    page = auth_client.post("/receipts/review", {"mode": "ocr", "text": "<script>alert(1)</script> ₹10"}).data
    assert b"<script>alert(1)</script>" not in page


def test_saving_a_receipt_stores_reference(app, auth_client):
    resp = save_from_receipt(auth_client)
    assert resp.status_code == 302
    row = saved(app)[0]
    assert (row["amount_cents"], row["reference"], row["description"]) == (25000, "425612345678", "Swiggy")


def test_duplicate_receipt_is_blocked_then_allowed_on_confirm(app, auth_client):
    save_from_receipt(auth_client)
    review = auth_client.post("/receipts/review", {"mode": "ocr", "text": GPAY_TEXT}).get_data(as_text=True)
    assert "already saved this payment" in review

    resp = save_from_receipt(auth_client)
    assert resp.status_code == 409
    assert len(saved(app)) == 1

    resp = save_from_receipt(auth_client, allow_duplicate="1")
    assert resp.status_code == 302
    assert len(saved(app)) == 2


def test_duplicate_check_is_per_user(app, auth_client):
    save_from_receipt(auth_client)
    other = Client(app.test_client())
    other.register(email="other@example.com")
    assert save_from_receipt(other).status_code == 302


def test_reference_is_sanitised(app, auth_client):
    save_from_receipt(auth_client, reference="4256-1234<script>")
    assert saved(app)[0]["reference"] == "42561234script"


def test_save_and_scan_another(auth_client):
    resp = save_from_receipt(auth_client, add_another="1")
    assert resp.location.endswith("/receipts/scan")


def test_manual_transactions_have_no_reference(app, auth_client):
    auth_client.add_tx()
    assert saved(app)[0]["reference"] is None


# ------------------------------------------------------------------ #
# Share target                                                        #
# ------------------------------------------------------------------ #

def test_share_accepts_image_without_csrf_token(auth_client):
    resp = auth_client.post("/receipts/share", {"receipt": (io.BytesIO(PNG_BYTES), "shot.png")},
                            csrf=False, content_type="multipart/form-data")
    assert resp.status_code == 200
    assert b'src="data:image/png;base64,' in resp.data


def test_share_accepts_text(auth_client):
    resp = auth_client.post("/receipts/share", {"text": "Paid ₹150 to Ramesh via Google Pay"}, csrf=False)
    assert resp.status_code == 200
    assert "Paid ₹150 to Ramesh" in resp.get_data(as_text=True)


def test_share_rejects_non_images(auth_client):
    resp = auth_client.post("/receipts/share", {"receipt": (io.BytesIO(b"<svg onload=alert(1)>"), "x.svg")},
                            csrf=False, content_type="multipart/form-data")
    assert resp.status_code == 400
    assert b"data:image" not in resp.data


def test_share_requires_login(client):
    resp = client.post("/receipts/share", {"text": "hi"}, csrf=False)
    assert resp.status_code == 302 and "/login" in resp.location


def test_share_never_writes_data(app, auth_client):
    auth_client.post("/receipts/share", {"text": GPAY_TEXT}, csrf=False)
    assert saved(app) == []


def test_other_posts_still_need_csrf(auth_client):
    assert auth_client.post("/receipts/review", {"text": GPAY_TEXT}, csrf=False).status_code == 400


# ------------------------------------------------------------------ #
# PWA plumbing                                                        #
# ------------------------------------------------------------------ #

def test_service_worker_served_from_root(client):
    resp = client.get("/sw.js")
    assert resp.status_code == 200
    assert resp.mimetype == "application/javascript"
    assert resp.headers["Service-Worker-Allowed"] == "/"
    assert b"/receipts/share" in resp.data


def test_manifest_declares_share_target(client):
    resp = client.get("/static/manifest.webmanifest")
    manifest = json.loads(resp.data)
    assert manifest["share_target"]["action"] == "/receipts/share"
    assert manifest["share_target"]["params"]["files"][0]["name"] == "receipt"
    sizes = {icon["sizes"] for icon in manifest["icons"]}
    assert {"192x192", "512x512"} <= sizes


def test_csp_allows_wasm_but_not_eval(client):
    csp = client.get("/").headers["Content-Security-Policy"]
    assert "'wasm-unsafe-eval'" in csp
    assert "'unsafe-eval'" not in csp.replace("'wasm-unsafe-eval'", "")


def test_ocr_assets_are_vendored(client):
    for path in ["vendor/tesseract/tesseract.min.js", "vendor/tesseract/worker.min.js",
                 "vendor/tesseract/core/tesseract-core-simd-lstm.wasm.js", "vendor/tesseract/lang/eng.traineddata.gz"]:
        assert client.get("/static/" + path).status_code == 200, path


# ------------------------------------------------------------------ #
# Option B: AI reader                                                 #
# ------------------------------------------------------------------ #

class FakeClient:
    """Stands in for anthropic.Anthropic(); records the request, returns a canned reply."""

    def __init__(self, reply=None, error=None, stop_reason="end_turn"):
        self.calls = []
        self.reply, self.error, self.stop_reason = reply, error, stop_reason
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(
            stop_reason=self.stop_reason,
            content=[SimpleNamespace(type="thinking", thinking=""),
                     SimpleNamespace(type="text", text=json.dumps(self.reply))],
        )


AI_REPLY = {"type": "expense", "amount": "480.00", "date": "2026-09-12", "payee": "Zomato",
            "reference": "425698765432", "category": "Food", "app": "PhonePe"}


def enable_ai(app, monkeypatch, fake):
    app.config.update(RECEIPT_AI_PROVIDER="anthropic", ANTHROPIC_API_KEY="test-key")
    monkeypatch.setattr(receipt_ai, "_client", lambda: fake)


def test_ai_is_off_by_default(app):
    with app.app_context():
        assert receipt_ai.ai_enabled() is False


def test_ai_request_shape(app):
    fake = FakeClient(AI_REPLY)
    with app.app_context():
        receipt = extract_receipt(PNG_BYTES, "image/png", TODAY, client=fake)
    call = fake.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["fallbacks"] == "default" and call["betas"] == ["server-side-fallback-2026-07-01"]
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert call["messages"][0]["content"][0]["source"]["media_type"] == "image/png"
    assert (receipt.amount_cents, receipt.payee, receipt.reference) == (48000, "Zomato", "425698765432")


def test_ai_review_route(app, auth_client, monkeypatch):
    fake = FakeClient(AI_REPLY)
    enable_ai(app, monkeypatch, fake)
    review_first(app)
    assert b'data-ai="1"' in auth_client.get("/receipts/scan").data
    resp = auth_client.post("/receipts/review", {"mode": "ai", "image": (io.BytesIO(JPEG_BYTES), "r.jpg")},
                            content_type="multipart/form-data")
    page = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert 'value="480"' in page and "Read by AI" in page
    assert len(fake.calls) == 1


def test_ai_failure_falls_back_to_text(app, auth_client, monkeypatch):
    request = SimpleNamespace(method="POST", url="https://api.anthropic.com/v1/messages")
    fake = FakeClient(error=anthropic.APIConnectionError(request=request))
    enable_ai(app, monkeypatch, fake)
    resp = auth_client.post("/receipts/review", {"mode": "ai", "text": GPAY_TEXT,
                                                 "image": (io.BytesIO(JPEG_BYTES), "r.jpg")},
                            content_type="multipart/form-data")
    page = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert 'value="250"' in page and "unavailable" in page


def test_ai_failure_without_text_asks_to_scan_on_device(app, auth_client, monkeypatch):
    fake = FakeClient(AI_REPLY, stop_reason="refusal")
    enable_ai(app, monkeypatch, fake)
    resp = auth_client.post("/receipts/review", {"mode": "ai", "image": (io.BytesIO(JPEG_BYTES), "r.jpg")},
                            content_type="multipart/form-data")
    assert resp.status_code == 422
    assert b"scan on this device" in resp.data


def test_ai_rejects_bad_images_and_bad_json(app):
    with app.app_context():
        with pytest.raises(ReceiptAIError):
            extract_receipt(b"not an image", "application/pdf", TODAY, client=FakeClient(AI_REPLY))
        fake = FakeClient(AI_REPLY)
        fake.beta.messages.create = lambda **kw: SimpleNamespace(
            stop_reason="end_turn", content=[SimpleNamespace(type="text", text="not json")])
        with pytest.raises(ReceiptAIError):
            extract_receipt(PNG_BYTES, "image/png", TODAY, client=fake)


def test_ai_output_is_revalidated(app):
    hostile = {"type": "expense", "amount": "-99", "date": "2099-01-01", "payee": "₹500",
               "reference": "'; DROP TABLE--", "category": "Hacking", "app": "x"}
    with app.app_context():
        r = extract_receipt(PNG_BYTES, "image/png", TODAY, client=FakeClient(hostile))
    assert r.amount_cents is None and r.date is None and r.payee is None
    assert r.reference == "DROPTABLE" and r.category == "Other"



# ------------------------------------------------------------------ #
# Auto-save + undo                                                    #
# ------------------------------------------------------------------ #

def test_clear_receipt_is_auto_saved_with_undo(app, auth_client):
    resp = auth_client.post("/receipts/review", {"mode": "ocr", "text": GPAY_TEXT})
    assert resp.status_code == 302 and resp.location.endswith("/dashboard")
    row = saved(app)[0]
    assert (row["amount_cents"], row["description"], row["reference"]) == (25000, "Swiggy", "425612345678")
    dash = auth_client.get("/dashboard").get_data(as_text=True)
    assert "Saved ₹250 · Swiggy · Food" in dash and ">Undo<" in dash
    assert "Saved ₹250" not in auth_client.get("/dashboard").get_data(as_text=True)  # shown once


def test_undo_removes_the_auto_saved_transaction(app, auth_client):
    auth_client.post("/receipts/review", {"mode": "ocr", "text": GPAY_TEXT})
    tx_id = saved(app)[0]["id"]
    resp = auth_client.post(f"/transactions/{tx_id}/delete", {"undo": "1", "next": "/dashboard"})
    assert resp.location.endswith("/dashboard")
    assert saved(app) == []
    assert b"Undone" in auth_client.get("/dashboard").data


def test_unclear_receipt_still_shows_form(app, auth_client):
    # Amount without a rupee sign and no corroboration -> not confident.
    resp = auth_client.post("/receipts/review", {"mode": "ocr", "text": "Paid to Ramesh\n85\nPayment successful"})
    assert resp.status_code == 200 and b"Check and save" in resp.data
    assert saved(app) == []


def test_possible_duplicate_is_never_auto_saved(app, auth_client):
    auth_client.post("/receipts/review", {"mode": "ocr", "text": GPAY_TEXT})
    resp = auth_client.post("/receipts/review", {"mode": "ocr", "text": GPAY_TEXT})
    assert resp.status_code == 200 and b"already saved this payment" in resp.data
    assert len(saved(app)) == 1


def test_auto_save_can_be_turned_off(app, auth_client):
    auth_client.post("/settings/receipts", {})
    resp = auth_client.post("/receipts/review", {"mode": "ocr", "text": GPAY_TEXT})
    assert resp.status_code == 200
    assert saved(app) == []
    auth_client.post("/settings/receipts", {"auto_save_receipts": "1"})
    assert auth_client.post("/receipts/review", {"mode": "ocr", "text": GPAY_TEXT}).status_code == 302


def test_ai_read_receipt_is_auto_saved(app, auth_client, monkeypatch):
    enable_ai(app, monkeypatch, FakeClient(AI_REPLY))
    resp = auth_client.post("/receipts/review", {"mode": "ai", "image": (io.BytesIO(JPEG_BYTES), "r.jpg")},
                            content_type="multipart/form-data")
    assert resp.status_code == 302
    assert saved(app)[0]["amount_cents"] == 48000


# ------------------------------------------------------------------ #
# Quick add                                                           #
# ------------------------------------------------------------------ #

def test_quick_add_saves_and_offers_undo(app, auth_client):
    resp = auth_client.post("/transactions/quick", {"q": "lunch 180 yesterday", "next": "/dashboard"})
    assert resp.location.endswith("/dashboard")
    row = saved(app)[0]
    assert (row["kind"], row["amount_cents"], row["category"], row["date"], row["description"]) ==         ("expense", 18000, "Food", "2026-09-14", "Lunch")
    assert "Saved ₹180 · Lunch · Food" in auth_client.get("/dashboard").get_data(as_text=True)


def test_quick_add_income(app, auth_client):
    auth_client.post("/transactions/quick", {"q": "salary 65000"})
    row = saved(app)[0]
    assert (row["kind"], row["category"], row["amount_cents"]) == ("income", "Salary", 6500000)


def test_quick_add_error_saves_nothing(app, auth_client):
    auth_client.post("/transactions/quick", {"q": "lunch"})
    assert saved(app) == []
    assert b"Add an amount" in auth_client.get("/dashboard").data


def test_quick_add_needs_csrf_and_login(app, auth_client):
    assert auth_client.post("/transactions/quick", {"q": "250 tea"}, csrf=False).status_code == 400
    signed_out = Client(app.test_client())
    assert signed_out.post("/transactions/quick", {"q": "250 tea"}).status_code == 302
    assert saved(app) == []


def test_quick_add_rejects_offsite_next(app, auth_client):
    resp = auth_client.post("/transactions/quick", {"q": "250 tea", "next": "https://evil.example"})
    assert "evil" not in resp.location


def test_quick_preview(auth_client):
    data = auth_client.get("/transactions/quick/preview?q=250%20swiggy").json
    assert data == {"ok": True, "kind": "expense", "amount": "₹250", "category": "Food", "date": "2026-09-15",
                    "is_today": True, "description": "Swiggy", "when": "today"}
    assert auth_client.get("/transactions/quick/preview?q=tea%2020%20yesterday").json["when"] == "yesterday"
    assert auth_client.get("/transactions/quick/preview?q=tea%2020%20on%201%20sep").json["when"] == "Tue 1 Sep"
    assert auth_client.get("/transactions/quick/preview?q=swiggy").json["ok"] is False


def test_dashboard_has_quick_add(auth_client):
    assert b"data-quick-add" in auth_client.get("/dashboard").data
