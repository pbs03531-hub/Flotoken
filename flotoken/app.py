"""Flotoken: takeaway token system for many restaurants.

Run:   python app.py      ->  http://127.0.0.1:5000
First run asks you (the Flotoken owner) to create a platform login; from there you add restaurants.
Each restaurant lives at /r/<restaurant-code>/ with its own database.
"""
import os
import secrets
import time
from datetime import timedelta

from flask import Flask, g, jsonify, redirect, render_template, request
from werkzeug.middleware.proxy_fix import ProxyFix

import admin
import auth
import customers
import db as database
import orders
import pages
import portal
from util import ApiError, ist

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


# Pages and calls that work before the Flotoken owner has been created (first run on a new server).
OPEN_BEFORE_SETUP = ("/static/", "/api/platform/", "/platform", "/healthz", "/sw.js", "/manifest.webmanifest",
                     "/offline", "/pricing", "/api/public/", "/staff", "/customer", "/api/customer/")


def create_app(test_config=None):
    app = Flask(__name__)
    on_render = bool(os.environ.get("RENDER"))          # Render sets this variable on its servers
    legacy = os.environ.get("DB_FILE")                   # older setups named one file; use its folder
    app.config.update(
        DATA_DIR=os.environ.get("DATA_DIR") or (os.path.dirname(legacy) if legacy else os.path.join(BASE_DIR, "instance")),
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
    os.makedirs(app.config["DATA_DIR"], exist_ok=True)

    app.teardown_appcontext(database.close_db)
    app.register_blueprint(portal.bp)                    # /, /staff, /customer, /platform, /pricing ...
    app.register_blueprint(customers.account_bp)         # /api/customer/... (one account for all restaurants)
    for module in (auth, orders, admin, pages, customers):
        app.register_blueprint(module.bp, url_prefix="/r/<slug>")     # everything a restaurant uses
    portal.bootstrap(app)

    # /r/<slug>/... : take the restaurant code out of the address and put it back in url_for() links.
    @app.url_value_preprocessor
    def pull_slug(_endpoint, values):
        g.slug = str(values.pop("slug")).lower() if values and "slug" in values else None

    @app.url_defaults
    def add_slug(endpoint, values):
        if "slug" not in values and g.get("slug") and app.url_map.is_endpoint_expecting(endpoint, "slug"):
            values["slug"] = g.slug

    def unavailable(code, message):
        if "/api/" in request.path:
            raise ApiError(code, message)
        return render_template("error.html", code=code, message=message), code

    @app.before_request
    def guard():
        g.rest = g.user = g.customer = g.padmin = None
        portal.load_platform_admin()
        # First run: nothing works until the Flotoken owner login exists.
        if request.path != "/" and not request.path.startswith(OPEN_BEFORE_SETUP) and not portal.has_platform_admin():
            return redirect("/platform")
        customers.load_customer()
        if g.get("slug"):
            row = database.pdb().execute("SELECT * FROM restaurants WHERE slug = ?", (g.slug,)).fetchone()
            if row is None:
                return unavailable(404, "We could not find that restaurant. Check the address or code.")
            if row["status"] != "active":
                return unavailable(403, "This restaurant is not taking orders on Flotoken right now.")
            g.rest = dict(row)
            auth.load_user()
        # Cross-site forms cannot send JSON, so requiring it blocks CSRF on every state-changing call.
        if request.method in ("POST", "PUT", "DELETE") and "/api/" in request.path and not request.is_json:
            raise ApiError(415, "Send JSON")

    @app.after_request
    def headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        if request.is_secure:
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        if "/api/" in request.path or resp.mimetype == "text/html":
            resp.headers["Cache-Control"] = "no-store"
        return resp

    asset_version = int(time.time())     # changes on every restart so browsers fetch fresh CSS/JS

    @app.context_processor
    def inject():
        rest, user = g.get("rest"), g.get("user")
        s = database.all_settings() if rest else {}
        base = f"/r/{g.slug}" if rest else ""
        cfg = {"user": user, "base": base, "slug": g.get("slug") or ""}
        if user:
            cfg.update(restaurant=s["restaurant_name"], whatsapp=s["whatsapp_template"],
                       upi_vpa=s["upi_vpa"], upi_name=s["upi_name"] or s["restaurant_name"],
                       payment_mode=s["payment_mode"])
        return {"user": user, "APP": cfg, "ASSET_V": asset_version, "SET": s, "BASE": base,
                "restaurant_name": s["restaurant_name"] if rest else "Flotoken"}

    @app.template_filter("ist")
    def ist_filter(ms, fmt="%d %b %Y, %I:%M %p"):
        return ist(ms).strftime(fmt) if ms else ""

    @app.errorhandler(ApiError)
    def api_error(e):
        return jsonify(error=e.message, **e.extra), e.code

    @app.errorhandler(404)
    def not_found(_e):
        if "/api/" in request.path:
            return jsonify(error="Not found"), 404
        return render_template("error.html", code=404, message="Page not found"), 404

    @app.errorhandler(413)
    def too_big(_e):
        return jsonify(error="Request too large"), 413

    @app.errorhandler(500)
    def server_error(_e):
        if "/api/" in request.path:
            return jsonify(error="Something went wrong on the server"), 500
        return render_template("error.html", code=500, message="Something went wrong"), 500

    return app


app = create_app()

if __name__ == "__main__":
    # host 0.0.0.0 lets phones and TVs on the same Wi-Fi open http://<your-laptop-ip>:5000
    app.run(host="0.0.0.0", port=5000, debug=os.environ.get("FLASK_DEBUG", "1") == "1")
