import re
import secrets

from flask import (
    Blueprint, current_app, flash, g, redirect, render_template, request, session, url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from database.db import get_db, seed_user_data
from services.dates import today
from services.security import login_throttle, safe_next_url

bp = Blueprint("auth", __name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Hash of a random password, checked when the email is unknown so a failed
# login takes the same time whether or not the account exists.
_DUMMY_HASH = generate_password_hash(secrets.token_hex(16))


def validate_password(password):
    if len(password) < 8:
        return "Password must be at least 8 characters."
    if len(password) > 128:
        return "Password must be at most 128 characters."
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        return "Password must contain at least one letter and one number."
    return None


def validate_name(name):
    if not name:
        return "Name is required."
    if len(name) > 60:
        return "Name must be at most 60 characters."
    return None


def validate_email(email):
    if not email or len(email) > 254 or not EMAIL_RE.match(email):
        return "Enter a valid email address."
    return None


def start_session(user_id, remember=False):
    """Log in with a fresh session so a pre-login session id can't be reused."""
    session.clear()
    session["user_id"] = user_id
    session.permanent = remember


def load_logged_in_user():
    user_id = session.get("user_id")
    g.user = None
    if user_id is not None:
        g.user = get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if g.user is None:
            session.clear()


@bp.route("/register", methods=["GET", "POST"])
def register():
    if g.user:
        return redirect(url_for("main.dashboard"))
    form = {"name": "", "email": ""}
    error = None
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        form = {"name": name, "email": email}
        error = validate_name(name) or validate_email(email) or validate_password(password)
        if not error and password != confirm:
            error = "Passwords do not match."
        db = get_db()
        if not error and db.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            error = "An account with that email already exists."
        if not error:
            cur = db.execute(
                "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                (name, email, generate_password_hash(password)),
            )
            db.commit()
            start_session(cur.lastrowid)
            flash(f"Welcome to Spendly, {name.split()[0]}! Add your first transaction to get started.", "success")
            return redirect(url_for("main.dashboard"))
    return render_template("auth/register.html", form=form, error=error), (400 if error else 200)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("main.dashboard"))
    email = ""
    error = None
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        keys = (f"ip:{request.remote_addr}", f"email:{email}")
        if login_throttle.is_blocked(*keys):
            error = "Too many failed attempts. Please wait 15 minutes and try again."
            return render_template("auth/login.html", email=email, error=error), 429
        user = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        valid = check_password_hash(user["password_hash"] if user else _DUMMY_HASH, password)
        if user and valid:
            login_throttle.reset(*keys)
            start_session(user["id"], remember=bool(request.form.get("remember")))
            target = safe_next_url(request.args.get("next"), url_for("main.dashboard"))
            return redirect(target)
        login_throttle.record_failure(*keys)
        error = "Incorrect email or password."
    return render_template("auth/login.html", email=email, error=error), (401 if error else 200)


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You've been signed out.", "info")
    return redirect(url_for("main.landing"))


@bp.route("/demo", methods=["POST"])
def demo():
    """Create a private, throwaway account pre-filled with a year of data."""
    db = get_db()
    ttl = int(current_app.config["DEMO_TTL_HOURS"])
    db.execute(
        "DELETE FROM users WHERE is_demo = 1 AND created_at < datetime('now', ?)",
        (f"-{ttl} hours",),
    )
    token = secrets.token_hex(6)
    cur = db.execute(
        "INSERT INTO users (name, email, password_hash, is_demo) VALUES (?, ?, ?, 1)",
        ("Demo User", f"demo-{token}@demo.spendly.local", generate_password_hash(secrets.token_hex(16))),
    )
    seed_user_data(db, cur.lastrowid, today(), seed=42)
    db.commit()
    start_session(cur.lastrowid)
    flash("You're exploring a demo account filled with sample data. Feel free to change anything.", "info")
    return redirect(url_for("main.dashboard"))
