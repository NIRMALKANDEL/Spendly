"""Turn payment-receipt text into a draft transaction.

The text comes from on-device OCR of a GPay / PhonePe / Paytm / BHIM
screenshot, from text shared by those apps, or from a bank SMS. OCR is
imperfect (the ₹ sign is often read as %, 2 or 7), so every field is a best
guess that the user confirms before anything is saved.
"""

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from services.categories import EXPENSE_CATEGORIES, INCOME_CATEGORIES
from services.money import cents_to_input

MAX_TEXT_LENGTH = 20_000
MAX_AMOUNT_CENTS = 10_000_000_00  # ₹1 crore: anything above is almost surely an ID

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
MONTH_RE = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"

# A number such as 250, 1,250.50 or 1,23,456 (Indian grouping).
NUMBER = r"(\d{1,3}(?:,\d{2,3})+|\d+)(?:\.(\d{1,2}))?"
CURRENCY = r"(?:₹|rs\.?|inr|rupees?)"
# Characters OCR commonly produces in place of ₹ when it sits right before digits.
RUPEE_LOOKALIKES = "%=?¥€£$&zZ"
# ...and digits it sometimes becomes when glued to the amount ("₹349" -> "3349").
RUPEE_DIGIT_MISREADS = "23479"

AMOUNT_LABELS = re.compile(
    r"\b(amount|amt|total|paid|debited|sent|payment of|txn amt|transferred|received|credited)\b", re.I)
DATE_OR_TIME = re.compile(r"\d{1,2}:\d{2}|\b(am|pm)\b", re.I)

APPS = [
    ("Google Pay", r"google\s*pay|\bg\s?pay\b"),
    ("PhonePe", r"phone\s*pe"),
    ("Paytm", r"paytm"),
    ("BHIM", r"\bbhim\b"),
    ("Amazon Pay", r"amazon\s*pay"),
    ("CRED", r"\bcred\b"),
    ("WhatsApp Pay", r"whatsapp"),
    ("MobiKwik", r"mobikwik"),
]

# Checked in order; first keyword hit wins. Brands before generic words.
CATEGORY_KEYWORDS = [
    ("Food", ["swiggy", "zomato", "domino", "pizza", "kfc", "mcdonald", "burger", "starbucks", "cafe", "café",
              "coffee", "restaurant", "dhaba", "biryani", "bakery", "eatery", "food", "chai", "juice", "canteen"]),
    ("Groceries", ["bigbasket", "big basket", "blinkit", "zepto", "instamart", "grofers", "dmart", "d-mart",
                   "jiomart", "reliance fresh", "more retail", "grocery", "groceries", "supermarket", "kirana",
                   "vegetable", "fruits", "provision", "general store", "mart"]),
    ("Travel", ["irctc", "makemytrip", "goibibo", "redbus", "cleartrip", "ixigo", "indigo", "air india", "vistara",
                "spicejet", "akasa", "oyo", "airbnb", "hotel booking", "flight", "train ticket"]),
    ("Transport", ["uber", "ola", "rapido", "namma yatri", "metro", "fastag", "petrol", "diesel", "fuel",
                   "indian oil", "iocl", "bharat petroleum", "bpcl", "hindustan petroleum", "hpcl", "shell",
                   "parking", "toll", "auto", "cab", "taxi", "bus pass"]),
    ("Bills", ["electricity", "bescom", "tneb", "msedcl", "bses", "tata power", "airtel", "jio", "vodafone",
               "vi recharge", "bsnl", "recharge", "broadband", "wifi", "water bill", "gas bill", "lpg", "indane",
               "bharat gas", "dth", "tata play", "insurance", "emi", "credit card bill", "bill payment", "postpaid"]),
    ("Rent", ["rent", "landlord", "house owner", "pg ", "hostel", "nobroker"]),
    ("Health", ["pharmacy", "medical", "chemist", "apollo", "medplus", "1mg", "pharmeasy", "netmeds", "hospital",
                "clinic", "doctor", "diagnostic", "lab", "dental", "gym", "cult.fit", "cultfit"]),
    ("Entertainment", ["netflix", "spotify", "hotstar", "prime video", "youtube", "bookmyshow", "pvr", "inox",
                       "cinema", "movie", "gaming", "steam", "playstation", "zee5", "sonyliv", "jiocinema"]),
    ("Shopping", ["amazon", "flipkart", "myntra", "ajio", "meesho", "nykaa", "croma", "reliance digital",
                  "decathlon", "lifestyle", "shoppers stop", "zara", "h&m", "ikea", "store", "shop", "fashion"]),
    ("Education", ["udemy", "coursera", "byju", "unacademy", "vedantu", "school", "college", "university",
                   "tuition", "coaching", "course", "exam fee", "books", "stationery"]),
]
INCOME_KEYWORDS = [
    ("Salary", ["salary", "payroll", "wages"]),
    ("Investment", ["dividend", "interest", "mutual fund", "zerodha", "groww"]),
    ("Freelance", ["freelance", "invoice", "upwork", "fiverr"]),
]

INCOME_HINTS = re.compile(
    r"\b(received\s+from|money\s+received|you\s+received|has\s+been\s+credited|credited\s+(?:to|in)\s+your"
    r"|credited\s+with|cashback\s+received|refund\s+(?:of|received)|received\s+successfully)\b", re.I)
EXPENSE_HINTS = re.compile(
    r"\b(paid\s+to|paid\s+successfully|payment\s+successful|debited|sent\s+to|money\s+sent|you\s+paid"
    r"|transferred\s+to|payment\s+to)\b", re.I)

PAYEE_LINE = re.compile(
    r"^(?:paid\s+successfully\s+to|money\s+sent\s+to|payment\s+to|transferred\s+to|paid\s+to|sent\s+to"
    r"|paying|to)\b\s*[:\-]?\s*(.*)$", re.I)
PAYER_LINE = re.compile(
    r"^(?:money\s+received\s+from|received\s+from|credited\s+by|from)\b\s*[:\-]?\s*(.*)$", re.I)
# Name ends at a keyword, a bracket, a comma/semicolon, a sentence-ending full
# stop (not the dot inside "okaxis.com" or a VPA) or the end of the line.
_NAME_END = r"(?=\s*[(\[]|[,;\n]|\.(?:\s|$)|$|\s+(?:on|via|using|ref|refno|upi|from|for|to|in|a/c|is|was)\b)"
INLINE_PAYEE = re.compile(
    r"\b(?:paid|sent|trf|transferred|payment|debited)\b[^\n]{0,60}?\bto\s+(?:vpa\s+)?"
    r"([A-Za-z0-9][\w .&'@/-]{1,50}?)" + _NAME_END, re.I)
INLINE_PAYER = re.compile(
    r"\breceived\b[^\n]{0,40}?\bfrom\s+(?:vpa\s+)?"
    r"([A-Za-z0-9][\w .&'@/-]{1,50}?)" + _NAME_END, re.I)

REFERENCE_PATTERNS = [
    re.compile(r"(?:upi\s*(?:transaction|txn|ref(?:erence)?)\.?\s*(?:id|no\.?|number)?|\butr(?:\s*no\.?)?"
               r"|\brrn|\bref\s*no\.?|\brefno)\s*[:#.\-]?\s*(\d{12})(?!\d)", re.I),
    re.compile(r"(?:transaction|txn|order|reference)\.?\s*(?:id|no\.?|number)\s*[:#.\-]?\s*([A-Za-z0-9]{10,35})\b",
               re.I),
    re.compile(r"(?<![\d,.])(\d{12})(?![\d,.])"),  # a bare 12-digit UPI RRN
]

NOT_A_NAME = re.compile(
    r"^(?:\W*|₹.*|rs\.?\s*\d.*|\d[\d,. ]*|.*successful.*|.*completed.*|upi.*|google pay|phonepe|paytm"
    r"|banking name.*|split.*|share.*|view.*|done|pay again|check balance)$", re.I)


@dataclass
class Receipt:
    kind: str = "expense"
    amount_cents: int | None = None
    date: str | None = None
    payee: str | None = None
    reference: str | None = None
    category: str = "Other"
    app: str | None = None
    found: set = field(default_factory=set)

    def to_form(self, today):
        """Values for the transaction form. Missing fields get safe defaults."""
        description = self.payee or (f"{self.app} payment" if self.app else "")
        return {
            "kind": self.kind,
            "amount": cents_to_input(self.amount_cents) if self.amount_cents else "",
            "category": self.category,
            "date": self.date or today.isoformat(),
            "description": description[:200],
            "reference": self.reference or "",
        }


# ------------------------------------------------------------------ #
# Field extractors                                                    #
# ------------------------------------------------------------------ #

def normalise(text):
    text = (text or "")[:MAX_TEXT_LENGTH].replace("\r", "\n").replace("₹", "₹")
    lines = [re.sub(r"[ \t ]+", " ", line).strip() for line in text.split("\n")]
    return [line for line in lines if line]


def _to_cents(whole, frac):
    digits = whole.replace(",", "")
    if not digits or len(digits) > 9:
        return None
    cents = int(digits) * 100 + (int((frac or "0").ljust(2, "0")[:2]) if frac else 0)
    return cents if 0 < cents <= MAX_AMOUNT_CENTS else None


def find_amount(lines):
    """Best-guess payment amount in cents, or None."""
    candidates = []  # (score, order, cents, raw)
    order = 0
    for i, line in enumerate(lines):
        labelled = bool(AMOUNT_LABELS.search(line))
        near = " ".join(lines[max(0, i - 1): i + 2])
        for m in re.finditer(CURRENCY + r"\s*" + NUMBER, line, re.I):
            cents = _to_cents(m.group(1), m.group(2))
            if cents:
                candidates.append((5 + labelled, order, cents, m.group(0)))
                order += 1
        # "%250", "¥ 1,284", "£4 1,284": a rupee sign misread by OCR (sometimes with a stray
        # digit split off by a space), ending the line.
        m = re.search(r"(?:^|\s)[" + re.escape(RUPEE_LOOKALIKES) + r"](?:\d\s)?\s?" + NUMBER + r"$", line)
        if m and (cents := _to_cents(m.group(1), m.group(2))):
            candidates.append((4, order, cents, m.group(0)))
            order += 1
        # A line that is only a number, next to "paid"/"completed" — the big headline amount
        # when OCR dropped the ₹ sign entirely.
        m = re.match(r"^" + NUMBER + r"$", line)
        if m and re.search(r"paid|success|complete|sent|received|debited|credited", near, re.I):
            if (cents := _to_cents(m.group(1), m.group(2))) and not re.fullmatch(r"(19|20)\d\d", m.group(1)):
                candidates.append((3, order, cents, line))
                order += 1
        # "Amount: 250.00", "debited by 1,250" — labelled numbers with money formatting.
        if labelled and not DATE_OR_TIME.search(line):
            for m in re.finditer(r"(?<![\w@])" + NUMBER + r"(?![\w@])", line):
                if (m.group(2) or "," in m.group(1)) and (cents := _to_cents(m.group(1), m.group(2))):
                    candidates.append((2, order, cents, m.group(0)))
                    order += 1
    if not candidates:
        return None
    candidates.sort(key=lambda c: (-c[0], c[1]))
    best = candidates[0]
    # "₹349" read as "3349": if the same number minus its first digit was also found,
    # the shorter one is the real amount.
    values = {c[2] for c in candidates}
    whole, paise = divmod(best[2], 100)
    digits = str(whole)
    if len(digits) > 1 and digits[0] in RUPEE_DIGIT_MISREADS:
        shorter = int(digits[1:]) * 100 + paise
        if shorter in values and shorter:
            return shorter
    return best[2]


def _safe_date(year, month, day, today):
    try:
        value = date(year, month, day)
    except ValueError:
        return None
    if value > today + timedelta(days=1) or value.year < 2000:
        return None
    return value


def find_date(lines, today):
    text = "\n".join(lines)
    patterns = [
        # Dates never span lines, so only spaces/dashes may separate the parts.
        (r"(?<![\d₹.,])\b(\d{1,2})(?:st|nd|rd|th)?[ \-]+" + MONTH_RE + r"(?![a-z])[ ,\-]*(\d{4})?(?!\d)", "dmy"),
        (r"\b" + MONTH_RE + r"(?![a-z]) +(\d{1,2})(?!\d)(?:st|nd|rd|th)?,? *(\d{4})?(?!\d)", "mdy"),
        (r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", "iso"),
        (r"\b(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})\b", "numeric"),
    ]
    found = []
    for pattern, style in patterns:
        for m in re.finditer(pattern, text, re.I):
            g = m.groups()
            if style == "dmy":
                day, month, year = int(g[0]), MONTHS[g[1][:3].lower()], g[2]
            elif style == "mdy":
                month, day, year = MONTHS[g[0][:3].lower()], int(g[1]), g[2]
            elif style == "iso":
                year, month, day = g
            else:  # Indian order: dd/mm/yyyy
                day, month, year = int(g[0]), int(g[1]), g[2]
                if year and len(year) == 2:
                    year = "20" + year
            if year is None:
                # No year shown ("12 Sep, 10:30 pm"): this year, or last year if that's in the future.
                candidate = _safe_date(today.year, int(month), int(day), today)
                value = candidate or _safe_date(today.year - 1, int(month), int(day), today)
            else:
                value = _safe_date(int(year), int(month), int(day), today)
            if value:
                found.append((m.start(), value))
    if found:
        return min(found)[1]
    if re.search(r"\byesterday\b", text, re.I):
        return today - timedelta(days=1)
    if re.search(r"\btoday\b", text, re.I):
        return today
    return None


def find_reference(lines):
    text = "\n".join(lines)
    for pattern in REFERENCE_PATTERNS:
        m = pattern.search(text)
        if m:
            return m.group(1)[:40]
    return None


def clean_name(raw):
    name = re.sub(r"\b[\w.\-]+@[a-z][\w.\-]*\b", "", raw, flags=re.I).strip()  # drop UPI IDs
    if not name and "@" in raw:
        name = raw.split("@", 1)[0].replace(".", " ")
    name = re.sub(r"\s{2,}", " ", name).strip(" :-–·,.|")
    # OCR often puts the amount on the payee's line ("Blinkit £4 1,284"): drop trailing
    # tokens that are amounts or currency marks.
    tokens = name.split(" ")
    while len(tokens) > 1 and re.fullmatch(
            r"[₹" + re.escape(RUPEE_LOOKALIKES) + r"]?[\d,.]*\d[\d,.]*|[₹" + re.escape(RUPEE_LOOKALIKES) + r"]|rs\.?",
            tokens[-1], re.I):
        tokens.pop()
    name = " ".join(tokens)
    name = re.sub(r"^(?:mr|mrs|ms)\.?\s+", "", name, flags=re.I)
    if not name or NOT_A_NAME.match(name) or len(name) < 2:
        return None
    # Dates, times and number-heavy lines ("12 Sep 2026", "XXXX1234") aren't names.
    digits = sum(ch.isdigit() for ch in name)
    if (digits / len(name) > 0.3 or DATE_OR_TIME.search(name)
            or re.search(r"\d\s*" + MONTH_RE + r"(?![a-z])", name, re.I)):
        return None
    if name.isupper() and len(name) > 3:
        name = name.title()
    return name[:60]


def find_counterparty(lines, kind):
    """Who was paid (expense) or who paid you (income)."""
    line_pattern = PAYER_LINE if kind == "income" else PAYEE_LINE
    for i, line in enumerate(lines):
        m = line_pattern.match(line)
        if not m:
            continue
        name = clean_name(m.group(1))
        if not name:
            for nxt in lines[i + 1: i + 3]:
                name = clean_name(nxt)
                if name:
                    break
        if name:
            return name
    inline = INLINE_PAYER if kind == "income" else INLINE_PAYEE
    m = inline.search("\n".join(lines))
    if m:
        return clean_name(m.group(1))
    return None


def detect_kind(text):
    if INCOME_HINTS.search(text) and not EXPENSE_HINTS.search(text):
        return "income"
    return "expense"


def detect_app(text):
    for name, pattern in APPS:
        if re.search(pattern, text, re.I):
            return name
    return None


def _contains(haystack, keyword):
    return re.search(r"(?<![a-z])" + re.escape(keyword.strip()) + r"(?![a-z])", haystack) is not None


def guess_category(kind, payee, text):
    table = INCOME_KEYWORDS if kind == "income" else CATEGORY_KEYWORDS
    valid = INCOME_CATEGORIES if kind == "income" else EXPENSE_CATEGORIES
    # The payee name is the strongest signal; fall back to the whole receipt.
    for haystack in filter(None, [(payee or "").lower(), text.lower()]):
        for category, keywords in table:
            if any(_contains(haystack, k) for k in keywords):
                return category if category in valid else "Other"
    return "Other"


# ------------------------------------------------------------------ #
# Entry points                                                        #
# ------------------------------------------------------------------ #

def parse_receipt_text(text, today):
    lines = normalise(text)
    joined = "\n".join(lines)
    receipt = Receipt(kind=detect_kind(joined), app=detect_app(joined))

    receipt.amount_cents = find_amount(lines)
    day = find_date(lines, today)
    receipt.date = day.isoformat() if day else None
    receipt.payee = find_counterparty(lines, receipt.kind)
    receipt.reference = find_reference(lines)
    receipt.category = guess_category(receipt.kind, receipt.payee, joined)

    for name in ("amount_cents", "date", "payee", "reference"):
        if getattr(receipt, name):
            receipt.found.add(name.replace("_cents", ""))
    if receipt.category != "Other":
        receipt.found.add("category")
    return receipt


def receipt_from_fields(data, today):
    """Build a Receipt from structured fields (e.g. an AI extractor's JSON).

    Every value is re-validated here, so a model can't smuggle in anything the
    text parser wouldn't accept.
    """
    from services.money import parse_amount

    receipt = Receipt()
    receipt.kind = "income" if str(data.get("type") or data.get("kind") or "").lower() == "income" else "expense"
    try:
        receipt.amount_cents = parse_amount(data.get("amount")) if data.get("amount") not in (None, "") else None
    except ValueError:
        receipt.amount_cents = None
    raw_date = str(data.get("date") or "")
    try:
        parsed = date.fromisoformat(raw_date[:10])
        receipt.date = parsed.isoformat() if _safe_date(parsed.year, parsed.month, parsed.day, today) else None
    except ValueError:
        receipt.date = None
    receipt.payee = clean_name(str(data.get("payee") or data.get("merchant") or "")) or None
    reference = re.sub(r"[^A-Za-z0-9]", "", str(data.get("reference") or ""))
    receipt.reference = reference[:40] or None
    valid = INCOME_CATEGORIES if receipt.kind == "income" else EXPENSE_CATEGORIES
    category = str(data.get("category") or "")
    receipt.category = category if category in valid else guess_category(receipt.kind, receipt.payee, "")
    receipt.app = str(data.get("app"))[:30] if data.get("app") else None
    for name in ("amount_cents", "date", "payee", "reference"):
        if getattr(receipt, name):
            receipt.found.add(name.replace("_cents", ""))
    if receipt.category != "Other":
        receipt.found.add("category")
    return receipt
