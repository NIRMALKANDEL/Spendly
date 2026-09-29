"""Date helpers. Dates are stored as ISO strings (YYYY-MM-DD)."""

import calendar
from datetime import date, timedelta

MIN_DATE = date(2000, 1, 1)


def parse_date(raw):
    """Parse an ISO date string. Raises ValueError with a readable message."""
    try:
        value = date.fromisoformat(str(raw).strip())
    except (TypeError, ValueError):
        raise ValueError("Enter a valid date (YYYY-MM-DD).") from None
    return value


def parse_optional_date(raw):
    if raw is None or not str(raw).strip():
        return None
    try:
        return parse_date(raw)
    except ValueError:
        return None


def days_in_month(year, month):
    return calendar.monthrange(year, month)[1]


def add_months(d, months, anchor_day=None):
    """Move d by whole months, clamping to the month end (Jan 31 + 1 -> Feb 28).

    anchor_day keeps a recurring date from drifting: once clamped to the 28th,
    later months return to the 31st.
    """
    total = d.year * 12 + (d.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    day = min(anchor_day or d.day, days_in_month(year, month))
    return date(year, month, day)


def month_start(d):
    return d.replace(day=1)


def month_end(d):
    return d.replace(day=days_in_month(d.year, d.month))


def month_key(d):
    return f"{d.year:04d}-{d.month:02d}"


def parse_month(raw, default):
    """Parse "YYYY-MM" into the first day of that month."""
    try:
        year, month = str(raw).split("-")
        return date(int(year), int(month), 1)
    except (TypeError, ValueError):
        return default


def month_label(key):
    year, month = key.split("-")
    return f"{calendar.month_abbr[int(month)]} {year}"


def last_n_month_keys(today, n):
    """Month keys for the n months ending with today's month, oldest first."""
    return [month_key(add_months(month_start(today), -i)) for i in range(n - 1, -1, -1)]


def months_between(start, end):
    """Whole months from start until end (never negative)."""
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return max(months, 0)


def inclusive_days(start, end):
    return (end - start).days + 1



def today():
    """Today's date; tests pin it with app.config["FIXED_TODAY"]."""
    from flask import current_app, has_app_context

    if has_app_context() and current_app.config.get("FIXED_TODAY"):
        return current_app.config["FIXED_TODAY"]
    return date.today()
