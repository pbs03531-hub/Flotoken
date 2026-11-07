"""Customer accounts, order history, ratings, and the restaurant's view of its customers.

Customers sign up with name + mobile number + password and must be signed in to order from the app.
Walk-in customers are served by the cashier, who can attach an existing customer to a counter order.

Phone numbers are NOT verified yet (that needs an SMS provider for OTP). Because of that, signing up never
reveals old orders that merely share the same number: a customer sees only orders placed while signed in,
or that the cashier attached to their account in person. `phone_verified` is stored for when OTP is added.
"""
import csv
import io
import re
import secrets
from datetime import timedelta

from flask import Blueprint, Response, g, jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash

import db as database
from auth import require, validate_password
from db import db
from orders import full_order, public_view
from util import IST, ApiError, as_int, clean_text, ist, now_ms, rate_limit, today

bp = Blueprint("customers", __name__)

PLAN = {"yearly": 7000, "monthly": 649, "gst_percent": 18}   # Rs; monthly = 7000 / 12 + about 11%


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
        row = db().execute("SELECT id, name, phone, created_at FROM customers WHERE id = ?", (cid,)).fetchone()
        g.customer = dict(row) if row else None
        if row is None:
            session.pop("cid", None)


def require_customer():
    if g.get("customer") is None:
        raise ApiError(401, "Please log in to continue")
    return g.customer


def gst_breakdown(price, percent=PLAN["gst_percent"]):
    """GST added on top of `price`, and the base/GST inside a GST-inclusive `price`. Rupees, 2 decimals."""
    rate = percent / 100
    return {
        "price": price, "percent": percent,
        "add_gst": round(price * rate, 2), "add_total": round(price * (1 + rate), 2),
        "incl_base": round(price / (1 + rate), 2), "incl_gst": round(price - price / (1 + rate), 2),
    }


def _login(customer_id):
    d = db()
    d.execute("UPDATE customers SET last_login_at = ?, login_count = login_count + 1 WHERE id = ?", (now_ms(), customer_id))
    d.commit()
    session["cid"] = customer_id
    session.permanent = True


def _order_card(o):
    """A customer's own past order, as shown in My orders."""
    return {"code": o["code"], "tok": o["tok"], "day": o["day"], "status": o["status"], "created_at": o["created_at"],
            "total": o["payable"], "rating": o["rating"], "items": [{"id": i["id"], "name": i["name"], "qty": i["qty"],
                                                                      "price": i["price"]} for i in o["items"]]}


# ------------------------------------------------------------------ customer API
@bp.post("/api/customer/signup")
def signup():
    rate_limit("signup:" + (request.remote_addr or "?"), 8, 3600, "Too many sign-ups from this device. Try again later.")
    data = request.get_json(silent=True) or {}
    name = clean_text(data.get("name"), 40, "Name", required=True)
    phone = norm_phone(data.get("phone"))
    validate_password(data.get("password"))
    if data.get("consent") is not True:
        raise ApiError(400, "Please tick the box to agree to how your details are used")
    d = db()
    if d.execute("SELECT 1 FROM customers WHERE phone = ?", (phone,)).fetchone():
        raise ApiError(409, "This number already has an account. Please log in.")
    cid = d.execute("INSERT INTO customers (name, phone, password_hash, consent_at, created_at) VALUES (?,?,?,?,?)",
                    (name, phone, generate_password_hash(data["password"]), now_ms(), now_ms())).lastrowid
    d.commit()
    _login(cid)
    return jsonify(ok=True, customer={"id": cid, "name": name, "phone": phone}), 201


@bp.post("/api/customer/login")
def login():
    data = request.get_json(silent=True) or {}
    phone = norm_phone(data.get("phone"))
    rate_limit("clogin-ip:" + (request.remote_addr or "?"), 15, 300, "Too many attempts. Try again in 5 minutes.")
    rate_limit("clogin-phone:" + phone, 6, 600, "Too many attempts for this number. Try again in 10 minutes.")
    row = db().execute("SELECT id, name, phone, password_hash FROM customers WHERE phone = ?", (phone,)).fetchone()
    if row is None or not check_password_hash(row["password_hash"], str(data.get("password") or "")):
        raise ApiError(401, "Wrong mobile number or password")
    _login(row["id"])
    return jsonify(ok=True, customer={"id": row["id"], "name": row["name"], "phone": row["phone"]})


@bp.post("/api/customer/logout")
def logout():
    session.pop("cid", None)
    return jsonify(ok=True)


@bp.get("/api/customer/me")
def me():
    c = g.customer
    return jsonify(customer={"id": c["id"], "name": c["name"], "phone": c["phone"]} if c else None)


@bp.put("/api/customer/me")
def update_me():
    c = require_customer()
    name = clean_text((request.get_json(silent=True) or {}).get("name"), 40, "Name", required=True)
    db().execute("UPDATE customers SET name = ? WHERE id = ?", (name, c["id"]))
    db().commit()
    return jsonify(ok=True, customer={"id": c["id"], "name": name, "phone": c["phone"]})


@bp.post("/api/customer/password")
def change_password():
    c = require_customer()
    data = request.get_json(silent=True) or {}
    row = db().execute("SELECT password_hash FROM customers WHERE id = ?", (c["id"],)).fetchone()
    if not check_password_hash(row["password_hash"], str(data.get("current") or "")):
        raise ApiError(400, "Current password is wrong")
    validate_password(data.get("new"))
    db().execute("UPDATE customers SET password_hash = ? WHERE id = ?", (generate_password_hash(data["new"]), c["id"]))
    db().commit()
    return jsonify(ok=True)


@bp.delete("/api/customer/me")
def delete_me():
    """Delete the account. Bills stay for the restaurant's accounts but lose the customer's name and number."""
    c = require_customer()
    data = request.get_json(silent=True) or {}
    row = db().execute("SELECT password_hash FROM customers WHERE id = ?", (c["id"],)).fetchone()
    if not check_password_hash(row["password_hash"], str(data.get("password") or "")):
        raise ApiError(400, "Password is wrong")
    d = db()
    d.execute("UPDATE orders SET customer_id = NULL, customer_name = 'Deleted customer', phone = '' WHERE customer_id = ?", (c["id"],))
    d.execute("DELETE FROM customers WHERE id = ?", (c["id"],))
    d.commit()
    session.pop("cid", None)
    return jsonify(ok=True)


@bp.get("/api/customer/orders")
def my_orders():
    c = require_customer()
    ids = db().execute("SELECT id FROM orders WHERE customer_id = ? ORDER BY id DESC LIMIT 40", (c["id"],)).fetchall()
    return jsonify(orders=[_order_card(full_order(r["id"])) for r in ids])


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


# ------------------------------------------------------------------ restaurant side: customer list
STATS_SQL = """
SELECT c.id, c.name, c.phone, c.phone_verified, c.created_at, c.last_login_at, c.login_count,
  (SELECT COUNT(*) FROM orders o WHERE o.customer_id = c.id AND o.status != 'cancelled') AS orders,
  (SELECT COALESCE(SUM(oi.price * oi.qty), 0) FROM order_items oi JOIN orders o ON o.id = oi.order_id
     WHERE o.customer_id = c.id AND o.status != 'cancelled') AS spent,
  (SELECT MAX(o.created_at) FROM orders o WHERE o.customer_id = c.id) AS last_order_at
FROM customers c
"""


def _search(q, limit):
    where, args = "", []
    q = clean_text(q, 40)
    digits = re.sub(r"\D", "", q)
    if q.startswith("+91"):
        digits = digits[2:]                       # a country code typed in front of a partial number
    if q:
        if len(digits) >= 3 and not re.search(r"[^\W\d_]", q):      # no letters: treat as a phone number
            where, args = " WHERE c.phone LIKE ?", [f"%{digits[-10:]}%"]
        else:
            where, args = " WHERE c.name LIKE ?", [f"%{q}%"]
    sort = request.args.get("sort", "recent")
    order = {"spent": "spent DESC", "orders": "orders DESC", "joined": "c.created_at DESC"}.get(
        sort, "COALESCE(last_order_at, c.created_at) DESC")
    return [dict(r) for r in db().execute(f"{STATS_SQL}{where} ORDER BY {order}, c.id DESC LIMIT ?", args + [limit])]


@bp.get("/api/customers")
@require("cashier")
def list_customers():
    limit = as_int(request.args.get("limit", 200), "Limit", 1, 500)
    total = db().execute("SELECT COUNT(*) FROM customers").fetchone()[0]
    return jsonify(customers=_search(request.args.get("q"), limit), total=total)


@bp.get("/api/customers/<int:cid>")
@require("cashier")
def customer_detail(cid):
    d = db()
    row = next((c for c in [dict(r) for r in d.execute(STATS_SQL + " WHERE c.id = ?", (cid,))]), None)
    if row is None:
        raise ApiError(404, "Customer not found")
    favourites = [dict(r) for r in d.execute(
        "SELECT oi.name, SUM(oi.qty) AS qty FROM order_items oi JOIN orders o ON o.id = oi.order_id "
        "WHERE o.customer_id = ? AND o.status != 'cancelled' GROUP BY oi.name ORDER BY qty DESC, oi.name LIMIT 3", (cid,))]
    ids = d.execute("SELECT id FROM orders WHERE customer_id = ? ORDER BY id DESC LIMIT 30", (cid,)).fetchall()
    orders = [{**_order_card(o), "rating_note": o["rating_note"]} for o in (full_order(r["id"]) for r in ids)]
    rated = [o["rating"] for o in orders if o["rating"]]
    return jsonify(customer=row, favourites=favourites, orders=orders,
                   avg_rating=round(sum(rated) / len(rated), 1) if rated else None)


@bp.post("/api/customers/<int:cid>/reset-password")
@require("cashier")
def reset_password(cid):
    """For a customer who forgot their password: staff give them a temporary one, shown once."""
    d = db()
    if not d.execute("SELECT 1 FROM customers WHERE id = ?", (cid,)).fetchone():
        raise ApiError(404, "Customer not found")
    temp = "".join(secrets.choice("23456789") for _ in range(6))
    d.execute("UPDATE customers SET password_hash = ? WHERE id = ?", (generate_password_hash(temp), cid))
    d.commit()
    return jsonify(ok=True, temporary_password=temp)


@bp.get("/api/customers.csv")
@require()
def customers_csv():
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Name", "Mobile", "Joined", "Last login", "Logins", "Orders", "Spent (Rs)", "Last order"])
    fmt = "%Y-%m-%d %H:%M"
    for c in _search("", 100000):
        w.writerow([c["name"], c["phone"], ist(c["created_at"]).strftime(fmt),
                    ist(c["last_login_at"]).strftime(fmt) if c["last_login_at"] else "", c["login_count"],
                    c["orders"], c["spent"], ist(c["last_order_at"]).strftime(fmt) if c["last_order_at"] else ""])
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=flotoken-customers-{today()}.csv"})


# ------------------------------------------------------------------ owner's business dashboard
@bp.get("/api/admin/business")
@require()
def business():
    """Everything the owner wants to know about who uses the app, in one call."""
    d = db()
    now = now_ms()
    day = 86400000
    one = lambda sql, *a: d.execute(sql, a).fetchone()[0] or 0
    total = one("SELECT COUNT(*) FROM customers")
    ordered = one("SELECT COUNT(DISTINCT customer_id) FROM orders WHERE customer_id IS NOT NULL AND status != 'cancelled'")
    repeat = one("SELECT COUNT(*) FROM (SELECT customer_id FROM orders WHERE customer_id IS NOT NULL AND status != 'cancelled' "
                 "GROUP BY customer_id HAVING COUNT(*) >= 2)")
    orders_all = one("SELECT COUNT(*) FROM orders WHERE status != 'cancelled'")
    orders_linked = one("SELECT COUNT(*) FROM orders WHERE status != 'cancelled' AND customer_id IS NOT NULL")
    ratings = [r["rating"] for r in d.execute("SELECT rating FROM orders WHERE rating IS NOT NULL")]
    dist = {str(n): ratings.count(n) for n in (5, 4, 3, 2, 1)}

    # last 14 days, oldest first, in IST
    days = [(ist(now) - timedelta(days=n)).strftime("%Y-%m-%d") for n in range(13, -1, -1)]
    signups = {x: 0 for x in days}
    for r in d.execute("SELECT created_at FROM customers WHERE created_at >= ?", (now - 15 * day,)):
        key = ist(r["created_at"]).strftime("%Y-%m-%d")
        if key in signups:
            signups[key] += 1
    orders_by_day = {r["day"]: r["n"] for r in d.execute(
        "SELECT day, COUNT(*) AS n FROM orders WHERE status != 'cancelled' AND day >= ? GROUP BY day", (days[0],))}

    top = [dict(r) for r in d.execute(STATS_SQL + " ORDER BY spent DESC, orders DESC LIMIT 5") if r["orders"]]
    staff = {r["role"]: r["n"] for r in d.execute("SELECT role, COUNT(*) AS n FROM users WHERE active = 1 GROUP BY role")}
    return jsonify(
        customers={"total": total, "new_7d": one("SELECT COUNT(*) FROM customers WHERE created_at >= ?", now - 7 * day),
                   "new_30d": one("SELECT COUNT(*) FROM customers WHERE created_at >= ?", now - 30 * day),
                   "active_7d": one("SELECT COUNT(*) FROM customers WHERE last_login_at >= ?", now - 7 * day),
                   "ordered": ordered, "repeat": repeat, "never_ordered": total - ordered,
                   "repeat_percent": round(100 * repeat / ordered) if ordered else 0},
        orders={"total": orders_all, "linked": orders_linked, "app": one("SELECT COUNT(*) FROM orders WHERE source = 'app' AND status != 'cancelled'"),
                "counter": one("SELECT COUNT(*) FROM orders WHERE source = 'counter' AND status != 'cancelled'"),
                "linked_percent": round(100 * orders_linked / orders_all) if orders_all else 0},
        ratings={"count": len(ratings), "avg": round(sum(ratings) / len(ratings), 1) if ratings else None, "distribution": dist},
        trend=[{"day": x, "signups": signups[x], "orders": orders_by_day.get(x, 0)} for x in days],
        top_customers=top, staff=staff, plan=PLAN, gst=gst_breakdown(PLAN["monthly"]))
