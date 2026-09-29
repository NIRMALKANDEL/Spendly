"""Money parsing and formatting.

Amounts are stored as integer minor units (paise / cents) so sums never pick
up floating-point drift.
"""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from services.categories import CURRENCIES

MAX_AMOUNT_CENTS = 100_000_000_000  # 1,000,000,000.00 — a sanity ceiling.


def parse_amount(raw, allow_zero=False):
    """Parse user input like "1,250.5" into cents. Raises ValueError."""
    if raw is None:
        raise ValueError("Amount is required.")
    text = str(raw).strip().replace(",", "").replace("_", "")
    for symbol, *_ in CURRENCIES.values():
        text = text.replace(symbol, "")
    text = text.strip()
    if not text:
        raise ValueError("Amount is required.")
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise ValueError("Amount must be a number.") from None
    if not value.is_finite():
        raise ValueError("Amount must be a number.")
    if abs(value) > Decimal(MAX_AMOUNT_CENTS) / 100:
        raise ValueError("Amount is too large.")
    if value.as_tuple().exponent < -2:
        raise ValueError("Amount can have at most 2 decimal places.")
    cents = int((value * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if cents < 0 or (cents == 0 and not allow_zero):
        raise ValueError("Amount must be greater than zero.")
    if cents > MAX_AMOUNT_CENTS:
        raise ValueError("Amount is too large.")
    return cents


def _group_western(digits):
    return f"{int(digits):,}"


def _group_indian(digits):
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts) + "," + tail


def format_money(cents, currency="INR", decimals=None):
    """Format cents for display: ₹1,23,456 or $123,456.78.

    decimals=None shows paise only when the amount has any.
    """
    cents = int(cents or 0)
    symbol, grouping, _ = CURRENCIES.get(currency, CURRENCIES["INR"])
    sign = "−" if cents < 0 else ""
    cents = abs(cents)
    whole, frac = divmod(cents, 100)
    group = _group_indian if grouping == "indian" else _group_western
    text = group(str(whole))
    if decimals is True or (decimals is None and frac):
        text += f".{frac:02d}"
    return f"{sign}{symbol}{text}"


def cents_to_input(cents):
    """Render cents back into a plain form-field value ("1250.50")."""
    if cents is None:
        return ""
    whole, frac = divmod(int(cents), 100)
    return f"{whole}.{frac:02d}" if frac else str(whole)
