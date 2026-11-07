"""Staff login, roles and first-run setup.

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
HOME = {"owner": "/admin", "cashier": "/counter", "kitchen": "/parcel"}


def load_user():
    g.user = None
    uid = session.get("uid")
    if uid:
        row = database.db().execute(
            "SELECT id, username, role FROM users WHERE id = ? AND active = 1", (uid,)).fetchone()
        g.user = dict(row) if row else None
        if row is None:
            session.clear()


def require(*roles, page=False):
    """Protect a route. The owner can always do everything; with no roles listed it is owner-only.
    page=True redirects to the right screen instead of returning a JSON error."""
    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if g.user is None:
                if page:
                    return redirect(url_for("auth.login_page", next=request.path))
                raise ApiError(401, "Please sign in")
            if g.user["role"] != "owner" and g.user["role"] not in roles:
                if page:
                    return redirect(HOME.get(g.user["role"], "/"))
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
    if not has_users():
        return redirect(url_for("auth.setup_page"))
    if g.user:
        return redirect(HOME[g.user["role"]])
    return render_template("login.html", next=request.args.get("next", ""))


@bp.get("/setup")
def setup_page():
    if has_users():
        return redirect(url_for("auth.login_page"))
    return render_template("setup.html")


# ------------------------------------------------------------------ API
@bp.post("/api/auth/setup")
def api_setup():
    """First run only: creates the owner account and restaurant name."""
    if has_users():
        raise ApiError(409, "Setup is already done")
    data = request.get_json(silent=True) or {}
    name = clean_text(data.get("restaurant_name"), 60, "Restaurant name", required=True)
    username = validate_username(data.get("username"))
    validate_password(data.get("password"))
    d = database.db()
    uid = d.execute("INSERT INTO users (username, password_hash, role, created_at) VALUES (?,?,?,?)",
                    (username, generate_password_hash(data["password"]), "owner", now_ms())).lastrowid
    database.set_setting("restaurant_name", name)
    if data.get("sample_menu"):
        database.seed_sample_menu()
    d.commit()
    session.clear()
    session["uid"] = uid
    session.permanent = True
    return jsonify(ok=True, home=HOME["owner"])


@bp.post("/api/auth/login")
def api_login():
    data = request.get_json(silent=True) or {}
    username, password = str(data.get("username") or "").strip(), str(data.get("password") or "")
    ip = request.remote_addr or "?"
    rate_limit("login:" + ip, 8, 300, "Too many sign-in attempts. Try again in 5 minutes.")
    row = database.db().execute(
        "SELECT id, password_hash, role FROM users WHERE username = ? AND active = 1", (username,)).fetchone()
    if row is None or not check_password_hash(row["password_hash"], password):
        raise ApiError(401, "Wrong username or password")
    session.clear()
    session["uid"] = row["id"]
    session.permanent = True
    return jsonify(ok=True, home=HOME[row["role"]])


@bp.post("/api/auth/logout")
def api_logout():
    session.clear()
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
