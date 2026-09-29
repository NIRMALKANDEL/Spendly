# ◈ Spendly — Personal Finance Tracker

Track every rupee. Spendly is a full-stack personal finance app for logging expenses and income,
setting budgets, analysing past spending, planning savings goals and running "what if" calculations —
with editable themes, dark mode and a mobile-first layout.

![tests](https://github.com/NIRMALKANDEL/Spendly/actions/workflows/tests.yml/badge.svg)
![python](https://img.shields.io/badge/python-3.12-blue)
![flask](https://img.shields.io/badge/flask-3.1-black)

| Dashboard (dark) | Analytics (light) |
|---|---|
| ![Dashboard](docs/dashboard-dark.png) | ![Analytics](docs/analytics-light.png) |

| Mobile dashboard | Mobile goals | Landing |
|---|---|---|
| <img src="docs/mobile-dashboard.png" width="240"> | <img src="docs/mobile-goals.png" width="240"> | <img src="docs/landing.png" width="420"> |

> **Try it without signing up:** click **“Try the live demo”** on the landing page. It creates a private
> sandbox account with a year of realistic sample data (auto-deleted after 24 hours).

---

## Features

**Tracking**
- Expenses **and** income with categories, dates and notes; add / edit / delete
- Search, filter (type, category, date range), sort and paginate your history
- **CSV import** (validated, all-or-nothing) and **CSV / JSON export** (full backup)
- **Recurring transactions** — rent, salary, subscriptions are logged automatically (weekly / monthly / yearly,
  month-end safe: a rule on the 31st lands on Feb 28 and returns to the 31st in March)

**Understanding**
- **Dashboard:** month-to-date spend, income, net saved, savings rate, spending-pace chart vs last month,
  6-month income/expense trend, category breakdown, budget progress, recent activity
- **Analytics** for 3 / 6 / 12 months, year-to-date, all time or a custom range: monthly trend,
  category ranking, average spend by weekday, category × month heat table, largest expenses, income sources
- **Plain-language insights** — e.g. *“You've spent 12% less than at this point last month”*,
  *“At this pace you'll spend about ₹48,500 this month — ₹3,500 over budget”*,
  *“Food spending in Aug was up 31% versus the previous three-month average”*

**Planning**
- **Budgets:** an overall monthly limit plus per-category limits, with good / close / over states
- **Savings goals:** target, deadline, progress, add/withdraw money, and the monthly amount needed to hit each date
- **Calculators:** compound savings growth (with chart), goal planner, time-to-goal, emergency fund
  (pre-filled from your real 3-month average) and loan EMI

**Experience**
- **Editable themes:** 5 presets (Forest, Ocean, Plum, Terracotta, Graphite), light / dark / system mode,
  and a custom accent colour picker with live preview — saved per user
- **Mobile-first:** off-canvas sidebar, bottom tab bar with a floating “+” button, 16px inputs (no iOS zoom),
  safe-area aware, no horizontal scrolling at 390px
- Multi-currency display (₹ INR with Indian digit grouping `1,23,456`, रू NPR, $, €, £, A$, C$)
- Installable (web manifest), accessible (skip link, labelled controls, focus rings, `aria-live` flashes,
  chart ↔ table toggle, reduced-motion support), printable

## Security

| Concern | How it's handled |
|---|---|
| Passwords | Hashed with Werkzeug scrypt; min 8 chars with a letter and a number |
| Brute force | Login throttling per IP and per email (5 failures / 15 min); constant-time check for unknown emails |
| CSRF | Per-session token required on every POST (forms and `fetch`) |
| Session | `HttpOnly`, `SameSite=Lax`, `Secure` in production, regenerated on login (no fixation) |
| XSS | Jinja auto-escaping; strict **Content-Security-Policy** (`script-src 'self'`, no inline JS, Chart.js vendored) |
| SQL injection | Parameterised queries only; sort keys whitelisted; `LIKE` wildcards escaped |
| Authorisation | Every record lookup is scoped to the signed-in user (`404` for others' data) |
| Open redirect | `?next=` only accepts same-site relative paths |
| CSV injection | Exported cells starting with `= + - @` are neutralised |
| Headers | `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`, HSTS in production, `no-store` on private pages |
| Input limits | 2 MB uploads, 5,000 import rows, bounded amounts/dates/text lengths |

## Tech stack

- **Backend:** Python 3.12, Flask 3 (application factory + blueprints), SQLite (foreign keys, cascading deletes, indexes)
- **Frontend:** server-rendered Jinja templates, hand-written CSS with design tokens, vanilla JS, Chart.js 4
- **Testing:** pytest — 116 tests, ~95% coverage, GitHub Actions CI
- **Deploy:** Gunicorn; configs for Render and PythonAnywhere

Money is stored as **integer paise/cents** so totals never suffer floating-point drift.

## Project structure

```
app.py                 # application factory: config, security hooks, blueprints, error pages
config.py              # settings (env-driven), secret-key handling
wsgi.py                # production entry point (gunicorn wsgi:app)
database/db.py         # schema, connection handling, demo seed data, CLI commands
routes/                # blueprints: auth, main (dashboard, calculators), transactions,
                       #             budgets, goals, recurring, analytics, settings
services/              # framework-free logic: analytics & insights, finance maths,
                       #   money parsing/formatting, dates, recurring engine, security
templates/             # Jinja templates (+ _macros.html component library)
static/                # css/style.css, js/{main,charts,calculators,theme-init}.js, vendor/chart.js
tests/                 # pytest suite
```

## Run locally

```bash
git clone https://github.com/NIRMALKANDEL/Spendly.git
cd Spendly
python -m venv venv
# Windows: venv\Scripts\activate    macOS/Linux: source venv/bin/activate
pip install -r requirements-dev.txt
python app.py                      # http://127.0.0.1:5001
```

Optional: `flask --app app seed-db` creates `demo@spendly.app` / `demo1234` with a year of data.

Run the tests:

```bash
pytest --cov=.
```

### Configuration

| Variable | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | generated into `instance/secret_key` | Session signing key — **required** when `PRODUCTION=1` |
| `DATABASE_PATH` | `instance/spendly.db` | SQLite file location |
| `PRODUCTION` | off | Enables secure cookies, HSTS and proxy header handling |

## Deploy

### Option A — PythonAnywhere (free, data persists) ✅ recommended

1. Sign up at [pythonanywhere.com](https://www.pythonanywhere.com) (free “Beginner” account).
2. Open a **Bash console** and run:
   ```bash
   git clone https://github.com/NIRMALKANDEL/Spendly.git
   cd Spendly
   python3.12 -m venv venv && source venv/bin/activate
   pip install -r requirements.txt
   python -c "import secrets; print(secrets.token_hex(32))"   # copy this value
   ```
3. **Web** tab → *Add a new web app* → *Manual configuration* → *Python 3.12*.
4. Set **Virtualenv** to `/home/<you>/Spendly/venv` and **Source code** to `/home/<you>/Spendly`.
5. Edit the **WSGI configuration file** so it contains only:
   ```python
   import os, sys
   path = "/home/<you>/Spendly"
   if path not in sys.path:
       sys.path.insert(0, path)
   os.environ["PRODUCTION"] = "1"
   os.environ["SECRET_KEY"] = "<paste the value from step 2>"
   os.environ["DATABASE_PATH"] = "/home/<you>/Spendly/instance/spendly.db"
   from wsgi import app as application
   ```
6. **Static files:** URL `/static/` → Directory `/home/<you>/Spendly/static`.
7. Turn on **Force HTTPS**, click **Reload**. Your app is live at `https://<you>.pythonanywhere.com`.

To update later: `cd ~/Spendly && git pull` in a console, then **Reload** on the Web tab.

### Option B — Render (one-click from GitHub)

1. Sign in to [render.com](https://render.com) with GitHub → **New → Blueprint** → pick this repo.
2. Render reads `render.yaml`, generates a `SECRET_KEY` and deploys to `https://spendly-xxxx.onrender.com`.

Render's free plan has **no persistent disk**, so the database resets on each redeploy and the app sleeps
after 15 minutes idle (first visit then takes ~30s). That's fine for a portfolio demo — the “Try the live demo”
button always works — but use PythonAnywhere (or add a Render disk) for real personal data.

## Roadmap ideas

- PostgreSQL support for multi-instance hosting
- Receipt photo attachments
- Email reminders for budgets and recurring bills
- Split expenses with friends
- Offline mode with a service worker

## License

MIT — see [LICENSE](LICENSE).
