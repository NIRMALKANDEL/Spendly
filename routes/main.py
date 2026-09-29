from flask import Blueprint, current_app, g, redirect, render_template, send_from_directory, url_for

from database.db import get_db
from services import analytics
from services.dates import add_months, last_n_month_keys, month_end, month_start, today
from services.money import format_money
from services.security import login_required

bp = Blueprint("main", __name__)


@bp.route("/")
def landing():
    if g.user:
        return redirect(url_for("main.dashboard"))
    return render_template("landing.html")


@bp.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    user = g.user
    uid = user["id"]
    now = today()
    this_first = month_start(now)
    prev_first = add_months(this_first, -1)

    def fmt(cents):
        return format_money(cents, user["currency"])

    this_month = analytics.totals(db, uid, this_first, month_end(now))
    last_month = analytics.totals(db, uid, prev_first, month_end(prev_first))
    trend = analytics.monthly_series(db, uid, last_n_month_keys(now, 6))
    categories = analytics.category_totals(db, uid, this_first, month_end(now))
    budget = analytics.budget_status(db, user, this_first)
    recent = db.execute(
        "SELECT * FROM transactions WHERE user_id = ? ORDER BY date DESC, id DESC LIMIT 6",
        (uid,),
    ).fetchall()
    goals = db.execute(
        "SELECT * FROM goals WHERE user_id = ? ORDER BY (saved_cents * 1.0 / target_cents) DESC LIMIT 3",
        (uid,),
    ).fetchall()
    has_any = db.execute("SELECT 1 FROM transactions WHERE user_id = ? LIMIT 1", (uid,)).fetchone()

    pace = {
        "labels": list(range(1, month_end(now).day + 1)),
        "this_month": analytics.cumulative_daily(db, uid, this_first, through_day=now.day),
        "last_month": analytics.cumulative_daily(db, uid, prev_first),
        "budget": user["monthly_budget_cents"],
    }
    chart_data = {
        "trend": {
            "labels": [m["label"] for m in trend],
            "income": [m["income"] for m in trend],
            "expense": [m["expense"] for m in trend],
        },
        "pace": pace,
    }

    return render_template(
        "dashboard.html",
        this_month=this_month,
        last_month=last_month,
        categories=categories,
        budget=budget,
        recent=recent,
        goals=goals,
        has_any=bool(has_any),
        insights=analytics.dashboard_insights(db, user, now, fmt),
        chart_data=chart_data,
        month_name=now.strftime("%B %Y"),
        status_for=analytics.status_for,
    )


@bp.route("/calculators")
def calculators():
    """Savings, goal, emergency-fund and loan calculators (all client-side)."""
    avg_expense = None
    if g.user:
        now = today()
        start = add_months(month_start(now), -3)
        end = month_end(add_months(month_start(now), -1))
        spent = analytics.totals(get_db(), g.user["id"], start, end)["expense"]
        if spent:
            avg_expense = round(spent / 3 / 100)
    return render_template("calculators.html", avg_expense=avg_expense)


@bp.route("/privacy")
def privacy():
    return render_template("legal/privacy.html")


@bp.route("/terms")
def terms():
    return render_template("legal/terms.html")


@bp.route("/sw.js")
def service_worker():
    """Served from the root so its scope covers the whole app (needed for the share target)."""
    response = send_from_directory(current_app.static_folder, "js/sw.js", mimetype="application/javascript",
                                   max_age=0)
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Service-Worker-Allowed"] = "/"
    return response
