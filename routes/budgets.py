from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from database.db import get_db
from services import analytics
from services.categories import EXPENSE_CATEGORIES
from services.dates import add_months, month_end, month_start, parse_month, today
from services.money import parse_amount
from services.security import login_required

bp = Blueprint("budgets", __name__, url_prefix="/budgets")


@bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    db = get_db()
    uid = g.user["id"]

    if request.method == "POST":
        errors = []
        overall_raw = request.form.get("overall", "").strip()
        overall = 0
        if overall_raw:
            try:
                overall = parse_amount(overall_raw, allow_zero=True)
            except ValueError as exc:
                errors.append(f"Overall budget: {exc}")
        updates = {}
        for category in EXPENSE_CATEGORIES:
            raw = request.form.get(f"budget_{category}", "").strip()
            if not raw:
                updates[category] = None
                continue
            try:
                updates[category] = parse_amount(raw, allow_zero=True) or None
            except ValueError as exc:
                errors.append(f"{category}: {exc}")
        if errors:
            for message in errors:
                flash(message, "error")
            return redirect(url_for("budgets.index"))

        db.execute("UPDATE users SET monthly_budget_cents = ? WHERE id = ?", (overall, uid))
        for category, cents in updates.items():
            if cents is None:
                db.execute("DELETE FROM budgets WHERE user_id = ? AND category = ?", (uid, category))
            else:
                db.execute(
                    "INSERT INTO budgets (user_id, category, amount_cents) VALUES (?, ?, ?)"
                    " ON CONFLICT(user_id, category) DO UPDATE SET amount_cents = excluded.amount_cents",
                    (uid, category, cents),
                )
        db.commit()
        flash("Budgets saved.", "success")
        return redirect(url_for("budgets.index"))

    current = month_start(today())
    month = parse_month(request.args.get("month"), current)
    if month > current:
        month = current
    status = analytics.budget_status(db, g.user, month)
    existing = {
        r["category"]: r["amount_cents"]
        for r in db.execute("SELECT category, amount_cents FROM budgets WHERE user_id = ?", (uid,))
    }
    spent = {c["category"]: c["total"]
             for c in analytics.category_totals(db, uid, month, month_end(month))}
    return render_template(
        "budgets.html",
        status=status,
        existing=existing,
        spent=spent,
        categories=EXPENSE_CATEGORIES,
        month=month,
        prev_month=add_months(month, -1),
        next_month=add_months(month, 1) if month < current else None,
        status_for=analytics.status_for,
    )
