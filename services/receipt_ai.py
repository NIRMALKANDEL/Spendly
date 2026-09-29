"""Option B: read a receipt image with Claude.

Off by default. Turn it on with:
    RECEIPT_AI_PROVIDER=anthropic
    ANTHROPIC_API_KEY=sk-ant-...
    RECEIPT_AI_MODEL=claude-opus-5-5   (optional; this is the default)

The model only *reads* the image and returns structured JSON; every field is
then re-validated by services.receipts.receipt_from_fields, and the user still
confirms the draft before anything is saved.
"""

import json
import logging

from flask import current_app

from services.receipts import receipt_from_fields

log = logging.getLogger(__name__)

ALLOWED_MEDIA_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024

PROMPT = (
    "This image is a payment receipt: most often a UPI app screenshot (Google Pay, PhonePe, Paytm, BHIM), "
    "otherwise a bank SMS or a shop bill. Extract the single payment it records.\n"
    "- type: 'expense' if money left the user's account, 'income' if the user received money.\n"
    "- amount: the payment amount as a plain number string without currency symbol or commas, e.g. '1250.50'.\n"
    "- date: ISO format YYYY-MM-DD. If the year isn't shown, use {year}.\n"
    "- payee: the merchant or person paid (for income: who paid). Not a bank name, not a UPI ID if a name is shown.\n"
    "- reference: the UPI transaction ID / UTR / RRN (digits only) if shown.\n"
    "- category: one of {categories}. Use 'Other' if unsure.\n"
    "- app: the payment app name if identifiable.\n"
    "Use an empty string for anything not visible. Never guess an amount you can't read."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": ["expense", "income"]},
        "amount": {"type": "string"},
        "date": {"type": "string"},
        "payee": {"type": "string"},
        "reference": {"type": "string"},
        "category": {"type": "string"},
        "app": {"type": "string"},
    },
    "required": ["type", "amount", "date", "payee", "reference", "category", "app"],
    "additionalProperties": False,
}


class ReceiptAIError(Exception):
    """The AI reader couldn't produce a result; the caller falls back to on-device OCR."""


def ai_enabled():
    cfg = current_app.config
    return cfg.get("RECEIPT_AI_PROVIDER") == "anthropic" and bool(cfg.get("ANTHROPIC_API_KEY"))


def _client():
    import anthropic  # imported lazily so the app runs without the SDK when AI is off

    return anthropic.Anthropic(api_key=current_app.config["ANTHROPIC_API_KEY"], timeout=45.0, max_retries=1)


def extract_receipt(image_bytes, media_type, today, client=None):
    """Return a services.receipts.Receipt read from the image, or raise ReceiptAIError."""
    import base64

    import anthropic

    from services.categories import EXPENSE_CATEGORIES, INCOME_CATEGORIES

    if media_type not in ALLOWED_MEDIA_TYPES:
        raise ReceiptAIError("Unsupported image type.")
    if not image_bytes or len(image_bytes) > MAX_IMAGE_BYTES:
        raise ReceiptAIError("Image is empty or too large.")

    categories = ", ".join(dict.fromkeys(EXPENSE_CATEGORIES + INCOME_CATEGORIES))
    client = client or _client()
    try:
        response = client.beta.messages.create(
            model=current_app.config.get("RECEIPT_AI_MODEL") or "claude-opus-5-5",
            max_tokens=2000,
            # If a safety classifier declines, the API retries on a suitable model itself.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            # Reading a receipt is simple extraction: low effort keeps it fast and cheap.
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type,
                                                 "data": base64.standard_b64encode(image_bytes).decode()}},
                    {"type": "text", "text": PROMPT.format(year=today.year, categories=categories)},
                ],
            }],
        )
    except anthropic.AuthenticationError as exc:
        log.error("Receipt AI: invalid ANTHROPIC_API_KEY")
        raise ReceiptAIError("AI reader is misconfigured.") from exc
    except anthropic.RateLimitError as exc:
        raise ReceiptAIError("AI reader is busy; try again in a minute.") from exc
    except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
        log.warning("Receipt AI request failed: %s", exc)
        raise ReceiptAIError("AI reader is unavailable right now.") from exc

    if response.stop_reason == "refusal":
        raise ReceiptAIError("The AI reader declined this image.")
    text = next((b.text for b in response.content if b.type == "text"), None)
    try:
        data = json.loads(text or "")
    except json.JSONDecodeError as exc:
        raise ReceiptAIError("AI reader returned an unexpected answer.") from exc
    if not isinstance(data, dict):
        raise ReceiptAIError("AI reader returned an unexpected answer.")
    return receipt_from_fields(data, today)
