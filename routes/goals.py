import math

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from database.db import get_db
from services.dates import months_between, parse_date, today
from services.finance import required_monthly_saving
from services.money import cents_to_input, parse_amount
from services.security import login_required

bp = Blueprint("goals", __name__, url_prefix="/goals")

MAX_GOALS = 50


def validate_goal(form):
    name = (form.get("name") or "").strip()
    if not name or len(name) > 60:
        return None, "Goal name is required (max 60 characters)."
    try:
        target = parse_amount(form.get("target"))
        saved_raw = (form.get("saved") or "").strip()
        saved = parse_amount(saved_raw, allow_zero=True) if saved_raw else 0
    except ValueError as exc:
        return None, str(exc)
    target_date = None
    if (form.get("target_date") or "").strip():
        try:
            target_date = parse_date(form.get("target_date")).isoformat()
        except ValueError as exc:
            return None, str(exc)
    return {"name": name, "target_cents": target, "saved_cents": saved, "target_date": target_date}, None


def describe_goal(goal, now):
    """Progress figures and a plain status for one goal."""
    target, saved = goal["target_cents"], goal["saved_cents"]
    info = {
        "goal": goal,
        "percent": min(saved / target * 100, 100),
        "remaining": max(target - saved, 0),
        "months_left": None,
        "monthly_needed": None,
        "status": "open",
    }
    if saved >= target:
        info["status"] = "complete"
        return info
    if goal["target_date"]:
        deadline = parse_date(goal["target_date"])
        if deadline < now:
            info["status"] = "overdue"
        else:
            months = max(months_between(now, deadline), 1)
            info["months_left"] = months
            needed = required_monthly_saving(target, saved, 0, months)
            info["monthly_needed"] = math.ceil(needed / 100) * 100  # whole units, rounded up
            info["status"] = "scheduled"
    return info


def get_owned_goal(goal_id):
    goal = get_db().execute(
        "SELECT * FROM goals WHERE id = ? AND user_id = ?", (goal_id, g.user["id"])
    ).fetchone()
    if goal is None:
        abort(404)
    return goal


@bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    db = get_db()
    uid = g.user["id"]
    form, error = {}, None
    if request.method == "POST":
        form = request.form
        clean, error = validate_goal(request.form)
        count = db.execute("SELECT COUNT(*) FROM goals WHERE user_id = ?", (uid,)).fetchone()[0]
        if not error and count >= MAX_GOALS:
            error = f"You can have up to {MAX_GOALS} goals."
        if not error:
            db.execute(
                "INSERT INTO goals (user_id, name, target_cents, saved_cents, target_date) VALUES (?, ?, ?, ?, ?)",
                (uid, clean["name"], clean["target_cents"], clean["saved_cents"], clean["target_date"]),
            )
            db.commit()
            flash(f"Goal “{clean['name']}” created.", "success")
            return redirect(url_for("goals.index"))

    now = today()
    goals = [describe_goal(row, now) for row in db.execute(
        "SELECT * FROM goals WHERE user_id = ? ORDER BY target_date IS NULL, target_date, id", (uid,))]
    totals = {
        "target": sum(i["goal"]["target_cents"] for i in goals),
        "saved": sum(min(i["goal"]["saved_cents"], i["goal"]["target_cents"]) for i in goals),
        "monthly": sum(i["monthly_needed"] or 0 for i in goals),
    }
    return render_template("goals/index.html", goals=goals, totals=totals, form=form,
                           error=error), (400 if error else 200)


@bp.route("/<int:goal_id>/edit", methods=["GET", "POST"])
@login_required
def edit(goal_id):
    goal = get_owned_goal(goal_id)
    error = None
    form = {
        "name": goal["name"],
        "target": cents_to_input(goal["target_cents"]),
        "saved": cents_to_input(goal["saved_cents"]),
        "target_date": goal["target_date"] or "",
    }
    if request.method == "POST":
        form = request.form
        clean, error = validate_goal(request.form)
        if not error:
            db = get_db()
            db.execute(
                "UPDATE goals SET name = ?, target_cents = ?, saved_cents = ?, target_date = ?"
                " WHERE id = ? AND user_id = ?",
                (clean["name"], clean["target_cents"], clean["saved_cents"], clean["target_date"],
                 goal_id, g.user["id"]),
            )
            db.commit()
            flash("Goal updated.", "success")
            return redirect(url_for("goals.index"))
    return render_template("goals/edit.html", goal=goal, form=form, error=error), (400 if error else 200)


@bp.route("/<int:goal_id>/contribute", methods=["POST"])
@login_required
def contribute(goal_id):
    goal = get_owned_goal(goal_id)
    try:
        amount = parse_amount(request.form.get("amount"))
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("goals.index"))
    withdraw = request.form.get("action") == "withdraw"
    if withdraw and amount > goal["saved_cents"]:
        flash("You can't withdraw more than you've saved.", "error")
        return redirect(url_for("goals.index"))
    new_saved = goal["saved_cents"] + (-amount if withdraw else amount)
    db = get_db()
    db.execute("UPDATE goals SET saved_cents = ? WHERE id = ? AND user_id = ?",
               (new_saved, goal_id, g.user["id"]))
    db.commit()
    if not withdraw and new_saved >= goal["target_cents"] > goal["saved_cents"]:
        flash(f"🎉 You reached your goal “{goal['name']}”!", "success")
    else:
        flash("Goal balance updated.", "success")
    return redirect(url_for("goals.index"))


@bp.route("/<int:goal_id>/delete", methods=["POST"])
@login_required
def delete(goal_id):
    get_owned_goal(goal_id)
    db = get_db()
    db.execute("DELETE FROM goals WHERE id = ? AND user_id = ?", (goal_id, g.user["id"]))
    db.commit()
    flash("Goal deleted.", "success")
    return redirect(url_for("goals.index"))
