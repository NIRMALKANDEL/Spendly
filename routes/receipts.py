"""Scan or share a payment receipt and turn it into a draft transaction.

Flow: /receipts/scan reads the image on the device (Tesseract.js) and posts the
recognised text to /receipts/review, which parses it and shows the normal
transaction form pre-filled. Nothing is saved until the user presses Save.
With RECEIPT_AI_PROVIDER=anthropic the image itself is sent to /receipts/review
and read by Claude instead (services/receipt_ai.py).
"""

import base64

from flask import Blueprint, current_app, g, redirect, render_template, request, url_for

from routes.transactions import (
    find_duplicate, insert_transaction, offer_undo, render_form, validate_transaction,
)
from services.dates import today
from services.receipt_ai import ReceiptAIError, ai_enabled, extract_receipt
from services.receipts import MAX_TEXT_LENGTH, parse_receipt_text
from services.security import login_required

bp = Blueprint("receipts", __name__, url_prefix="/receipts")

# Magic numbers of the image formats we accept; the declared MIME type is not trusted.
IMAGE_SIGNATURES = [
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
]


def sniff_image(data):
    for signature, media_type in IMAGE_SIGNATURES:
        if data.startswith(signature):
            return media_type
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def read_image(upload, max_bytes):
    """(bytes, media_type) for a valid uploaded image, else (None, None)."""
    if not upload or not upload.filename:
        return None, None
    data = upload.read(max_bytes + 1)
    if not data or len(data) > max_bytes:
        return None, None
    media_type = sniff_image(data)
    return (data, media_type) if media_type else (None, None)


def scan_page(error=None, shared_text="", shared_image=None, status=200):
    return render_template(
        "receipts/scan.html",
        error=error,
        ai=ai_enabled(),
        shared_text=shared_text,
        shared_image=shared_image,
    ), status


@bp.route("/scan")
@login_required
def scan():
    return scan_page()


@bp.route("/review", methods=["POST"])
@login_required
def review():
    now = today()
    text = (request.form.get("text") or "")[:MAX_TEXT_LENGTH]
    receipt, method, notice = None, "text", None

    if ai_enabled() and request.form.get("mode") == "ai":
        data, media_type = read_image(request.files.get("image"), 5 * 1024 * 1024)
        if data:
            try:
                receipt, method = extract_receipt(data, media_type, now), "ai"
            except ReceiptAIError as exc:
                notice = str(exc)
        elif not text.strip():
            return scan_page(error="Choose a JPG, PNG or WebP image of the receipt.", status=400)

    if receipt is None:
        if not text.strip():
            message = notice or "We couldn't find any text in that image. Try a sharper screenshot, or paste the text."
            return scan_page(error=message + (" You can scan on this device instead." if notice else ""),
                             status=422)
        receipt, method = parse_receipt_text(text, now), ("ocr" if request.form.get("mode") == "ocr" else "text")

    form = receipt.to_form(now)
    duplicate = find_duplicate(g.user["id"], receipt.reference)

    # Clearly-read receipts are saved straight away, with Undo, when the user allows it.
    if g.user["auto_save_receipts"] and receipt.is_clear() and not duplicate and not notice:
        clean, error = validate_transaction(form)
        if not error:
            offer_undo(insert_transaction(g.user["id"], clean), clean)
            return redirect(url_for("main.dashboard"))

    context = {
        "source": "receipt",
        "method": method,
        "found": sorted(receipt.found),
        "app": receipt.app,
        "text": text[:4000],
        "notice": notice,
    }
    return render_form(form=form, receipt=context, duplicate=duplicate)


@bp.route("/share", methods=["POST"])
@login_required
def share():
    """Android share-target fallback (the service worker normally handles this).

    CSRF-exempt because the browser posts it from the OS share sheet without our
    token. That is safe: it only renders the scan page and never writes data;
    saving still goes through the CSRF-protected transaction form.
    """
    max_bytes = current_app.config["SHARE_MAX_BYTES"]
    request.max_content_length = max_bytes + 64 * 1024
    parts = [request.form.get(k, "").strip() for k in ("title", "text", "url")]
    shared_text = "\n".join(p for p in parts if p)[:MAX_TEXT_LENGTH]
    image = None
    upload = request.files.get("receipt") or next(iter(request.files.values()), None)
    data, media_type = read_image(upload, max_bytes)
    if data:
        image = f"data:{media_type};base64,{base64.b64encode(data).decode()}"
    if not image and not shared_text:
        return scan_page(error="Nothing we can read was shared. Share a screenshot of the payment.", status=400)
    return scan_page(shared_text=shared_text, shared_image=image)
