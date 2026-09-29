"""SQLite access: connection per request, schema creation and seed data."""

import random
import sqlite3
from pathlib import Path

import click
from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    name                 TEXT    NOT NULL,
    email                TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    password_hash        TEXT    NOT NULL,
    currency             TEXT    NOT NULL DEFAULT 'INR',
    theme                TEXT    NOT NULL DEFAULT 'forest',
    mode                 TEXT    NOT NULL DEFAULT 'system',
    accent               TEXT,
    monthly_budget_cents INTEGER NOT NULL DEFAULT 0 CHECK (monthly_budget_cents >= 0),
    is_demo              INTEGER NOT NULL DEFAULT 0,
    email_verified       INTEGER NOT NULL DEFAULT 0,
    auto_save_receipts   INTEGER NOT NULL DEFAULT 1,
    verification_sent_at TEXT,
    created_at           TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS recurring (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind         TEXT    NOT NULL CHECK (kind IN ('expense', 'income')),
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    category     TEXT    NOT NULL,
    description  TEXT    NOT NULL DEFAULT '',
    frequency    TEXT    NOT NULL CHECK (frequency IN ('weekly', 'monthly', 'yearly')),
    anchor_day   INTEGER NOT NULL,
    next_date    TEXT    NOT NULL,
    active       INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS transactions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind         TEXT    NOT NULL CHECK (kind IN ('expense', 'income')),
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    category     TEXT    NOT NULL,
    date         TEXT    NOT NULL,
    description  TEXT    NOT NULL DEFAULT '',
    recurring_id INTEGER REFERENCES recurring(id) ON DELETE SET NULL,
    reference    TEXT,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_transactions_user_date ON transactions (user_id, date);

CREATE TABLE IF NOT EXISTS budgets (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    category     TEXT    NOT NULL,
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    UNIQUE (user_id, category)
);

CREATE TABLE IF NOT EXISTS goals (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name         TEXT    NOT NULL,
    target_cents INTEGER NOT NULL CHECK (target_cents > 0),
    saved_cents  INTEGER NOT NULL DEFAULT 0 CHECK (saved_cents >= 0),
    target_date  TEXT,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""


def connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db():
    """Return this request's connection, opening it on first use."""
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


# Columns added after the first release. CREATE TABLE IF NOT EXISTS won't add
# them to an existing database, so they are applied here, idempotently.
MIGRATIONS = [
    ("users", "email_verified", "INTEGER NOT NULL DEFAULT 0"),
    ("users", "verification_sent_at", "TEXT"),
    ("transactions", "reference", "TEXT"),  # UPI transaction ID, used to spot duplicate receipts
    ("users", "auto_save_receipts", "INTEGER NOT NULL DEFAULT 1"),
]


def migrate(db):
    for table, column, definition in MIGRATIONS:
        existing = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    db.execute("CREATE INDEX IF NOT EXISTS idx_transactions_user_reference ON transactions (user_id, reference)")


def init_db():
    Path(current_app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
    db = get_db()
    db.executescript(SCHEMA)
    migrate(db)
    db.commit()


# ------------------------------------------------------------------ #
# Seed data                                                           #
# ------------------------------------------------------------------ #

def seed_user_data(db, user_id, today, seed=None):
    """Fill an account with ~12 months of realistic activity.

    Used for the demo account and `flask seed-db`. Deterministic per seed.
    """
    from services.dates import add_months, month_start, timedelta

    rng = random.Random(seed if seed is not None else user_id)
    rows = []

    def add(kind, rupees, category, day, description):
        if day <= today:
            rows.append((user_id, kind, int(round(rupees * 100)), category, day.isoformat(), description))

    first_month = add_months(month_start(today), -11)
    for offset in range(12):
        start = add_months(first_month, offset)
        add("income", 65000, "Salary", start, "Monthly salary")
        if rng.random() < 0.45:
            add("income", rng.choice([4000, 6500, 9000, 12000]), "Freelance",
                start + timedelta(days=rng.randint(8, 25)), "Freelance project")
        add("expense", 18000, "Rent", start.replace(day=5), "Apartment rent")
        add("expense", rng.randint(1800, 3200), "Bills", start.replace(day=10), "Electricity & internet")
        add("expense", 649, "Entertainment", start.replace(day=12), "Streaming subscription")
        for week in range(4):
            add("expense", rng.randint(1100, 2400), "Groceries",
                start + timedelta(days=week * 7 + rng.randint(0, 3)), "Weekly groceries")
        for _ in range(rng.randint(7, 12)):
            add("expense", rng.randint(150, 900), "Food",
                start + timedelta(days=rng.randint(0, 27)),
                rng.choice(["Lunch with team", "Coffee", "Dinner out", "Food delivery", "Snacks"]))
        for _ in range(rng.randint(5, 9)):
            add("expense", rng.randint(60, 450), "Transport",
                start + timedelta(days=rng.randint(0, 27)),
                rng.choice(["Metro card top-up", "Cab ride", "Fuel", "Bus pass"]))
        if rng.random() < 0.7:
            add("expense", rng.randint(900, 5500), "Shopping",
                start + timedelta(days=rng.randint(0, 27)),
                rng.choice(["Clothes", "Headphones", "Home decor", "Books", "Shoes"]))
        if rng.random() < 0.35:
            add("expense", rng.randint(400, 3500), "Health",
                start + timedelta(days=rng.randint(0, 27)),
                rng.choice(["Pharmacy", "Doctor visit", "Gym membership"]))
        if rng.random() < 0.25:
            add("expense", rng.randint(1500, 6000), "Education",
                start + timedelta(days=rng.randint(0, 27)), "Online course")
        if offset in (3, 9):
            add("expense", rng.randint(9000, 16000), "Travel",
                start + timedelta(days=rng.randint(10, 20)), "Weekend trip")

    db.executemany(
        "INSERT INTO transactions (user_id, kind, amount_cents, category, date, description)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    db.executemany(
        "INSERT OR IGNORE INTO budgets (user_id, category, amount_cents) VALUES (?, ?, ?)",
        [
            (user_id, "Food", 500000),
            (user_id, "Groceries", 800000),
            (user_id, "Shopping", 300000),
            (user_id, "Transport", 200000),
            (user_id, "Entertainment", 150000),
        ],
    )
    db.execute("UPDATE users SET monthly_budget_cents = ? WHERE id = ?", (4500000, user_id))
    db.executemany(
        "INSERT INTO goals (user_id, name, target_cents, saved_cents, target_date) VALUES (?, ?, ?, ?, ?)",
        [
            (user_id, "Emergency fund", 30000000, 17500000, add_months(today, 8).isoformat()),
            (user_id, "New laptop", 9000000, 5200000, add_months(today, 4).isoformat()),
            (user_id, "Trip to the mountains", 6000000, 1100000, add_months(today, 10).isoformat()),
        ],
    )
    next_month = add_months(month_start(today), 1)
    db.executemany(
        "INSERT INTO recurring (user_id, kind, amount_cents, category, description, frequency,"
        " anchor_day, next_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (user_id, "income", 6500000, "Salary", "Monthly salary", "monthly", 1, next_month.isoformat()),
            (user_id, "expense", 1800000, "Rent", "Apartment rent", "monthly", 5, next_month.replace(day=5).isoformat()),
            (user_id, "expense", 64900, "Entertainment", "Streaming subscription", "monthly", 12,
             next_month.replace(day=12).isoformat()),
        ],
    )


# ------------------------------------------------------------------ #
# CLI                                                                 #
# ------------------------------------------------------------------ #

@click.command("init-db")
def init_db_command():
    """Create tables if they do not exist."""
    init_db()
    click.echo("Database initialised.")


@click.command("seed-db")
@click.option("--email", default="demo@spendly.app", show_default=True)
@click.option("--password", default="demo1234", show_default=True)
def seed_db_command(email, password):
    """Create a sample user with a year of data."""
    from datetime import date

    from werkzeug.security import generate_password_hash

    init_db()
    db = get_db()
    if db.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
        click.echo(f"{email} already exists; nothing to do.")
        return
    cur = db.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        ("Sample User", email, generate_password_hash(password)),
    )
    seed_user_data(db, cur.lastrowid, date.today())
    db.commit()
    click.echo(f"Seeded {email} / {password}")


@click.command("backup-db")
def backup_db_command():
    """Snapshot the database into BACKUP_DIR (run daily from a scheduler)."""
    from services.backup import create_backup, list_backups

    cfg = current_app.config
    path = create_backup(cfg["DATABASE"], cfg["BACKUP_DIR"], cfg["BACKUP_KEEP"])
    click.echo(f"Backup written to {path}")
    click.echo(f"{len(list_backups(cfg['BACKUP_DIR']))} backups kept in {cfg['BACKUP_DIR']}")


def init_app(app):
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
    app.cli.add_command(seed_db_command)
    app.cli.add_command(backup_db_command)
    with app.app_context():
        init_db()
