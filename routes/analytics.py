from flask import Blueprint, g, render_template, request

from database.db import get_db
from services import analytics
from services.dates import add_months, month_start, parse_date, parse_optional_date, today
from services.money import format_money
from services.security import login_required

bp = Blueprint("analytics", __name__, url_prefix="/analytics")

RANGES = {
    "3m": ("Last 3 months", 3),
    "6m": ("Last 6 months", 6),
    "12m": ("Last 12 months", 12),
    "ytd": ("This year", None),
    "all": ("All time", None),
    "custom": ("Custom", None),
}


def resolve_range(args, db, user_id, now):
    key = args.get("range", "12m")
    if key not in RANGES:
        key = "12m"
    end = now
    if key in ("3m", "6m", "12m"):
        start = add_months(month_start(now), -(RANGES[key][1] - 1))
    elif key == "ytd":
        start = now.replace(month=1, day=1)
    elif key == "all":
        first = db.execute("SELECT MIN(date) FROM transactions WHERE user_id = ?", (user_id,)).fetchone()[0]
        start = parse_date(first) if first else month_start(now)
        start = min(start, now)
    else:
        start = parse_optional_date(args.get("start")) or add_months(month_start(now), -2)
        end = parse_optional_date(args.get("end")) or now
        if start > end:
            start, end = end, start
    return key, start, end


@bp.route("/")
@login_required
def index():
    db = get_db()
    user = g.user
    uid = user["id"]
    now = today()
    range_key, start, end = resolve_range(request.args, db, uid, now)

    def fmt(cents):
        return format_money(cents, user["currency"])

    summary = analytics.totals(db, uid, start, end)
    keys = analytics.month_keys_between(start, end)
    monthly = analytics.monthly_series(db, uid, keys)
    categories = analytics.category_totals(db, uid, start, end)
    income_categories = analytics.category_totals(db, uid, start, end, kind="income")
    weekdays = analytics.weekday_totals(db, uid, start, end)
    by_cat_month = analytics.category_by_month(db, uid, keys[-6:])
    months_with_spend = [m for m in monthly if m["expense"]]

    chart_data = {
        "monthly": {
            "labels": [m["label"] for m in monthly],
            "income": [m["income"] for m in monthly],
            "expense": [m["expense"] for m in monthly],
        },
        "categories": {
            "labels": [c["category"] for c in categories],
            "values": [c["total"] for c in categories],
        },
        "weekdays": {
            "labels": [d["day"] for d in weekdays],
            "values": [round(d["average"]) for d in weekdays],
        },
    }
    return render_template(
        "analytics.html",
        ranges=RANGES,
        range_key=range_key,
        start=start,
        end=end,
        summary=summary,
        monthly=monthly,
        categories=categories,
        income_categories=income_categories,
        top=analytics.top_expenses(db, uid, start, end),
        insights=analytics.range_insights(db, uid, start, end, fmt),
        avg_month=(sum(m["expense"] for m in months_with_spend) / len(months_with_spend)
                   if months_with_spend else 0),
        heat_keys=keys[-6:],
        by_cat_month=by_cat_month,
        chart_data=chart_data,
    )
