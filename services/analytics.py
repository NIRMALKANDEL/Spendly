"""Spending analysis queries and plain-language insights."""

from services.dates import (
    add_months,
    inclusive_days,
    month_end,
    month_key,
    month_label,
    month_start,
    timedelta,
)
from services.finance import savings_rate

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def totals(db, user_id, start, end):
    row = db.execute(
        """
        SELECT
            COALESCE(SUM(CASE WHEN kind = 'income'  THEN amount_cents END), 0) AS income,
            COALESCE(SUM(CASE WHEN kind = 'expense' THEN amount_cents END), 0) AS expense,
            COUNT(CASE WHEN kind = 'expense' THEN 1 END) AS expense_count
        FROM transactions
        WHERE user_id = ? AND date BETWEEN ? AND ?
        """,
        (user_id, start.isoformat(), end.isoformat()),
    ).fetchone()
    income, expense = row["income"], row["expense"]
    return {
        "income": income,
        "expense": expense,
        "net": income - expense,
        "expense_count": row["expense_count"],
        "savings_rate": savings_rate(income, expense),
    }


def category_totals(db, user_id, start, end, kind="expense"):
    rows = db.execute(
        """
        SELECT category, SUM(amount_cents) AS total, COUNT(*) AS count
        FROM transactions
        WHERE user_id = ? AND kind = ? AND date BETWEEN ? AND ?
        GROUP BY category
        ORDER BY total DESC, category
        """,
        (user_id, kind, start.isoformat(), end.isoformat()),
    ).fetchall()
    grand = sum(r["total"] for r in rows) or 1
    return [
        {"category": r["category"], "total": r["total"], "count": r["count"],
         "share": r["total"] / grand * 100}
        for r in rows
    ]


def monthly_series(db, user_id, keys):
    """Income/expense per month for the given YYYY-MM keys (oldest first)."""
    if not keys:
        return []
    rows = db.execute(
        """
        SELECT substr(date, 1, 7) AS month,
               COALESCE(SUM(CASE WHEN kind = 'income'  THEN amount_cents END), 0) AS income,
               COALESCE(SUM(CASE WHEN kind = 'expense' THEN amount_cents END), 0) AS expense
        FROM transactions
        WHERE user_id = ? AND date BETWEEN ? AND ?
        GROUP BY month
        """,
        (user_id, f"{keys[0]}-01", f"{keys[-1]}-31"),
    ).fetchall()
    by_month = {r["month"]: r for r in rows}
    series = []
    for key in keys:
        row = by_month.get(key)
        income = row["income"] if row else 0
        expense = row["expense"] if row else 0
        series.append({"key": key, "label": month_label(key), "income": income,
                       "expense": expense, "net": income - expense})
    return series


def month_keys_between(start, end):
    keys = []
    cursor = month_start(start)
    while cursor <= end:
        keys.append(month_key(cursor))
        cursor = add_months(cursor, 1)
    return keys


def category_by_month(db, user_id, keys):
    """{category: {month_key: cents}} for expenses across the given months."""
    if not keys:
        return {}
    rows = db.execute(
        """
        SELECT category, substr(date, 1, 7) AS month, SUM(amount_cents) AS total
        FROM transactions
        WHERE user_id = ? AND kind = 'expense' AND date BETWEEN ? AND ?
        GROUP BY category, month
        """,
        (user_id, f"{keys[0]}-01", f"{keys[-1]}-31"),
    ).fetchall()
    result = {}
    for r in rows:
        result.setdefault(r["category"], {})[r["month"]] = r["total"]
    return result


def weekday_totals(db, user_id, start, end):
    """Expense totals and per-day averages by weekday, Monday first."""
    rows = db.execute(
        """
        SELECT CAST(strftime('%w', date) AS INTEGER) AS dow, SUM(amount_cents) AS total
        FROM transactions
        WHERE user_id = ? AND kind = 'expense' AND date BETWEEN ? AND ?
        GROUP BY dow
        """,
        (user_id, start.isoformat(), end.isoformat()),
    ).fetchall()
    sums = [0] * 7
    for r in rows:
        sums[(r["dow"] + 6) % 7] += r["total"]  # SQLite: 0 = Sunday
    occurrences = [0] * 7
    day = start
    while day <= end:
        occurrences[day.weekday()] += 1
        day += timedelta(days=1)
    return [
        {"day": WEEKDAYS[i], "total": sums[i],
         "average": sums[i] / occurrences[i] if occurrences[i] else 0}
        for i in range(7)
    ]


def top_expenses(db, user_id, start, end, limit=8):
    return db.execute(
        """
        SELECT id, amount_cents, category, date, description
        FROM transactions
        WHERE user_id = ? AND kind = 'expense' AND date BETWEEN ? AND ?
        ORDER BY amount_cents DESC, date DESC
        LIMIT ?
        """,
        (user_id, start.isoformat(), end.isoformat(), limit),
    ).fetchall()


def cumulative_daily(db, user_id, month_first, through_day=None):
    """Running expense total for each day of a month."""
    last = month_end(month_first)
    rows = db.execute(
        """
        SELECT date, SUM(amount_cents) AS total
        FROM transactions
        WHERE user_id = ? AND kind = 'expense' AND date BETWEEN ? AND ?
        GROUP BY date
        """,
        (user_id, month_first.isoformat(), last.isoformat()),
    ).fetchall()
    by_day = {r["date"]: r["total"] for r in rows}
    running, series = 0, []
    for day in range(1, last.day + 1):
        if through_day is not None and day > through_day:
            break
        running += by_day.get(month_first.replace(day=day).isoformat(), 0)
        series.append(running)
    return series


def budget_status(db, user, month_first):
    """Per-category and overall budget progress for one month."""
    start, end = month_first, month_end(month_first)
    spent = {c["category"]: c["total"] for c in category_totals(db, user["id"], start, end)}
    rows = db.execute(
        "SELECT category, amount_cents FROM budgets WHERE user_id = ? ORDER BY category",
        (user["id"],),
    ).fetchall()
    categories = []
    for r in rows:
        used = spent.get(r["category"], 0)
        categories.append({
            "category": r["category"],
            "budget": r["amount_cents"],
            "spent": used,
            "remaining": r["amount_cents"] - used,
            "percent": used / r["amount_cents"] * 100,
        })
    categories.sort(key=lambda b: b["percent"], reverse=True)
    total_spent = sum(spent.values())
    overall = None
    if user["monthly_budget_cents"]:
        overall = {
            "budget": user["monthly_budget_cents"],
            "spent": total_spent,
            "remaining": user["monthly_budget_cents"] - total_spent,
            "percent": total_spent / user["monthly_budget_cents"] * 100,
        }
    return {"categories": categories, "overall": overall, "total_spent": total_spent}


def status_for(percent):
    if percent >= 100:
        return "critical"
    if percent >= 85:
        return "warning"
    return "good"


# ------------------------------------------------------------------ #
# Insights                                                            #
# ------------------------------------------------------------------ #

def _pct_change(current, previous):
    if not previous:
        return None
    return (current - previous) / previous * 100


def dashboard_insights(db, user, today, fmt):
    """Short, actionable observations about the current month."""
    uid = user["id"]
    insights = []
    this_first = month_start(today)
    prev_first = add_months(this_first, -1)

    spent_now = totals(db, uid, this_first, today)["expense"]
    comparable_end = prev_first.replace(day=min(today.day, month_end(prev_first).day))
    spent_then = totals(db, uid, prev_first, comparable_end)["expense"]
    change = _pct_change(spent_now, spent_then)
    if change is not None and abs(change) >= 5:
        tone = "good" if change < 0 else "warning"
        direction = "less" if change < 0 else "more"
        insights.append({
            "tone": tone,
            "text": f"You've spent {abs(change):.0f}% {direction} than at this point last month.",
        })

    days_elapsed = today.day
    days_total = month_end(today).day
    if spent_now and days_elapsed < days_total:
        projected = spent_now / days_elapsed * days_total
        text = f"At this pace you'll spend about {fmt(round(projected / 100) * 100)} this month."
        tone = "info"
        budget = user["monthly_budget_cents"]
        if budget:
            if projected > budget:
                tone = "warning"
                text += f" That's {fmt(round((projected - budget) / 100) * 100)} over your budget."
            else:
                tone = "good"
                text += " You're on track to stay within budget."
        insights.append({"tone": tone, "text": text})

    status = budget_status(db, user, this_first)
    over = [b["category"] for b in status["categories"] if b["percent"] >= 100]
    if over:
        insights.append({"tone": "critical", "text": f"Over budget in {', '.join(over)}."})

    last_month = totals(db, uid, prev_first, month_end(prev_first))
    if last_month["savings_rate"] is not None:
        rate = last_month["savings_rate"]
        tone = "good" if rate >= 20 else ("warning" if rate >= 0 else "critical")
        insights.append({
            "tone": tone,
            "text": f"Last month you saved {rate:.0f}% of your income"
                    + (" — nicely above the 20% rule of thumb." if rate >= 20 else "."),
        })
    return insights


def range_insights(db, user_id, start, end, fmt):
    """Observations about an arbitrary historical range (analytics page)."""
    insights = []
    cats = category_totals(db, user_id, start, end)
    if not cats:
        return insights

    top = cats[0]
    insights.append({
        "tone": "info",
        "text": f"{top['category']} is your largest spending category at {top['share']:.0f}% of the total.",
    })

    keys = month_keys_between(start, end)
    by_cat = category_by_month(db, user_id, keys)
    complete = [k for k in keys if k < month_key(end) or end == month_end(end)]
    if len(complete) >= 4:
        latest, previous = complete[-1], complete[-4:-1]
        best = None
        for category, months in by_cat.items():
            baseline = sum(months.get(k, 0) for k in previous) / 3
            current = months.get(latest, 0)
            if baseline >= 50000 and current:
                change = _pct_change(current, baseline)
                if best is None or abs(change) > abs(best[1]):
                    best = (category, change)
        if best and abs(best[1]) >= 15:
            category, change = best
            direction = "up" if change > 0 else "down"
            insights.append({
                "tone": "warning" if change > 0 else "good",
                "text": f"{category} spending in {month_label(latest)} was {direction} "
                        f"{abs(change):.0f}% versus the previous three-month average.",
            })

    week = weekday_totals(db, user_id, start, end)
    weekday_avg = sum(d["average"] for d in week[:5]) / 5
    weekend_avg = sum(d["average"] for d in week[5:]) / 2
    if weekday_avg and weekend_avg:
        ratio = weekend_avg / weekday_avg
        if ratio >= 1.15:
            insights.append({"tone": "info",
                             "text": f"You spend {ratio:.1f}× more per day on weekends than on weekdays."})
        elif ratio <= 0.85:
            insights.append({"tone": "info",
                             "text": "Your weekends are thriftier than your weekdays."})

    summary = totals(db, user_id, start, end)
    days = inclusive_days(start, end)
    if summary["expense"]:
        insights.append({
            "tone": "info",
            "text": f"Average daily spend: {fmt(round(summary['expense'] / days / 100) * 100)}.",
        })
    if summary["savings_rate"] is not None:
        rate = summary["savings_rate"]
        insights.append({
            "tone": "good" if rate >= 20 else ("warning" if rate >= 0 else "critical"),
            "text": f"You kept {rate:.0f}% of your income over this period.",
        })
    return insights

