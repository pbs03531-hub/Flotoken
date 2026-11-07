"""The Flotoken platform: opening screen, the two logins, your own dashboard for all restaurants.

Platform-level addresses (no restaurant in them):
  /                    opening screen: Restaurant login | Customer
  /staff               restaurant staff / owner login (pick restaurant, username, password)
  /customer            customer sign-up / log-in, then pick a restaurant
  /platform            the Flotoken owner's dashboard (create restaurants, reset logins, see usage)
Everything a restaurant uses lives under /r/<restaurant-code>/ (see app.py).
"""
import json
import os
import re
import sqlite3
from datetime import datetime, timedelta
from functools import wraps

from flask import Blueprint, Response, current_app, g, jsonify, redirect, render_template, request, send_from_directory, session
from werkzeug.security import check_password_hash, generate_password_hash

import db as database
from auth import validate_password, validate_username
from db import open_restaurant_db, pdb, restaurant_path
from pricing import PLAN, gst_breakdown
from util import IST, ApiError, as_int, clean_text, ist, now_ms, rate_limit, today

bp = Blueprint("platform", __name__)

RESERVED = {"platform", "staff", "customer", "api", "static", "admin", "login", "r", "order", "pricing", "offline",
            "healthz", "sw", "manifest", "img", "setup", "www", "flotoken", "demo-null"}
PLANS = ("trial", "monthly", "yearly")
DAY = 86400000


# ------------------------------------------------------------------ platform admin session
def has_platform_admin():
    return pdb().execute("SELECT 1 FROM platform_admins LIMIT 1").fetchone() is not None


def load_platform_admin():
    g.padmin = None
    pid = session.get("pid")
    if pid:
        row = pdb().execute("SELECT id, username FROM platform_admins WHERE id = ?", (pid,)).fetchone()
        g.padmin = dict(row) if row else None
        if row is None:
            session.pop("pid", None)


def require_platform(view):
    @wraps(view)
    def wrapper(*a, **kw):
        if g.get("padmin") is None:
            raise ApiError(401, "Please sign in as the Flotoken owner")
        return view(*a, **kw)
    return wrapper


# ------------------------------------------------------------------ creating and fixing restaurants
def slugify(name):
    s = re.sub(r"[^a-z0-9]+", "-", str(name or "").lower()).strip("-")
    return s[:30].strip("-")


def validate_slug(slug):
    slug = str(slug or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,28}[a-z0-9]", slug):
        raise ApiError(400, "Restaurant code must be 3-30 letters, numbers or hyphens, for example betty-military")
    if slug in RESERVED:
        raise ApiError(400, "That code is reserved. Choose another.")
    return slug


def create_restaurant(name, slug, owner_username, owner_password, plan="trial", sample_menu=True, payment_mode="counter"):
    name = clean_text(name, 60, "Restaurant name", required=True)
    slug = validate_slug(slug or slugify(name))
    username, _ = validate_username(owner_username), validate_password(owner_password)
    if plan not in PLANS:
        raise ApiError(400, "Unknown plan")
    if payment_mode not in ("demo", "counter"):          # UPI needs the owner's UPI ID, so it is switched on in Admin > Settings
        raise ApiError(400, "Unknown payment option")
    p = pdb()
    if p.execute("SELECT 1 FROM restaurants WHERE slug = ?", (slug,)).fetchone() or os.path.exists(restaurant_path(slug)):
        raise ApiError(409, "That restaurant code is already used. Choose another.")
    days = {"trial": 30, "monthly": 31, "yearly": 366}[plan]
    rid = p.execute("INSERT INTO restaurants (slug, name, plan, paid_until, created_at) VALUES (?,?,?,?,?)",
                    (slug, name, plan, now_ms() + days * DAY, now_ms())).lastrowid
    p.commit()
    con = open_restaurant_db(slug)
    try:
        con.execute("INSERT INTO users (username, password_hash, role, created_at) VALUES (?,?,?,?)",
                    (username, generate_password_hash(owner_password), "owner", now_ms()))
        database.set_setting("restaurant_name", name, con)
        database.set_setting("payment_mode", payment_mode, con)
        if sample_menu:
            database.seed_sample_menu(con)
        con.commit()
    finally:
        con.close()
    return rid


def set_owner_login(rest, username, password):
    """Give a restaurant's owner a new password (and optionally a new username). Works even if the owner
    forgot both. Creates the owner login if the restaurant somehow has none."""
    validate_password(password)
    username = validate_username(username) if username else None
    con = open_restaurant_db(rest["slug"])
    try:
        owner = con.execute("SELECT id, username FROM users WHERE role = 'owner' ORDER BY id LIMIT 1").fetchone()
        try:
            if owner:
                con.execute("UPDATE users SET password_hash = ?, active = 1, username = ? WHERE id = ?",
                            (generate_password_hash(password), username or owner["username"], owner["id"]))
            else:
                if not username:
                    raise ApiError(400, "This restaurant has no owner yet. Enter a username for the owner.")
                con.execute("INSERT INTO users (username, password_hash, role, created_at) VALUES (?,?,?,?)",
                            (username, generate_password_hash(password), "owner", now_ms()))
            con.commit()
        except sqlite3.IntegrityError:
            raise ApiError(409, "Another login in that restaurant already uses this username")
        return con.execute("SELECT username FROM users WHERE role = 'owner' ORDER BY id LIMIT 1").fetchone()["username"]
    finally:
        con.close()


def bootstrap(app):
    """Hosting without a shell (Render): create what the environment variables describe.
    PLATFORM_USERNAME + PLATFORM_PASSWORD   the Flotoken owner login. Change the password variable to reset it.
    OWNER_USERNAME + OWNER_PASSWORD + RESTAURANT_NAME   a first restaurant, only while no restaurant exists."""
    env = os.environ.get
    with app.app_context():
        try:
            pu, pw = env("PLATFORM_USERNAME"), env("PLATFORM_PASSWORD")
            if pu and pw:
                try:
                    pu = validate_username(pu)
                    validate_password(pw)
                    row = pdb().execute("SELECT id, password_hash FROM platform_admins WHERE username = ?", (pu,)).fetchone()
                    if row is None:
                        pdb().execute("INSERT INTO platform_admins (username, password_hash, created_at) VALUES (?,?,?)",
                                      (pu, generate_password_hash(pw), now_ms()))
                        print(f"[flotoken] platform owner '{pu}' created from environment variables")
                    elif not check_password_hash(row["password_hash"], pw):
                        pdb().execute("UPDATE platform_admins SET password_hash = ? WHERE id = ?", (generate_password_hash(pw), row["id"]))
                        print(f"[flotoken] platform owner '{pu}' password updated from environment variable")
                    pdb().commit()
                except ApiError as e:
                    print(f"[flotoken] PLATFORM_USERNAME / PLATFORM_PASSWORD ignored: {e.message}")
            ou, op, rn = env("OWNER_USERNAME"), env("OWNER_PASSWORD"), env("RESTAURANT_NAME")
            if ou and op and rn and pdb().execute("SELECT 1 FROM restaurants LIMIT 1").fetchone() is None:
                try:
                    create_restaurant(rn, env("RESTAURANT_CODE"), ou, op, "trial", env("SAMPLE_MENU", "1") == "1", "demo")
                    print(f"[flotoken] first restaurant '{rn}' created from environment variables")
                except ApiError as e:
                    print(f"[flotoken] OWNER_* variables ignored: {e.message}")
        finally:
            database.close_db()


# ------------------------------------------------------------------ pages
@bp.get("/")
def landing():
    return render_template("landing.html")


@bp.get("/staff")
def staff_page():
    return render_template("staff_login.html", prefill=re.sub(r"[^a-z0-9-]", "", request.args.get("r", "").lower()))


@bp.get("/customer")
def customer_page():
    return render_template("customer.html")


@bp.get("/platform")
@bp.get("/platform/setup")
def platform_page():
    return render_template("platform.html")


@bp.get("/pricing")
def pricing_page():
    return render_template("pricing.html")


@bp.get("/manifest.webmanifest")
def manifest():
    data = {"id": "/", "name": "Flotoken", "short_name": "Flotoken", "start_url": "/", "scope": "/",
            "description": "Order takeaway from restaurants, skip the queue, and watch your token live.",
            "display": "standalone", "background_color": "#F3F5F2", "theme_color": "#C2410C", "lang": "en-IN",
            "icons": [{"src": "/static/img/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
                      {"src": "/static/img/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
                      {"src": "/static/img/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}]}
    resp = Response(json.dumps(data), mimetype="application/manifest+json")
    resp.headers["Cache-Control"] = "no-cache"
    return resp


def serve_sw():
    resp = send_from_directory(current_app.static_folder, "sw.js", mimetype="application/javascript")
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@bp.get("/sw.js")
def service_worker():
    return serve_sw()


@bp.get("/offline")
def offline():
    return render_template("offline.html")


@bp.get("/healthz")
def healthz():
    pdb().execute("SELECT 1").fetchone()
    return jsonify(ok=True)


# ------------------------------------------------------------------ public data
@bp.get("/api/public/restaurants")
def public_restaurants():
    """Active restaurants, for the customer's 'choose a restaurant' list and the staff login."""
    rows = pdb().execute("SELECT slug, name FROM restaurants WHERE status = 'active' ORDER BY name COLLATE NOCASE").fetchall()
    return jsonify(restaurants=[dict(r) for r in rows])


@bp.get("/api/public/pricing")
def pricing_data():
    monthly_x12 = PLAN["monthly"] * 12
    return jsonify(plan=PLAN, yearly_per_month=round(PLAN["yearly"] / 12, 2), yearly_saving=monthly_x12 - PLAN["yearly"],
                   gst={"monthly": gst_breakdown(PLAN["monthly"]), "yearly": gst_breakdown(PLAN["yearly"])})


# ------------------------------------------------------------------ platform admin: login
@bp.get("/api/platform/me")
def platform_me():
    a = g.padmin
    return jsonify(admin=a, needs_setup=not has_platform_admin())


@bp.post("/api/platform/setup")
def platform_setup():
    """First run on a new server (no environment variables): create the Flotoken owner login."""
    if has_platform_admin():
        raise ApiError(409, "Already set up. Please log in.")
    rate_limit("psetup:" + (request.remote_addr or "?"), 10, 3600, "Too many attempts")
    data = request.get_json(silent=True) or {}
    username, _ = validate_username(data.get("username")), validate_password(data.get("password"))
    aid = pdb().execute("INSERT INTO platform_admins (username, password_hash, created_at) VALUES (?,?,?)",
                        (username, generate_password_hash(data["password"]), now_ms())).lastrowid
    pdb().commit()
    session["pid"] = aid
    session.permanent = True
    return jsonify(ok=True), 201


@bp.post("/api/platform/login")
def platform_login():
    data = request.get_json(silent=True) or {}
    rate_limit("plogin:" + (request.remote_addr or "?"), 8, 600, "Too many attempts. Try again in 10 minutes.")
    row = pdb().execute("SELECT id, password_hash FROM platform_admins WHERE username = ?", (str(data.get("username") or "").strip(),)).fetchone()
    if row is None or not check_password_hash(row["password_hash"], str(data.get("password") or "")):
        raise ApiError(401, "Wrong username or password")
    session["pid"] = row["id"]
    session.permanent = True
    return jsonify(ok=True)


@bp.post("/api/platform/logout")
def platform_logout():
    session.pop("pid", None)
    return jsonify(ok=True)


@bp.post("/api/platform/password")
@require_platform
def platform_password():
    data = request.get_json(silent=True) or {}
    row = pdb().execute("SELECT password_hash FROM platform_admins WHERE id = ?", (g.padmin["id"],)).fetchone()
    if not check_password_hash(row["password_hash"], str(data.get("current") or "")):
        raise ApiError(400, "Current password is wrong")
    validate_password(data.get("new"))
    pdb().execute("UPDATE platform_admins SET password_hash = ? WHERE id = ?", (generate_password_hash(data["new"]), g.padmin["id"]))
    pdb().commit()
    return jsonify(ok=True)


# ------------------------------------------------------------------ platform admin: dashboard
def hotel_stats(rest):
    """Usage numbers read from one restaurant's own database."""
    con = open_restaurant_db(rest["slug"])
    try:
        one = lambda sql, *a: con.execute(sql, a).fetchone()[0] or 0
        now = now_ms()
        live = "status != 'cancelled'"
        owner = con.execute("SELECT username FROM users WHERE role = 'owner' ORDER BY id LIMIT 1").fetchone()
        return {
            "orders": one(f"SELECT COUNT(*) FROM orders WHERE {live}"),
            "orders_today": one(f"SELECT COUNT(*) FROM orders WHERE {live} AND day = ?", today()),
            "orders_30d": one(f"SELECT COUNT(*) FROM orders WHERE {live} AND created_at >= ?", now - 30 * DAY),
            "sales_30d": one("SELECT SUM(oi.price * oi.qty) FROM order_items oi JOIN orders o ON o.id = oi.order_id "
                             "WHERE o.status != 'cancelled' AND o.created_at >= ?", now - 30 * DAY),
            "customers": one("SELECT COUNT(DISTINCT customer_id) FROM orders WHERE customer_id IS NOT NULL"),
            "staff": one("SELECT COUNT(*) FROM users WHERE active = 1"),
            "last_order_at": one("SELECT MAX(created_at) FROM orders") or None,
            "owner": owner["username"] if owner else None,
            "by_day": {r["day"]: r["n"] for r in con.execute(
                f"SELECT day, COUNT(*) AS n FROM orders WHERE {live} AND day >= ? GROUP BY day", ((ist(now) - timedelta(days=14)).strftime("%Y-%m-%d"),))},
        }
    finally:
        con.close()


@bp.get("/api/platform/overview")
@require_platform
def overview():
    p, now = pdb(), now_ms()
    rows = [dict(r) for r in p.execute("SELECT * FROM restaurants ORDER BY created_at DESC")]
    days = [(ist(now) - timedelta(days=n)).strftime("%Y-%m-%d") for n in range(13, -1, -1)]
    orders_by_day = {d: 0 for d in days}
    for r in rows:
        r.update(hotel_stats(r))
        for d, n in r.pop("by_day").items():
            if d in orders_by_day:
                orders_by_day[d] += n
        r["expired"] = bool(r["paid_until"] and r["paid_until"] < now)
        r["expires_soon"] = bool(r["paid_until"] and now <= r["paid_until"] < now + 7 * DAY)
    signups = {d: 0 for d in days}
    for c in p.execute("SELECT created_at FROM customers WHERE created_at >= ?", (now - 15 * DAY,)):
        k = ist(c["created_at"]).strftime("%Y-%m-%d")
        if k in signups:
            signups[k] += 1
    one = lambda sql, *a: p.execute(sql, a).fetchone()[0] or 0
    active = [r for r in rows if r["status"] == "active"]
    mrr = sum(PLAN["monthly"] if r["plan"] == "monthly" else round(PLAN["yearly"] / 12) for r in active if r["plan"] in ("monthly", "yearly"))
    return jsonify(
        restaurants=rows,
        totals={"restaurants": len(rows), "active": len(active), "suspended": len(rows) - len(active),
                "trial": sum(1 for r in active if r["plan"] == "trial"), "paying": sum(1 for r in active if r["plan"] != "trial"),
                "expired": sum(1 for r in active if r["expired"]), "mrr": mrr,
                "orders": sum(r["orders"] for r in rows), "orders_today": sum(r["orders_today"] for r in rows),
                "orders_30d": sum(r["orders_30d"] for r in rows), "sales_30d": sum(r["sales_30d"] for r in rows),
                "customers": one("SELECT COUNT(*) FROM customers"), "customers_7d": one("SELECT COUNT(*) FROM customers WHERE created_at >= ?", now - 7 * DAY),
                "customers_active_7d": one("SELECT COUNT(*) FROM customers WHERE last_login_at >= ?", now - 7 * DAY)},
        trend=[{"day": d, "signups": signups[d], "orders": orders_by_day[d]} for d in days], plan=PLAN)


@bp.post("/api/platform/restaurants")
@require_platform
def add_restaurant():
    d = request.get_json(silent=True) or {}
    rid = create_restaurant(d.get("name"), d.get("slug"), d.get("owner_username"), d.get("owner_password"),
                            d.get("plan") or "trial", d.get("sample_menu", True) is not False,
                            d.get("payment_mode") or "counter")
    row = pdb().execute("SELECT slug FROM restaurants WHERE id = ?", (rid,)).fetchone()
    return jsonify(ok=True, id=rid, slug=row["slug"]), 201


def _rest(rid):
    row = pdb().execute("SELECT * FROM restaurants WHERE id = ?", (rid,)).fetchone()
    if row is None:
        raise ApiError(404, "Restaurant not found")
    return dict(row)


@bp.put("/api/platform/restaurants/<int:rid>")
@require_platform
def edit_restaurant(rid):
    rest, d = _rest(rid), request.get_json(silent=True) or {}
    name = clean_text(d["name"], 60, "Restaurant name", required=True) if "name" in d else rest["name"]
    status = d.get("status", rest["status"])
    plan = d.get("plan", rest["plan"])
    if status not in ("active", "suspended") or plan not in PLANS:
        raise ApiError(400, "Unknown status or plan")
    paid_until = rest["paid_until"]
    if "paid_until" in d:                      # "YYYY-MM-DD" (end of that day, IST) or empty
        v = str(d["paid_until"] or "").strip()
        if v:
            try:
                paid_until = int(datetime.strptime(v, "%Y-%m-%d").replace(hour=23, minute=59, tzinfo=IST).timestamp() * 1000)
            except ValueError:
                raise ApiError(400, "Date should look like 2027-03-31")
        else:
            paid_until = None
    notes = clean_text(d["notes"], 300, "Notes") if "notes" in d else rest["notes"]
    pdb().execute("UPDATE restaurants SET name=?, status=?, plan=?, paid_until=?, notes=? WHERE id=?",
                  (name, status, plan, paid_until, notes, rid))
    pdb().commit()
    if name != rest["name"]:                    # keep the restaurant's own screens in step
        con = open_restaurant_db(rest["slug"])
        try:
            database.set_setting("restaurant_name", name, con)
            con.commit()
        finally:
            con.close()
    return jsonify(ok=True)


@bp.post("/api/platform/restaurants/<int:rid>/owner")
@require_platform
def reset_owner(rid):
    """For the owner who forgot the username and/or password."""
    rest, d = _rest(rid), request.get_json(silent=True) or {}
    username = set_owner_login(rest, d.get("username"), d.get("password"))
    return jsonify(ok=True, username=username)


@bp.get("/api/platform/customers")
@require_platform
def find_customers():
    q = clean_text(request.args.get("q"), 40)
    digits = re.sub(r"\D", "", q)
    where, args = "", []
    if q:
        if len(digits) >= 3 and not re.search(r"[^\W\d_]", q):
            where, args = " WHERE phone LIKE ?", [f"%{digits[-10:]}%"]
        else:
            where, args = " WHERE name LIKE ?", [f"%{q}%"]
    rows = pdb().execute("SELECT c.id, c.name, c.phone, c.created_at, c.last_login_at, c.login_count, "
                         "(SELECT COUNT(*) FROM customer_hotels h WHERE h.customer_id = c.id) AS restaurants "
                         f"FROM customers c{where} ORDER BY c.created_at DESC LIMIT 50", args).fetchall()
    return jsonify(customers=[dict(r) for r in rows], total=pdb().execute("SELECT COUNT(*) FROM customers").fetchone()[0])


@bp.post("/api/platform/customers/<int:cid>/reset-password")
@require_platform
def reset_customer_password(cid):
    """A customer forgot their password: you set a new one for them (until OTP exists)."""
    import secrets
    if pdb().execute("SELECT 1 FROM customers WHERE id = ?", (cid,)).fetchone() is None:
        raise ApiError(404, "Customer not found")
    temp = "".join(secrets.choice("23456789") for _ in range(6))
    pdb().execute("UPDATE customers SET password_hash = ? WHERE id = ?", (generate_password_hash(temp), cid))
    pdb().commit()
    return jsonify(ok=True, temporary_password=temp)
