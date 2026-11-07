"""Customer accounts (global) and the restaurant's view of its own customers.

One Flotoken account works at every restaurant. The account lives in platform.db. A restaurant keeps a
snapshot (name, phone) on each order and only ever sees customers who ordered from it, never the global list.

Phone numbers are NOT verified yet (that needs an SMS provider for OTP). Because of that, signing up never
reveals old orders that merely share a number: a customer sees only orders placed while signed in, or that
a cashier attached in person. `phone_verified` is stored for when OTP is added.
"""
import csv
import io
import re
from datetime import timedelta

from flask import Blueprint, Response, g, jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from auth import require, validate_password
from db import db, open_restaurant_db, pdb
from orders import full_order
from util import ApiError, as_int, clean_text, ist, now_ms, rate_limit, today

bp = Blueprint("customers", __name__)            # restaurant side, under /r/<code>/
account_bp = Blueprint("account", __name__)      # the customer's own account, platform level


# ------------------------------------------------------------------ helpers
def norm_phone(value):
    """Canonical Indian mobile: 10 digits starting 6-9. Accepts +91 / 91 / 0 prefixes and spaces."""
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if not re.fullmatch(r"[6-9]\d{9}", digits):
        raise ApiError(400, "Enter a valid 10-digit mobile number")
    return digits


def load_customer():
    g.customer = None
    cid = session.get("cid")
    if cid:
        row = pdb().execute("SELECT id, name, phone, created_at FROM customers WHERE id = ?", (cid,)).fetchone()
        g.customer = dict(row) if row else None
        if row is None:
            session.pop("cid", None)


def require_customer():
    if g.get("customer") is None:
        raise ApiError(401, "Please log in to continue")
    return g.customer


def _login(customer_id):
    p = pdb()
    p.execute("UPDATE customers SET last_login_at = ?, login_count = login_count + 1 WHERE id = ?", (now_ms(), customer_id))
    p.commit()
    session["cid"] = customer_id
    session.permanent = True


def _order_card(o):
    """A customer's own past order, as shown in My orders."""
    return {"code": o["code"], "tok": o["tok"], "day": o["day"], "status": o["status"], "created_at": o["created_at"],
            "total": o["payable"], "rating": o["rating"], "rating_note": o["rating_note"],
            "items": [{"id": i["id"], "name": i["name"], "qty": i["qty"], "price": i["price"]} for i in o["items"]]}


def _my_restaurants(customer_id, slug=None):
    sql = ("SELECT r.id, r.slug, r.name FROM customer_hotels h JOIN restaurants r ON r.id = h.restaurant_id "
           "WHERE h.customer_id = ?" + (" AND r.slug = ?" if slug else ""))
    return [dict(r) for r in pdb().execute(sql, (customer_id, slug) if slug else (customer_id,))]


# ------------------------------------------------------------------ the customer's own account (platform level)
@account_bp.post("/api/customer/signup")
def signup():
    rate_limit("signup:" + (request.remote_addr or "?"), 8, 3600, "Too many sign-ups from this device. Try again later.")
    data = request.get_json(silent=True) or {}
    name = clean_text(data.get("name"), 40, "Name", required=True)
    phone = norm_phone(data.get("phone"))
    validate_password(data.get("password"))
    if data.get("consent") is not True:
        raise ApiError(400, "Please tick the box to agree to how your details are used")
    p = pdb()
    if p.execute("SELECT 1 FROM customers WHERE phone = ?", (phone,)).fetchone():
        raise ApiError(409, "This number already has an account. Please log in.")
    cid = p.execute("INSERT INTO customers (name, phone, password_hash, consent_at, created_at) VALUES (?,?,?,?,?)",
                    (name, phone, generate_password_hash(data["password"]), now_ms(), now_ms())).lastrowid
    p.commit()
    _login(cid)
    return jsonify(ok=True, customer={"id": cid, "name": name, "phone": phone}), 201


@account_bp.post("/api/customer/login")
def login():
    data = request.get_json(silent=True) or {}
    phone = norm_phone(data.get("phone"))
    rate_limit("clogin-ip:" + (request.remote_addr or "?"), 15, 300, "Too many attempts. Try again in 5 minutes.")
    rate_limit("clogin-phone:" + phone, 6, 600, "Too many attempts for this number. Try again in 10 minutes.")
    row = pdb().execute("SELECT id, name, phone, password_hash FROM customers WHERE phone = ?", (phone,)).fetchone()
    if row is None or not check_password_hash(row["password_hash"], str(data.get("password") or "")):
        raise ApiError(401, "Wrong mobile number or password")
    _login(row["id"])
    return jsonify(ok=True, customer={"id": row["id"], "name": row["name"], "phone": row["phone"]})


@account_bp.post("/api/customer/logout")
def logout():
    session.pop("cid", None)
    return jsonify(ok=True)


@account_bp.get("/api/customer/me")
def me():
    c = g.customer
    return jsonify(customer={"id": c["id"], "name": c["name"], "phone": c["phone"]} if c else None)


@account_bp.put("/api/customer/me")
def update_me():
    c = require_customer()
    name = clean_text((request.get_json(silent=True) or {}).get("name"), 40, "Name", required=True)
    pdb().execute("UPDATE customers SET name = ? WHERE id = ?", (name, c["id"]))
    pdb().commit()
    return jsonify(ok=True, customer={"id": c["id"], "name": name, "phone": c["phone"]})


@account_bp.post("/api/customer/password")
def change_password():
    c = require_customer()
    data = request.get_json(silent=True) or {}
    row = pdb().execute("SELECT password_hash FROM customers WHERE id = ?", (c["id"],)).fetchone()
    if not check_password_hash(row["password_hash"], str(data.get("current") or "")):
        raise ApiError(400, "Current password is wrong")
    validate_password(data.get("new"))
    pdb().execute("UPDATE customers SET password_hash = ? WHERE id = ?", (generate_password_hash(data["new"]), c["id"]))
    pdb().commit()
    return jsonify(ok=True)


@account_bp.delete("/api/customer/me")
def delete_me():
    """Delete the account. Bills stay in each restaurant's records but lose the customer's name and number."""
    c = require_customer()
    data = request.get_json(silent=True) or {}
    row = pdb().execute("SELECT password_hash FROM customers WHERE id = ?", (c["id"],)).fetchone()
    if not check_password_hash(row["password_hash"], str(data.get("password") or "")):
        raise ApiError(400, "Password is wrong")
    for r in _my_restaurants(c["id"]):
        con = open_restaurant_db(r["slug"])
        try:
            con.execute("UPDATE orders SET customer_id = NULL, customer_name = 'Deleted customer', phone = '' WHERE customer_id = ?", (c["id"],))
            con.commit()
        finally:
            con.close()
    pdb().execute("DELETE FROM customer_hotels WHERE customer_id = ?", (c["id"],))
    pdb().execute("DELETE FROM customers WHERE id = ?", (c["id"],))
    pdb().commit()
    session.pop("cid", None)
    return jsonify(ok=True)


@account_bp.get("/api/customer/orders")
def my_orders():
    """The customer's orders at every restaurant (or one, with ?r=<code>), newest first."""
    c = require_customer()
    cards = []
    for r in _my_restaurants(c["id"], (request.args.get("r") or "").lower() or None):
        con = open_restaurant_db(r["slug"])
        try:
            for row in con.execute("SELECT id FROM orders WHERE customer_id = ? ORDER BY id DESC LIMIT 25", (c["id"],)).fetchall():
                card = _order_card(full_order(row["id"], conn=con))
                card["restaurant"] = {"slug": r["slug"], "name": r["name"]}
                cards.append(card)
        finally:
            con.close()
    cards.sort(key=lambda x: x["created_at"], reverse=True)
    return jsonify(orders=cards[:40])


# ------------------------------------------------------------------ rating (restaurant-scoped)
@bp.post("/api/public/orders/<code>/rating")
def rate_order(code):
    """Body: {rating: 1-5, note?}. Only the customer who owns a collected order, once."""
    c = require_customer()
    row = db().execute("SELECT id, status, customer_id, rating FROM orders WHERE code = ?", (code[:20],)).fetchone()
    if row is None or row["customer_id"] != c["id"]:
        raise ApiError(404, "Order not found")
    if row["status"] != "collected":
        raise ApiError(409, "You can rate an order after you have collected it")
    if row["rating"] is not None:
        raise ApiError(409, "You have already rated this order")
    data = request.get_json(silent=True) or {}
    rating = as_int(data.get("rating"), "Rating", 1, 5)
    note = clean_text(data.get("note"), 200, "Comment")
    db().execute("UPDATE orders SET rating = ?, rating_note = ?, rated_at = ? WHERE id = ?", (rating, note, now_ms(), row["id"]))
    db().execute("INSERT INTO order_log (order_id, text, at, user) VALUES (?,?,?,?)",
                 (row["id"], f"Customer rated {rating}/5" + (f": {note}" if note else ""), now_ms(), "customer"))
    db().commit()
    return jsonify(ok=True, rating=rating)


# ------------------------------------------------------------------ restaurant side: its own customers
# One row per customer who ordered here. Name and phone are the snapshot on their latest order.
LOCAL_SQL = """
WITH agg AS (
  SELECT o.customer_id AS id, MAX(o.id) AS last_id, MIN(o.created_at) AS first_order_at, MAX(o.created_at) AS last_order_at,
         SUM(CASE WHEN o.status != 'cancelled' THEN 1 ELSE 0 END) AS orders,
         (SELECT COALESCE(SUM(oi.price * oi.qty), 0) FROM order_items oi JOIN orders x ON x.id = oi.order_id
            WHERE x.customer_id = o.customer_id AND x.status != 'cancelled') AS spent
  FROM orders o WHERE o.customer_id IS NOT NULL GROUP BY o.customer_id)
SELECT agg.*, l.customer_name AS name, l.phone AS phone FROM agg JOIN orders l ON l.id = agg.last_id
"""


def _search(q, limit):
    where, args = "", []
    q = clean_text(q, 40)
    digits = re.sub(r"\D", "", q)
    if q.startswith("+91"):
        digits = digits[2:]
    if q:
        if len(digits) >= 3 and not re.search(r"[^\W\d_]", q):       # no letters: a phone number
            where, args = " WHERE phone LIKE ?", [f"%{digits[-10:]}%"]
        else:
            where, args = " WHERE name LIKE ?", [f"%{q}%"]
    order = {"spent": "spent DESC", "orders": "orders DESC", "joined": "first_order_at DESC"}.get(
        request.args.get("sort", "recent"), "last_order_at DESC")
    return [dict(r) for r in db().execute(f"SELECT * FROM ({LOCAL_SQL}){where} ORDER BY {order}, id DESC LIMIT ?", args + [limit])]


@bp.get("/api/customers")
@require("cashier")
def list_customers():
    limit = as_int(request.args.get("limit", 200), "Limit", 1, 500)
    found = _search(request.args.get("q"), limit)
    q = clean_text(request.args.get("q"), 40)
    try:   # a full mobile number also finds a Flotoken account that has not ordered here yet (cashier types it in person)
        phone = norm_phone(q) if q and not re.search(r"[^\W\d_]", q) else None
    except ApiError:
        phone = None
    if phone and not any(c["phone"] == phone for c in found):
        acct = pdb().execute("SELECT id, name, phone FROM customers WHERE phone = ?", (phone,)).fetchone()
        if acct:
            found.append({**dict(acct), "orders": 0, "spent": 0, "last_order_at": None, "first_order_at": None, "new_here": True})
    total = db().execute("SELECT COUNT(DISTINCT customer_id) FROM orders WHERE customer_id IS NOT NULL").fetchone()[0]
    return jsonify(customers=found, total=total)


@bp.get("/api/customers/<int:cid>")
@require("cashier")
def customer_detail(cid):
    d = db()
    row = next((dict(r) for r in d.execute(f"SELECT * FROM ({LOCAL_SQL}) WHERE id = ?", (cid,))), None)
    if row is None:
        raise ApiError(404, "Customer not found")
    favourites = [dict(r) for r in d.execute(
        "SELECT oi.name, SUM(oi.qty) AS qty FROM order_items oi JOIN orders o ON o.id = oi.order_id "
        "WHERE o.customer_id = ? AND o.status != 'cancelled' GROUP BY oi.name ORDER BY qty DESC, oi.name LIMIT 3", (cid,))]
    ids = d.execute("SELECT id FROM orders WHERE customer_id = ? ORDER BY id DESC LIMIT 30", (cid,)).fetchall()
    orders = [_order_card(full_order(r["id"])) for r in ids]
    rated = [o["rating"] for o in orders if o["rating"]]
    return jsonify(customer=row, favourites=favourites, orders=orders,
                   avg_rating=round(sum(rated) / len(rated), 1) if rated else None)


@bp.get("/api/customers.csv")
@require()
def customers_csv():
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Name", "Mobile", "First order", "Last order", "Orders", "Spent (Rs)"])
    fmt = "%Y-%m-%d %H:%M"
    for c in _search("", 100000):
        w.writerow([c["name"], c["phone"], ist(c["first_order_at"]).strftime(fmt), ist(c["last_order_at"]).strftime(fmt), c["orders"], c["spent"]])
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=flotoken-customers-{today()}.csv"})


# ------------------------------------------------------------------ owner's business dashboard (this restaurant only)
@bp.get("/api/admin/business")
@require()
def business():
    d = db()
    now = now_ms()
    day = 86400000
    one = lambda sql, *a: d.execute(sql, a).fetchone()[0] or 0
    live = "status != 'cancelled'"
    people = [dict(r) for r in d.execute(f"SELECT id, orders, first_order_at, last_order_at, spent FROM ({LOCAL_SQL})")]
    ordered = len(people)
    repeat = sum(1 for p in people if p["orders"] >= 2)
    orders_all = one(f"SELECT COUNT(*) FROM orders WHERE {live}")
    orders_linked = one(f"SELECT COUNT(*) FROM orders WHERE {live} AND customer_id IS NOT NULL")
    revenue = one("SELECT SUM(oi.price * oi.qty) FROM order_items oi JOIN orders o ON o.id = oi.order_id WHERE o.status != 'cancelled'")
    ratings = [r["rating"] for r in d.execute("SELECT rating FROM orders WHERE rating IS NOT NULL")]
    dist = {str(n): ratings.count(n) for n in (5, 4, 3, 2, 1)}

    days = [(ist(now) - timedelta(days=n)).strftime("%Y-%m-%d") for n in range(13, -1, -1)]
    new_by_day = {x: 0 for x in days}
    for p in people:
        k = ist(p["first_order_at"]).strftime("%Y-%m-%d")
        if k in new_by_day:
            new_by_day[k] += 1
    orders_by_day = {r["day"]: r["n"] for r in d.execute(
        f"SELECT day, COUNT(*) AS n FROM orders WHERE {live} AND day >= ? GROUP BY day", (days[0],))}
    top = [dict(r) for r in d.execute(f"SELECT * FROM ({LOCAL_SQL}) WHERE orders > 0 ORDER BY spent DESC, orders DESC LIMIT 5")]
    staff = {r["role"]: r["n"] for r in d.execute("SELECT role, COUNT(*) AS n FROM users WHERE active = 1 GROUP BY role")}
    return jsonify(
        customers={"total": ordered, "new_7d": sum(1 for p in people if p["first_order_at"] >= now - 7 * day),
                   "new_30d": sum(1 for p in people if p["first_order_at"] >= now - 30 * day),
                   "active_7d": sum(1 for p in people if p["last_order_at"] >= now - 7 * day),
                   "repeat": repeat, "repeat_percent": round(100 * repeat / ordered) if ordered else 0},
        orders={"total": orders_all, "linked": orders_linked, "app": one(f"SELECT COUNT(*) FROM orders WHERE source = 'app' AND {live}"),
                "counter": one(f"SELECT COUNT(*) FROM orders WHERE source = 'counter' AND {live}"),
                "linked_percent": round(100 * orders_linked / orders_all) if orders_all else 0,
                "average": round(revenue / orders_all) if orders_all else 0, "revenue": revenue},
        ratings={"count": len(ratings), "avg": round(sum(ratings) / len(ratings), 1) if ratings else None, "distribution": dist},
        trend=[{"day": x, "signups": new_by_day[x], "orders": orders_by_day.get(x, 0)} for x in days],
        top_customers=top, staff=staff)
