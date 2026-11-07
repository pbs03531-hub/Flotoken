"""Staff login and roles (per restaurant).

Roles:  owner   - everything (menu, staff, settings, reports)
        cashier - counter orders, payments, refunds, cancel, hand over
        kitchen - start cooking, mark ready, mark items sold out
"""
from functools import wraps

from flask import Blueprint, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

import db as database
from util import ApiError, clean_text, now_ms, rate_limit

bp = Blueprint("auth", __name__)
ROLES = ("owner", "cashier", "kitchen")
HOME_ENDPOINT = {"owner": "pages.admin_page", "cashier": "pages.counter_page", "kitchen": "pages.parcel_page"}


def home_url(role):
    """Where each role starts, inside the current restaurant (/r/<code>/...)."""
    return url_for(HOME_ENDPOINT.get(role, "pages.order_page"))


def load_user():
    """A staff login belongs to ONE restaurant: user ids repeat across restaurants, so the session also
    remembers which restaurant it was issued for and is ignored anywhere else."""
    g.user = None
    uid = session.get("uid")
    if uid and g.get("rest") and session.get("srid") == g.rest["id"]:
        row = database.db().execute(
            "SELECT id, username, role FROM users WHERE id = ? AND active = 1", (uid,)).fetchone()
        g.user = dict(row) if row else None
        if row is None:
            session.pop("uid", None)
            session.pop("srid", None)


def require(*roles, page=False):
    """Protect a route. The owner can always do everything; with no roles listed it is owner-only.
    page=True redirects to the right screen instead of returning a JSON error."""
    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if g.user is None:
                if page:
                    return redirect(url_for("auth.login_page"))
                raise ApiError(401, "Please sign in")
            if g.user["role"] != "owner" and g.user["role"] not in roles:
                if page:
                    return redirect(home_url(g.user["role"]))
                raise ApiError(403, "You do not have permission for this")
            return view(*args, **kwargs)
        return wrapper
    return decorator


def has_users():
    return database.db().execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None


def validate_password(password):
    if not isinstance(password, str) or len(password) < 6:
        raise ApiError(400, "Password must be at least 6 characters")
    if len(password) > 100:
        raise ApiError(400, "Password is too long")


def validate_username(username):
    username = clean_text(username, 30, "Username", required=True)
    if not username.replace("_", "").replace(".", "").isalnum():
        raise ApiError(400, "Username can only contain letters, numbers, dot and underscore")
    return username


# ------------------------------------------------------------------ pages
@bp.get("/login")
def login_page():
    if g.user:
        return redirect(home_url(g.user["role"]))
    return render_template("login.html")


# ------------------------------------------------------------------ API
@bp.post("/api/auth/login")
def api_login():
    data = request.get_json(silent=True) or {}
    username, password = str(data.get("username") or "").strip(), str(data.get("password") or "")
    rate_limit(f"login:{g.rest['id']}:{request.remote_addr or '?'}", 8, 300, "Too many sign-in attempts. Try again in 5 minutes.")
    row = database.db().execute(
        "SELECT id, password_hash, role FROM users WHERE username = ? AND active = 1", (username,)).fetchone()
    if row is None or not check_password_hash(row["password_hash"], password):
        raise ApiError(401, "Wrong username or password")
    session["uid"], session["srid"] = row["id"], g.rest["id"]
    session.permanent = True
    return jsonify(ok=True, home=home_url(row["role"]))


@bp.post("/api/auth/logout")
def api_logout():
    session.pop("uid", None)
    session.pop("srid", None)
    return jsonify(ok=True)


@bp.get("/api/auth/me")
def api_me():
    return jsonify(user=g.user)


@bp.post("/api/auth/password")
@require(*ROLES)
def api_change_password():
    data = request.get_json(silent=True) or {}
    d = database.db()
    row = d.execute("SELECT password_hash FROM users WHERE id = ?", (g.user["id"],)).fetchone()
    if not check_password_hash(row["password_hash"], str(data.get("current") or "")):
        raise ApiError(400, "Current password is wrong")
    validate_password(data.get("new"))
    d.execute("UPDATE users SET password_hash = ? WHERE id = ?", (generate_password_hash(data["new"]), g.user["id"]))
    d.commit()
    return jsonify(ok=True)
