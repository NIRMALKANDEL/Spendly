import json
import re

from flask import (
    Blueprint, Response, flash, g, jsonify, redirect, render_template, request, session, url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from database.db import get_db
from routes.auth import validate_name, validate_password
from services.categories import CURRENCIES, MODES, THEMES
from services.dates import today
from services.security import login_required

bp = Blueprint("settings", __name__, url_prefix="/settings")

HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


@bp.route("/")
@login_required
def index():
    db = get_db()
    uid = g.user["id"]
    stats = db.execute(
        "SELECT COUNT(*) AS count, MIN(date) AS first FROM transactions WHERE user_id = ?", (uid,)
    ).fetchone()
    return render_template("settings.html", stats=stats, modes=MODES)


@bp.route("/profile", methods=["POST"])
@login_required
def profile():
    name = request.form.get("name", "").strip()
    currency = request.form.get("currency", "")
    error = validate_name(name)
    if not error and currency not in CURRENCIES:
        error = "Choose a supported currency."
    if error:
        flash(error, "error")
    else:
        db = get_db()
        db.execute("UPDATE users SET name = ?, currency = ? WHERE id = ?", (name, currency, g.user["id"]))
        db.commit()
        flash("Profile saved.", "success")
    return redirect(url_for("settings.index"))


@bp.route("/appearance", methods=["POST"])
@login_required
def appearance():
    theme = request.form.get("theme", "forest")
    mode = request.form.get("mode", "system")
    accent = request.form.get("accent", "").strip()
    if request.form.get("reset_accent") or not request.form.get("use_custom_accent"):
        accent = None
    if theme not in THEMES or mode not in MODES or (accent and not HEX_COLOR.match(accent)):
        flash("That appearance setting isn't valid.", "error")
        return redirect(url_for("settings.index"))
    db = get_db()
    db.execute("UPDATE users SET theme = ?, mode = ?, accent = ? WHERE id = ?",
               (theme, mode, accent.lower() if accent else None, g.user["id"]))
    db.commit()
    flash("Appearance updated.", "success")
    return redirect(url_for("settings.index") + "#appearance")


@bp.route("/mode", methods=["POST"])
@login_required
def mode():
    """Quick light/dark toggle from the top bar (called with fetch)."""
    value = request.form.get("mode") or (request.get_json(silent=True) or {}).get("mode")
    if value not in MODES:
        return jsonify(ok=False, error="invalid mode"), 400
    db = get_db()
    db.execute("UPDATE users SET mode = ? WHERE id = ?", (value, g.user["id"]))
    db.commit()
    return jsonify(ok=True, mode=value)


@bp.route("/password", methods=["POST"])
@login_required
def password():
    current = request.form.get("current_password", "")
    new = request.form.get("new_password", "")
    confirm = request.form.get("confirm_password", "")
    if not check_password_hash(g.user["password_hash"], current):
        flash("Your current password is incorrect.", "error")
    elif error := validate_password(new):
        flash(error, "error")
    elif new != confirm:
        flash("New passwords do not match.", "error")
    else:
        db = get_db()
        db.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                   (generate_password_hash(new), g.user["id"]))
        db.commit()
        flash("Password changed.", "success")
    return redirect(url_for("settings.index") + "#security")


@bp.route("/export.json")
@login_required
def export_json():
    db = get_db()
    uid = g.user["id"]

    def rows(sql):
        return [dict(r) for r in db.execute(sql, (uid,))]

    user = g.user
    payload = {
        "exported_at": today().isoformat(),
        "profile": {"name": user["name"], "email": user["email"], "currency": user["currency"],
                    "monthly_budget_cents": user["monthly_budget_cents"]},
        "transactions": rows("SELECT kind, amount_cents, category, date, description FROM transactions"
                             " WHERE user_id = ? ORDER BY date"),
        "budgets": rows("SELECT category, amount_cents FROM budgets WHERE user_id = ?"),
        "goals": rows("SELECT name, target_cents, saved_cents, target_date FROM goals WHERE user_id = ?"),
        "recurring": rows("SELECT kind, amount_cents, category, description, frequency, next_date, active"
                          " FROM recurring WHERE user_id = ?"),
    }
    return Response(
        json.dumps(payload, indent=2, ensure_ascii=False),
        mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="spendly-backup-{today().isoformat()}.json"'},
    )


@bp.route("/delete", methods=["POST"])
@login_required
def delete_account():
    if not g.user["is_demo"] and not check_password_hash(g.user["password_hash"],
                                                           request.form.get("password", "")):
        flash("Password is incorrect; your account was not deleted.", "error")
        return redirect(url_for("settings.index") + "#danger")
    db = get_db()
    db.execute("DELETE FROM users WHERE id = ?", (g.user["id"],))
    db.commit()
    session.clear()
    flash("Your account and all its data have been deleted.", "info")
    return redirect(url_for("main.landing"))
