"""Materialise due recurring rules into real transactions."""

from services.dates import add_months, parse_date, timedelta

# Safety valve: a weekly rule left untouched for years should not insert
# thousands of rows in a single request.
MAX_OCCURRENCES_PER_RUN = 200


def advance(current, frequency, anchor_day):
    if frequency == "weekly":
        return current + timedelta(days=7)
    if frequency == "monthly":
        return add_months(current, 1, anchor_day)
    if frequency == "yearly":
        return add_months(current, 12, anchor_day)
    raise ValueError(f"Unknown frequency: {frequency}")


def run_due(db, user_id, today):
    """Insert every occurrence due on or before `today`. Returns rows created."""
    rules = db.execute(
        "SELECT * FROM recurring WHERE user_id = ? AND active = 1 AND next_date <= ?",
        (user_id, today.isoformat()),
    ).fetchall()
    created = 0
    for rule in rules:
        due = parse_date(rule["next_date"])
        count = 0
        while due <= today and count < MAX_OCCURRENCES_PER_RUN:
            db.execute(
                "INSERT INTO transactions (user_id, kind, amount_cents, category, date, description, recurring_id)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_id, rule["kind"], rule["amount_cents"], rule["category"], due.isoformat(),
                 rule["description"], rule["id"]),
            )
            due = advance(due, rule["frequency"], rule["anchor_day"])
            count += 1
        db.execute("UPDATE recurring SET next_date = ? WHERE id = ?", (due.isoformat(), rule["id"]))
        created += count
    if rules:
        db.commit()
    return created
