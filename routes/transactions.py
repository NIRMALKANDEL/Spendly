import csv
import io
import math
import re
from datetime import timedelta

from flask import (
    Blueprint, Response, abort, flash, g, redirect, render_template, request, url_for,
)

from database.db import get_db
from services.categories import CATEGORIES, EXPENSE_CATEGORIES, INCOME_CATEGORIES, KINDS
from services.dates import MIN_DATE, parse_date, parse_optional_date, today
from services.money import cents_to_input, parse_amount
from services.security import login_required, safe_next_url

bp = Blueprint("transactions", __name__, url_prefix="/transactions")

PER_PAGE = 20
MAX_DESCRIPTION = 200
MAX_IMPORT_ROWS = 5000
SORTS = {
    "date_desc": "date DESC, id DESC",
    "date_asc": "date ASC, id ASC",
    "amount_desc": "amount_cents DESC, date DESC",
    "amount_asc": "amount_cents ASC, date DESC",
}


def validate_transaction(data):
    """Validate a transaction payload. Returns (clean, error)."""
    kind = (data.get("kind") or "expense").strip().lower()
    if kind not in KINDS:
        return None, "Choose expense or income."
    try:
        amount = parse_amount(data.get("amount"))
    except ValueError as exc:
        return None, str(exc)
    category = (data.get("category") or "").strip()
    match = next((c for c in CATEGORIES[kind] if c.lower() == category.lower()), None)
    if not match:
        return None, f"Choose a valid {kind} category."
    try:
        day = parse_date(data.get("date"))
    except ValueError as exc:
        return None, str(exc)
    if day < MIN_DATE or day > today() + timedelta(days=366):
        return None, "Date must be between 2000 and one year from today."
    description = (data.get("description") or "").strip()
    if len(description) > MAX_DESCRIPTION:
        return None, f"Description must be at most {MAX_DESCRIPTION} characters."
    return {
        "kind": kind,
        "amount_cents": amount,
        "category": match,
        "date": day.isoformat(),
        "description": description,
        # UPI transaction ID from a scanned receipt; letters and digits only.
        "reference": re.sub(r"[^A-Za-z0-9]", "", data.get("reference") or "")[:40] or None,
    }, None


def find_duplicate(user_id, reference):
    """An existing transaction with the same UPI reference, if any."""
    if not reference:
        return None
    return get_db().execute(
        "SELECT id, date, amount_cents, description, category FROM transactions"
        " WHERE user_id = ? AND reference = ? ORDER BY id LIMIT 1",
        (user_id, reference),
    ).fetchone()


def get_owned_transaction(tx_id):
    tx = get_db().execute(
        "SELECT * FROM transactions WHERE id = ? AND user_id = ?", (tx_id, g.user["id"])
    ).fetchone()
    if tx is None:
        abort(404)
    return tx


def read_filters(args):
    kind = args.get("kind", "")
    filters = {
        "kind": kind if kind in KINDS else "",
        "category": args.get("category", "").strip()[:40],
        "q": args.get("q", "").strip()[:100],
        "start": parse_optional_date(args.get("start")),
        "end": parse_optional_date(args.get("end")),
        "sort": args.get("sort") if args.get("sort") in SORTS else "date_desc",
    }
    return filters


def build_where(filters):
    clauses, params = ["user_id = ?"], [g.user["id"]]
    if filters["kind"]:
        clauses.append("kind = ?")
        params.append(filters["kind"])
    if filters["category"]:
        clauses.append("category = ?")
        params.append(filters["category"])
    if filters["q"]:
        escaped = filters["q"].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        clauses.append("(description LIKE ? ESCAPE '\\' OR category LIKE ? ESCAPE '\\')")
        params += [f"%{escaped}%"] * 2
    if filters["start"]:
        clauses.append("date >= ?")
        params.append(filters["start"].isoformat())
    if filters["end"]:
        clauses.append("date <= ?")
        params.append(filters["end"].isoformat())
    return " AND ".join(clauses), params


def filter_query_args(filters):
    """Filters as query-string args, for pagination and export links."""
    args = {k: v for k, v in filters.items() if v and k not in ("start", "end")}
    if filters["start"]:
        args["start"] = filters["start"].isoformat()
    if filters["end"]:
        args["end"] = filters["end"].isoformat()
    return args


@bp.route("/")
@login_required
def index():
    db = get_db()
    filters = read_filters(request.args)
    where, params = build_where(filters)
    summary = db.execute(
        f"""
        SELECT COUNT(*) AS count,
               COALESCE(SUM(CASE WHEN kind = 'income'  THEN amount_cents END), 0) AS income,
               COALESCE(SUM(CASE WHEN kind = 'expense' THEN amount_cents END), 0) AS expense
        FROM transactions WHERE {where}
        """,
        params,
    ).fetchone()
    pages = max(1, math.ceil(summary["count"] / PER_PAGE))
    page = min(max(request.args.get("page", 1, type=int) or 1, 1), pages)
    rows = db.execute(
        f"SELECT * FROM transactions WHERE {where} ORDER BY {SORTS[filters['sort']]} LIMIT ? OFFSET ?",
        params + [PER_PAGE, (page - 1) * PER_PAGE],
    ).fetchall()
    return render_template(
        "transactions/index.html",
        rows=rows,
        filters=filters,
        query_args=filter_query_args(filters),
        summary=summary,
        page=page,
        pages=pages,
        all_categories=sorted(set(EXPENSE_CATEGORIES + INCOME_CATEGORIES)),
    )


def render_form(tx=None, form=None, error=None, status=200, receipt=None, duplicate=None):
    return render_template(
        "transactions/form.html",
        tx=tx,
        form=form,
        error=error,
        categories=CATEGORIES,
        receipt=receipt,
        duplicate=duplicate,
    ), status


@bp.route("/new", methods=["GET", "POST"])
@login_required
def create():
    if request.method == "POST":
        clean, error = validate_transaction(request.form)
        from_receipt = request.form.get("source") == "receipt"
        if error:
            return render_form(form=request.form, error=error, status=400,
                               receipt={"source": "receipt"} if from_receipt else None)
        duplicate = find_duplicate(g.user["id"], clean["reference"])
        if duplicate and not request.form.get("allow_duplicate"):
            return render_form(form=request.form, status=409, duplicate=duplicate,
                               receipt={"source": "receipt"} if from_receipt else None,
                               error="You've already saved a payment with this UPI reference.")
        db = get_db()
        db.execute(
            "INSERT INTO transactions (user_id, kind, amount_cents, category, date, description, reference)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (g.user["id"], clean["kind"], clean["amount_cents"], clean["category"], clean["date"],
             clean["description"], clean["reference"]),
        )
        db.commit()
        flash(f"{clean['kind'].title()} added.", "success")
        if from_receipt and request.form.get("add_another"):
            return redirect(url_for("receipts.scan"))
        if request.form.get("add_another"):
            return redirect(url_for("transactions.create", kind=clean["kind"]))
        return redirect(url_for("transactions.index"))
    kind = request.args.get("kind") if request.args.get("kind") in KINDS else "expense"
    form = {"kind": kind, "date": today().isoformat(), "category": CATEGORIES[kind][0]}
    return render_form(form=form)


@bp.route("/<int:tx_id>/edit", methods=["GET", "POST"])
@login_required
def edit(tx_id):
    tx = get_owned_transaction(tx_id)
    if request.method == "POST":
        clean, error = validate_transaction(request.form)
        if error:
            return render_form(tx=tx, form=request.form, error=error, status=400)
        db = get_db()
        db.execute(
            "UPDATE transactions SET kind = ?, amount_cents = ?, category = ?, date = ?, description = ?"
            " WHERE id = ? AND user_id = ?",
            (clean["kind"], clean["amount_cents"], clean["category"], clean["date"],
             clean["description"], tx_id, g.user["id"]),
        )
        db.commit()
        flash("Transaction updated.", "success")
        return redirect(url_for("transactions.index"))
    form = dict(tx)
    form["amount"] = cents_to_input(tx["amount_cents"])
    return render_form(tx=tx, form=form)


@bp.route("/<int:tx_id>/delete", methods=["POST"])
@login_required
def delete(tx_id):
    get_owned_transaction(tx_id)
    db = get_db()
    db.execute("DELETE FROM transactions WHERE id = ? AND user_id = ?", (tx_id, g.user["id"]))
    db.commit()
    flash("Transaction deleted.", "success")
    return redirect(safe_back(url_for("transactions.index")))


def safe_back(fallback):
    return safe_next_url(request.form.get("next"), fallback)


def csv_safe(value):
    """Neutralise spreadsheet formula injection (=, +, -, @ prefixes)."""
    text = str(value)
    if text and text[0] in "=+-@\t\r":
        return "'" + text
    return text


@bp.route("/export.csv")
@login_required
def export_csv():
    filters = read_filters(request.args)
    where, params = build_where(filters)
    rows = get_db().execute(
        f"SELECT * FROM transactions WHERE {where} ORDER BY {SORTS[filters['sort']]}", params
    ).fetchall()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["date", "type", "category", "amount", "description"])
    for r in rows:
        writer.writerow([r["date"], r["kind"], r["category"], cents_to_input(r["amount_cents"]),
                         csv_safe(r["description"])])
    filename = f"spendly-transactions-{today().isoformat()}.csv"
    return Response(
        "﻿" + buffer.getvalue(),  # BOM so Excel opens UTF-8 (₹) correctly
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@bp.route("/import", methods=["GET", "POST"])
@login_required
def import_csv():
    if request.method == "GET":
        return render_template("transactions/import.html", errors=[])
    upload = request.files.get("file")
    if not upload or not upload.filename:
        flash("Choose a CSV file to import.", "error")
        return redirect(url_for("transactions.import_csv"))
    try:
        text = upload.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        flash("The file must be UTF-8 encoded CSV.", "error")
        return redirect(url_for("transactions.import_csv"))

    reader = csv.DictReader(io.StringIO(text))
    fields = {(f or "").strip().lower() for f in (reader.fieldnames or [])}
    required = {"date", "category", "amount"}
    if not required <= fields:
        flash("The CSV needs at least these columns: date, category, amount.", "error")
        return redirect(url_for("transactions.import_csv"))

    clean_rows, errors = [], []
    for line_no, raw in enumerate(reader, start=2):
        if line_no - 1 > MAX_IMPORT_ROWS:
            errors.append(f"Stopped after {MAX_IMPORT_ROWS} rows.")
            break
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items() if k}
        row["kind"] = row.get("type") or row.get("kind") or "expense"
        description = row.get("description", "")
        if description.startswith("'") and description[1:2] in ("=", "+", "-", "@"):
            row["description"] = description[1:]
        clean, error = validate_transaction(row)
        if error:
            errors.append(f"Row {line_no}: {error}")
        else:
            clean_rows.append(clean)

    if errors:
        return render_template("transactions/import.html", errors=errors[:25],
                               error_count=len(errors)), 400
    if not clean_rows:
        flash("The file has no rows to import.", "error")
        return redirect(url_for("transactions.import_csv"))

    db = get_db()
    db.executemany(
        "INSERT INTO transactions (user_id, kind, amount_cents, category, date, description)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        [(g.user["id"], r["kind"], r["amount_cents"], r["category"], r["date"], r["description"])
         for r in clean_rows],
    )
    db.commit()
    flash(f"Imported {len(clean_rows)} transactions.", "success")
    return redirect(url_for("transactions.index"))
