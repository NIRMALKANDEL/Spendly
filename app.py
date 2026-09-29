import os

from flask import Flask, g, render_template, request
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from config import INSTANCE_DIR, Config, load_secret_key
from database import db as database
from routes import analytics, auth, budgets, goals, main, recurring, settings, transactions
from services import categories
from services.backup import ensure_daily_backup
from services.dates import today
from services.mailer import mail_enabled
from services.money import cents_to_input, format_money
from services.recurring import run_due
from services.security import csrf_protect, csrf_token, set_security_headers


def create_app(test_config=None):
    app = Flask(__name__, instance_path=str(INSTANCE_DIR))
    app.config.from_object(Config)
    app.config["SECRET_KEY"] = load_secret_key()
    if test_config:
        app.config.update(test_config)

    if app.config["PRODUCTION"] and not os.environ.get("SECRET_KEY"):
        raise RuntimeError("Set the SECRET_KEY environment variable in production.")

    if app.config["PRODUCTION"]:
        # Hosts like Render/PythonAnywhere sit behind one proxy; trust its
        # X-Forwarded-* headers so request.remote_addr (login throttling) and
        # https URLs are correct.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    database.init_app(app)

    for module in (auth, main, transactions, budgets, goals, recurring, analytics, settings):
        app.register_blueprint(module.bp)

    @app.before_request
    def before_request():
        if request.endpoint == "static":
            return
        if app.config["AUTO_BACKUP"] and not app.config.get("TESTING"):
            ensure_daily_backup(app.config["DATABASE"], app.config["BACKUP_DIR"], app.config["BACKUP_KEEP"])
        csrf_protect()
        auth.load_logged_in_user()
        if g.user is not None:
            run_due(database.get_db(), g.user["id"], today())

    app.after_request(set_security_headers)

    @app.context_processor
    def inject_globals():
        user = g.get("user")
        theme = categories.THEMES.get(user["theme"] if user else "forest", categories.THEMES["forest"])
        return {
            "csrf_token": csrf_token,
            "current_user": user,
            "theme": theme,
            "themes": categories.THEMES,
            "currencies": categories.CURRENCIES,
            "mail_enabled": mail_enabled(),
            "contact_email": app.config.get("CONTACT_EMAIL"),
        }

    @app.template_filter("money")
    def money_filter(cents, decimals=None):
        currency = g.user["currency"] if g.get("user") else "INR"
        return format_money(cents, currency, decimals)

    app.add_template_filter(cents_to_input, "as_input")

    @app.errorhandler(HTTPException)
    def handle_http_error(err):
        return render_template("errors.html", error=err), err.code

    return app


if __name__ == "__main__":
    create_app().run(debug=True, port=5001)
