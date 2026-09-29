from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from database.db import get_db
from routes.transactions import validate_transaction
from services.categories import CATEGORIES, FREQUENCIES
from services.dates import parse_date, today
from services.recurring import advance, run_due
from services.security import login_required

bp = Blueprint("recurring", __name__, url_prefix="/recurring")

MAX_RULES = 100


def get_owned_rule(rule_id):
    rule = get_db().execute(
        "SELECT * FROM recurring WHERE id = ? AND user_id = ?", (rule_id, g.user["id"])
    ).fetchone()
    if rule is None:
        abort(404)
    return rule


@bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    db = get_db()
    uid = g.user["id"]
    error = None
    form = {"kind": "expense", "date": today().isoformat(), "frequency": "monthly"}
    if request.method == "POST":
        form = request.form
        clean, error = validate_transaction(request.form)
        frequency = request.form.get("frequency")
        if not error and frequency not in FREQUENCIES:
            error = "Choose how often this repeats."
        count = db.execute("SELECT COUNT(*) FROM recurring WHERE user_id = ?", (uid,)).fetchone()[0]
        if not error and count >= MAX_RULES:
            error = f"You can have up to {MAX_RULES} recurring items."
        if not error:
            start = parse_date(clean["date"])
            db.execute(
                "INSERT INTO recurring (user_id, kind, amount_cents, category, description, frequency,"
                " anchor_day, next_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (uid, clean["kind"], clean["amount_cents"], clean["category"], clean["description"],
                 frequency, start.day, clean["date"]),
            )
            db.commit()
            created = run_due(db, uid, today())
            message = "Recurring item saved."
            if created:
                message += f" {created} past occurrence{'s' if created != 1 else ''} added to your transactions."
            flash(message, "success")
            return redirect(url_for("recurring.index"))

    rules = db.execute(
        "SELECT * FROM recurring WHERE user_id = ? ORDER BY active DESC, next_date", (uid,)
    ).fetchall()
    monthly_factor = {"weekly": 52 / 12, "monthly": 1, "yearly": 1 / 12}
    monthly = {"expense": 0, "income": 0}
    for rule in rules:
        if rule["active"]:
            monthly[rule["kind"]] += rule["amount_cents"] * monthly_factor[rule["frequency"]]
    return render_template(
        "recurring.html",
        rules=rules,
        form=form,
        error=error,
        categories=CATEGORIES,
        frequencies=FREQUENCIES,
        monthly={k: round(v) for k, v in monthly.items()},
    ), (400 if error else 200)


@bp.route("/<int:rule_id>/toggle", methods=["POST"])
@login_required
def toggle(rule_id):
    rule = get_owned_rule(rule_id)
    next_date = parse_date(rule["next_date"])
    if not rule["active"]:
        # Resuming skips the occurrences missed while paused instead of backfilling them.
        while next_date < today():
            next_date = advance(next_date, rule["frequency"], rule["anchor_day"])
    db = get_db()
    db.execute("UPDATE recurring SET active = ?, next_date = ? WHERE id = ? AND user_id = ?",
               (0 if rule["active"] else 1, next_date.isoformat(), rule_id, g.user["id"]))
    db.commit()
    flash("Recurring item " + ("paused." if rule["active"] else "resumed."), "success")
    return redirect(url_for("recurring.index"))


@bp.route("/<int:rule_id>/delete", methods=["POST"])
@login_required
def delete(rule_id):
    get_owned_rule(rule_id)
    db = get_db()
    db.execute("DELETE FROM recurring WHERE id = ? AND user_id = ?", (rule_id, g.user["id"]))
    db.commit()
    flash("Recurring item deleted. Transactions it already created were kept.", "success")
    return redirect(url_for("recurring.index"))
