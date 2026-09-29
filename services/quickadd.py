"""Parse one-line quick entries like "250 swiggy", "lunch 180 yesterday", "+65000 salary"."""

import re
from datetime import timedelta
from decimal import Decimal

from services.categories import EXPENSE_CATEGORIES, INCOME_CATEGORIES
from services.receipts import MONTHS, guess_category

MAX_LENGTH = 200

AMOUNT = re.compile(
    r"(?<![\w.])(?:₹|rs\.?|inr)?\s*(\d{1,3}(?:,\d{2,3})+|\d+)(?:\.(\d{1,2}))?\s*(k|lakh|lac|l)?(?![\w])", re.I)
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MONTH_WORD = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"

INCOME_WORDS = re.compile(
    r"\b(salary|income|received|receive|got|refund|cashback|credited|bonus|freelance|dividend|interest|stipend"
    r"|payment from)\b", re.I)
FILLER = {"for", "on", "at", "paid", "spent", "spend", "to", "from", "the", "a", "an", "rs", "inr", "rupees", "of",
          "bought", "buy", "pay", "gave", "via", "using", "in", "and"}

# Everyday words that the receipt keyword table (merchant names) doesn't cover.
QUICK_KEYWORDS = [
    ("Food", ["lunch", "dinner", "breakfast", "snack", "snacks", "tea", "coffee", "chai", "meal", "momos", "maggi",
              "samosa", "dosa", "icecream", "ice cream", "sweets", "party"]),
    ("Groceries", ["milk", "vegetables", "veggies", "veg", "fruits", "fruit", "eggs", "bread", "ration", "rice",
                   "atta", "dal", "oil", "sabzi"]),
    ("Transport", ["bus", "train", "rickshaw", "bike", "scooty", "car wash", "service", "cab"]),
    ("Bills", ["electricity", "current bill", "internet", "mobile", "phone bill", "gas", "maintenance"]),
    ("Health", ["medicine", "medicines", "tablets", "hospital", "checkup", "dentist"]),
    ("Entertainment", ["movie", "movies", "concert", "game", "games", "subscription"]),
    ("Shopping", ["clothes", "shirt", "tshirt", "jeans", "shoes", "dress", "gift", "watch", "phone case"]),
    ("Education", ["book", "fees", "fee", "exam", "notes", "pen"]),
    ("Travel", ["trip", "ticket", "tickets", "tour", "vacation"]),
]
QUICK_INCOME_KEYWORDS = [
    ("Salary", ["salary", "bonus", "stipend"]),
    ("Freelance", ["freelance", "client", "project"]),
    ("Investment", ["interest", "dividend"]),
    ("Gift", ["gift", "birthday"]),
]


def _strip_dates(text, today):
    """Remove date phrases from text and return (text_without_dates, date)."""
    day = None
    lowered = text.lower()

    patterns = [
        (r"\bday before yesterday\b", lambda m: today - timedelta(days=2)),
        (r"\byesterday\b|\byday\b", lambda m: today - timedelta(days=1)),
        (r"\btoday\b|\btdy\b", lambda m: today),
        (r"\blast\s+(" + "|".join(WEEKDAYS) + r")\b|\b(" + "|".join(WEEKDAYS) + r")\b", None),
        (r"\b(?:on\s+)?(\d{1,2})(?:st|nd|rd|th)?\s+" + MONTH_WORD + r"\b", None),
        (r"\b(?:on\s+)?" + MONTH_WORD + r"\s+(\d{1,2})(?:st|nd|rd|th)?\b", None),
        # "25/9", "25-09-2026". A dot is a decimal point ("1.5 lakh"), never a date separator.
        (r"\b(?:on\s+)?(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", None),
    ]
    for pattern, resolver in patterns:
        m = re.search(pattern, lowered)
        if not m:
            continue
        value = None
        if resolver:
            value = resolver(m)
        elif any(w in m.group(0) for w in WEEKDAYS):
            name = next(w for w in WEEKDAYS if w in m.group(0))
            back = (today.weekday() - WEEKDAYS.index(name)) % 7
            value = today - timedelta(days=back or (7 if m.group(0).startswith("last") else 0))
        else:
            value = _explicit_date(m, today)
        if value is None:
            continue
        day = value
        text = text[:m.start()] + " " + text[m.end():]
        break
    return text, day


def _explicit_date(m, today):
    from services.receipts import _safe_date

    g = [x for x in m.groups() if x is not None]
    text = m.group(0)
    try:
        if re.search(MONTH_WORD, text):
            number = int(next(x for x in g if x.isdigit()))
            month = MONTHS[next(x for x in g if not x.isdigit())[:3]]
            day_of_month = number
            year = today.year
        else:
            day_of_month, month = int(g[0]), int(g[1])
            year = int(g[2]) if len(g) > 2 else today.year
            if year < 100:
                year += 2000
    except (StopIteration, ValueError, KeyError):
        return None
    value = _safe_date(year, month, day_of_month, today)
    if value is None and len(g) < 3:
        value = _safe_date(year - 1, month, day_of_month, today)
    return value


def _keyword_category(words, table):
    text = " " + " ".join(words) + " "
    for category, keywords in table:
        if any(f" {k} " in text for k in keywords):
            return category
    return None


def parse_quick(text, today):
    """Return (fields, error). fields is a dict ready for validate_transaction."""
    raw = (text or "").strip()[:MAX_LENGTH]
    if not raw:
        return None, "Type something like “250 lunch”."

    kind = "expense"
    if raw.startswith("+"):
        kind, raw = "income", raw[1:]
    elif raw.startswith("-"):
        raw = raw[1:]

    rest, day = _strip_dates(raw, today)

    m = AMOUNT.search(rest)
    if not m:
        return None, "Add an amount, e.g. “250 lunch” or “lunch 180”."
    # "2k" -> 2000, "1.5 lakh" -> 150000
    multiplier = {"k": 1000, "lakh": 100000, "lac": 100000, "l": 100000}.get((m.group(3) or "").lower(), 1)
    value = Decimal(m.group(1).replace(",", "") + ("." + m.group(2) if m.group(2) else "")) * multiplier
    amount = f"{value.quantize(Decimal('0.01')):f}"
    rest = rest[:m.start()] + " " + rest[m.end():]

    if INCOME_WORDS.search(rest):
        kind = "income"

    words = [w for w in re.findall(r"[\w&'.@-]+", rest.lower()) if w not in FILLER]
    valid = INCOME_CATEGORIES if kind == "income" else EXPENSE_CATEGORIES

    # An explicit category name wins ("300 shopping"), and isn't repeated in the description.
    category = next((c for c in valid if c.lower() in words), None)
    description_words = [w for w in re.findall(r"[\w&'.@-]+", rest) if w.lower() not in FILLER]
    if category:
        description_words = [w for w in description_words if w.lower() != category.lower()]
    if not category:
        table = QUICK_INCOME_KEYWORDS if kind == "income" else QUICK_KEYWORDS
        category = _keyword_category(words, table) or guess_category(kind, " ".join(words), " ".join(words))

    description = " ".join(description_words).strip()
    if description:
        description = description[0].upper() + description[1:]

    return {
        "kind": kind,
        "amount": amount,
        "category": category if category in valid else "Other",
        "date": (day or today).isoformat(),
        "description": description[:200],
    }, None
