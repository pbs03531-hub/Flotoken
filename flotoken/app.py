"""Flotoken: takeaway token system for restaurants.

Run:   python app.py      ->  http://127.0.0.1:5000
First run opens a setup page to create the owner account.
"""
import os
import secrets
import time
from datetime import timedelta

from flask import Flask, g, jsonify, redirect, render_template, request
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash

import admin
import auth
import customers
import db as database
import orders
import pages
from util import ApiError, ist, now_ms

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def load_secret_key():
    """Stable secret for login cookies: env var, else a random key saved in instance/secret.key."""
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    path = os.path.join(BASE_DIR, "instance", "secret.key")
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(secrets.token_hex(32))
    with open(path) as fh:
        return fh.read().strip()


def bootstrap_owner(app):
    """Hosting without a shell (e.g. Render): create the owner, name and sample menu from environment
    variables the first time the database is empty. Does nothing once an owner exists."""
    username, password = os.environ.get("OWNER_USERNAME"), os.environ.get("OWNER_PASSWORD")
    if not (username and password):
        return
    with app.app_context():
        if auth.has_users():
            return
        try:
            username = auth.validate_username(username)
            auth.validate_password(password)
        except ApiError as e:
            print(f"[flotoken] OWNER_USERNAME / OWNER_PASSWORD ignored: {e.message}")
            return
        d = database.db()
        d.execute("INSERT INTO users (username, password_hash, role, created_at) VALUES (?,?,?,?)",
                  (username, generate_password_hash(password), "owner", now_ms()))
        if os.environ.get("RESTAURANT_NAME"):
            database.set_setting("restaurant_name", os.environ["RESTAURANT_NAME"].strip()[:60])
        if os.environ.get("SAMPLE_MENU", "1") == "1":
            database.seed_sample_menu()
        d.commit()
        print(f"[flotoken] owner account '{username}' created from environment variables")


def create_app(test_config=None):
    app = Flask(__name__)
    on_render = bool(os.environ.get("RENDER"))          # Render sets this variable on its servers
    app.config.update(
        DB_FILE=os.environ.get("DB_FILE", os.path.join(BASE_DIR, "instance", "parcel.db")),
        SECRET_KEY=load_secret_key(),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=on_render or os.environ.get("COOKIE_SECURE") == "1",
        SEND_FILE_MAX_AGE_DEFAULT=timedelta(days=7),
        PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 14,   # staff tablets stay signed in for 14 days
        JSON_SORT_KEYS=False,
        MAX_CONTENT_LENGTH=600 * 1024,        # menu photos arrive as base64 (about 270 KB at most)
    )
    if test_config:
        app.config.update(test_config)
    # Behind a hosting proxy the real visitor address and https flag arrive in X-Forwarded-* headers.
    # Without this every visitor would look like the proxy and share one rate limit.
    if os.environ.get("TRUST_PROXY", "1" if on_render else "0") == "1":
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    os.makedirs(os.path.dirname(app.config["DB_FILE"]), exist_ok=True)
    database.init_db(app.config["DB_FILE"])

    app.teardown_appcontext(database.close_db)
    for module in (auth, customers, orders, admin, pages):
        app.register_blueprint(module.bp)
    bootstrap_owner(app)

    @app.before_request
    def guard():
        auth.load_user()
        customers.load_customer()
        # First run: nothing works until the owner account exists, so send every page to /setup.
        if not request.path.startswith(("/static/", "/api/", "/setup", "/healthz", "/sw.js", "/manifest.webmanifest", "/offline", "/img/", "/pricing")) and not auth.has_users():
            return redirect("/setup")
        # Cross-site forms cannot send JSON, so requiring it blocks CSRF on every state-changing call.
        if request.method in ("POST", "PUT", "DELETE") and request.path.startswith("/api/") and not request.is_json:
            raise ApiError(415, "Send JSON")

    @app.after_request
    def headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        if request.is_secure:
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        if request.path.startswith("/api/") or resp.mimetype == "text/html":
            resp.headers["Cache-Control"] = "no-store"
        return resp

    asset_version = int(time.time())     # changes on every restart so browsers fetch fresh CSS/JS

    @app.context_processor
    def inject():
        user = g.get("user")
        s = database.all_settings()
        cfg = {"user": user}
        if user:
            cfg.update(restaurant=s["restaurant_name"], whatsapp=s["whatsapp_template"],
                       upi_vpa=s["upi_vpa"], upi_name=s["upi_name"] or s["restaurant_name"],
                       payment_mode=s["payment_mode"])
        return {"user": user, "APP": cfg, "ASSET_V": asset_version, "SET": s,
                "restaurant_name": s["restaurant_name"]}

    @app.template_filter("ist")
    def ist_filter(ms, fmt="%d %b %Y, %I:%M %p"):
        return ist(ms).strftime(fmt) if ms else ""

    @app.errorhandler(ApiError)
    def api_error(e):
        return jsonify(error=e.message, **e.extra), e.code

    @app.errorhandler(404)
    def not_found(_e):
        if request.path.startswith("/api/"):
            return jsonify(error="Not found"), 404
        return render_template("error.html", code=404, message="Page not found"), 404

    @app.errorhandler(413)
    def too_big(_e):
        return jsonify(error="Request too large"), 413

    @app.errorhandler(500)
    def server_error(_e):
        if request.path.startswith("/api/"):
            return jsonify(error="Something went wrong on the server"), 500
        return render_template("error.html", code=500, message="Something went wrong"), 500

    return app


app = create_app()

if __name__ == "__main__":
    # host 0.0.0.0 lets phones and TVs on the same Wi-Fi open http://<your-laptop-ip>:5000
    app.run(host="0.0.0.0", port=5000, debug=os.environ.get("FLASK_DEBUG", "1") == "1")
