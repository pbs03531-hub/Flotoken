"""Orders: creation, payments, status changes, edits and cancellation.

Two APIs live here:
  /api/orders...          staff (login required)
  /api/public/...         customers: menu, place order (needs a customer login), track order, token board
"""
import re
import secrets
import sqlite3
from urllib.parse import quote

from flask import Blueprint, Response, g, jsonify, request

import db as database
from auth import require
from db import all_settings, db
from util import (ApiError, as_int, clean_phone, clean_text, now_ms, parse_date, rate_limit, today)

bp = Blueprint("orders", __name__)

NEXT_STATUS = {"placed": "preparing", "preparing": "ready", "ready": "collected"}
STATUS_COLUMN = {"preparing": "preparing_at", "ready": "ready_at", "collected": "collected_at"}
ACTIVE = ("placed", "preparing", "ready")
ALL_STATUSES = ACTIVE + ("collected", "cancelled")


# ------------------------------------------------------------------ helpers
def actor():
    return g.user["username"] if g.get("user") else "customer"


def add_log(order_id, text):
    db().execute("INSERT INTO order_log (order_id, text, at, user) VALUES (?,?,?,?)",
                 (order_id, text, now_ms(), actor()))


def add_payment(order_id, method, amount, ref=""):
    uid = g.user["id"] if g.get("user") else None
    db().execute("INSERT INTO payments (order_id, method, amount, at, user_id, ref) VALUES (?,?,?,?,?,?)",
                 (order_id, method, amount, now_ms(), uid, ref))


def full_order(order_id, full_log=False, conn=None):
    """One order with items, payments and derived money fields. `conn`: another restaurant's database."""
    d = conn or db()
    row = d.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if row is None:
        return None
    o = dict(row)
    o["items"] = [dict(r) for r in d.execute(
        "SELECT item_id AS id, name, price, qty FROM order_items WHERE order_id = ? ORDER BY name", (order_id,))]
    o["total"] = sum(i["price"] * i["qty"] for i in o["items"])
    o["payable"] = 0 if o["status"] == "cancelled" else o["total"]
    o["payments"] = [dict(r) for r in d.execute(
        "SELECT p.method, p.amount, p.at, p.ref, u.username AS staff FROM payments p "
        "LEFT JOIN users u ON u.id = p.user_id WHERE p.order_id = ? ORDER BY p.id", (order_id,))]
    o["paid"] = sum(p["amount"] for p in o["payments"])
    o["due"] = max(0, o["payable"] - o["paid"])         # customer still owes this
    o["refund"] = max(0, o["paid"] - o["payable"])      # restaurant owes this back
    logs = [dict(r) for r in d.execute("SELECT text, at, user FROM order_log WHERE order_id = ? ORDER BY id", (order_id,))]
    o["log"] = logs if full_log else logs[-6:]
    return o


def eta_minutes(settings=None):
    s = settings or all_settings()
    waiting = db().execute(
        "SELECT COUNT(*) FROM orders WHERE day = ? AND status IN ('placed','preparing')", (today(),)).fetchone()[0]
    return int(s["eta_base"]) + int(s["eta_per_order"]) * waiting


def day_summary(day):
    d = db()
    row = d.execute(
        "SELECT SUM(status != 'cancelled') AS orders, SUM(status = 'cancelled') AS cancelled, "
        "SUM(status IN ('placed','preparing','ready')) AS pending FROM orders WHERE day = ?", (day,)).fetchone()
    summary = {"orders": row["orders"] or 0, "cancelled": row["cancelled"] or 0,
               "pending": row["pending"] or 0, "upi": 0, "cash": 0}
    for r in d.execute("SELECT p.method AS m, SUM(p.amount) AS s FROM payments p JOIN orders o ON o.id = p.order_id "
                       "WHERE o.day = ? GROUP BY p.method", (day,)):
        summary[r["m"].lower()] = r["s"]
    return summary


def parse_items(raw):
    """Validate [{id, q}] against the live menu and return [(menu_row, qty)]."""
    if not isinstance(raw, list) or not raw:
        raise ApiError(400, "Add at least one item")
    if len(raw) > 40:
        raise ApiError(400, "Too many different items")
    lines = {}
    for it in raw:
        if not isinstance(it, dict):
            raise ApiError(400, "Invalid item")
        item_id = as_int(it.get("id"), "Item", 1, 10 ** 9)
        qty = as_int(it.get("q"), "Quantity", 1, 50)
        m = db().execute(
            "SELECT m.id, m.name, m.price, m.available FROM menu m JOIN categories c ON c.id = m.category_id "
            "WHERE m.id = ? AND m.active = 1 AND c.active = 1", (item_id,)).fetchone()
        if m is None:
            raise ApiError(400, "An item is no longer on the menu. Please refresh.")
        if not m["available"]:
            raise ApiError(409, f"{m['name']} is sold out", item_id=m["id"])
        prev = lines.get(m["id"], (m, 0))[1]
        if prev + qty > 50:
            raise ApiError(400, "Quantity is too high")
        lines[m["id"]] = (m, prev + qty)
    return list(lines.values())


def create_order(source, raw_items, pay_method, name, phone, note, customer_id=None):
    lines = parse_items(raw_items)
    total = sum(m["price"] * q for m, q in lines)
    s = all_settings()
    if source == "app" and s["accepting_orders"] != "1":
        raise ApiError(403, "We are not taking phone orders right now. Please order at the counter.")
    eta = eta_minutes(s) if source == "app" else 0
    uid = g.user["id"] if g.get("user") else None
    d = db()
    order_id = None
    for _ in range(8):  # retry if two orders grab the same token at the same moment
        code = secrets.token_urlsafe(6)
        try:
            tok = d.execute("SELECT COALESCE(MAX(tok), 0) + 1 FROM orders WHERE day = ?", (today(),)).fetchone()[0]
            order_id = d.execute(
                "INSERT INTO orders (day, tok, code, source, customer_name, phone, note, eta_min, created_at, created_by, customer_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (today(), tok, code, source, name, phone, note, eta, now_ms(), uid, customer_id)).lastrowid
            break
        except sqlite3.IntegrityError:
            d.rollback()
    if order_id is None:
        raise ApiError(503, "Could not create a token. Please try again.")
    for m, q in lines:
        d.execute("INSERT INTO order_items (order_id, item_id, name, price, qty) VALUES (?,?,?,?,?)",
                  (order_id, m["id"], m["name"], m["price"], q))
    add_log(order_id, "Order placed at " + ("phone (QR link)" if source == "app" else "counter"))
    if pay_method:
        # TODO(real UPI): for phone orders create a payment-gateway order first and only insert this
        # row after the gateway's webhook confirms the money arrived.
        add_payment(order_id, pay_method, total, ref="demo" if source == "app" else "")
        add_log(order_id, f"{pay_method} payment Rs {total} recorded" + (" (demo mode)" if source == "app" else ""))
    else:
        add_log(order_id, "Payment pending")
    d.commit()
    if customer_id:
        database.link_customer_hotel(customer_id)
    return order_id


def upi_link(vpa, payee, amount, tok):
    return (f"upi://pay?pa={quote(vpa)}&pn={quote(payee)}&am={amount:.2f}&cu=INR"
            f"&tn={quote('Token ' + str(tok))}")


def public_view(o, s):
    """What a customer may see about their own order (no phone number, no staff names)."""
    view = {k: o[k] for k in ("tok", "code", "status", "eta_min", "created_at", "paid", "due", "cancel_reason")}
    view["total"] = o["payable"]
    view["items"] = [{"name": i["name"], "qty": i["qty"], "price": i["price"]} for i in o["items"]]
    view["restaurant"] = s["restaurant_name"]
    view["ready_by"] = o["created_at"] + o["eta_min"] * 60000 if o["eta_min"] else None
    view["rating"] = o["rating"]
    view["mine"] = bool(g.get("customer") and o["customer_id"] == g.customer["id"])
    view["upi"] = None
    if o["due"] > 0 and s["payment_mode"] == "upi_manual" and s["upi_vpa"]:
        view["upi"] = {"vpa": s["upi_vpa"], "name": s["upi_name"] or s["restaurant_name"], "amount": o["due"],
                       "link": upi_link(s["upi_vpa"], s["upi_name"] or s["restaurant_name"], o["due"], o["tok"])}
    return view


def get_or_404(order_id, full_log=False):
    o = full_order(order_id, full_log)
    if o is None:
        raise ApiError(404, "Order not found")
    return o


# ------------------------------------------------------------------ staff API
@bp.get("/api/orders")
@require("cashier", "kitchen")
def list_orders():
    """scope=active (default): today's orders not handed over. scope=history: any date, with search."""
    d = db()
    if request.args.get("scope", "active") == "active":
        day = today()
        ids = d.execute("SELECT id FROM orders WHERE day = ? AND status IN ('placed','preparing','ready') ORDER BY id", (day,))
    else:
        day = parse_date(request.args.get("date"), today())
        q = clean_text(request.args.get("q"), 40)
        status = request.args.get("status", "")
        sql, args = "SELECT id FROM orders WHERE day = ?", [day]
        if status in ALL_STATUSES:
            sql += " AND status = ?"
            args.append(status)
        if q:
            digits = re.sub(r"\D", "", q)
            if q.isdigit() and len(q) <= 4:          # short numbers are token numbers
                sql += " AND tok = ?"
                args.append(int(q))
            elif digits and len(digits) >= 5:         # longer numbers are phone numbers
                sql += " AND phone LIKE ?"
                args.append(f"%{digits}%")
            else:
                sql += " AND customer_name LIKE ?"
                args.append(f"%{q}%")
        ids = d.execute(sql + " ORDER BY id DESC LIMIT 300", args)
    orders = [full_order(r["id"]) for r in ids.fetchall()]
    return jsonify(orders=orders, summary=day_summary(day), day=day)


@bp.get("/api/orders/<int:order_id>")
@require("cashier", "kitchen")
def get_order(order_id):
    return jsonify(get_or_404(order_id, full_log=True))


@bp.post("/api/orders")
@require("cashier")
def staff_create():
    """Body: {items:[{id,q}], payMethod?: 'UPI'|'Cash', name?, phone?, note?}"""
    data = request.get_json(silent=True) or {}
    pay = data.get("payMethod")
    if pay not in (None, "UPI", "Cash"):
        raise ApiError(400, "Invalid payment method")
    name, phone, customer_id = clean_text(data.get("name"), 40, "Name"), clean_phone(data.get("phone")), None
    if data.get("customer_id") is not None:       # the cashier picked a registered customer
        customer_id = as_int(data.get("customer_id"), "Customer", 1, 10 ** 9)
        c = database.pdb().execute("SELECT name, phone FROM customers WHERE id = ?", (customer_id,)).fetchone()
        if c is None:
            raise ApiError(400, "That customer no longer exists")
        name, phone = c["name"], c["phone"]
    oid = create_order("counter", data.get("items"), pay, name, phone, clean_text(data.get("note"), 200, "Note"), customer_id)
    return jsonify(full_order(oid)), 201


@bp.post("/api/orders/<int:order_id>/pay")
@require("cashier")
def pay(order_id):
    """Record a payment for whatever is still due. Body: {method}"""
    o = get_or_404(order_id)
    method = (request.get_json(silent=True) or {}).get("method")
    if method not in ("UPI", "Cash"):
        raise ApiError(400, "Invalid payment method")
    if o["due"] <= 0:
        raise ApiError(409, "Nothing is due on this order")
    add_payment(order_id, method, o["due"])
    add_log(order_id, f"{method} payment Rs {o['due']} recorded")
    db().commit()
    return jsonify(full_order(order_id))


@bp.post("/api/orders/<int:order_id>/refund")
@require("cashier")
def refund(order_id):
    """Mark the refund as given (after items were removed from, or the whole of, a paid order)."""
    o = get_or_404(order_id)
    if o["refund"] <= 0:
        raise ApiError(409, "No refund is owed")
    last = next((p for p in reversed(o["payments"]) if p["amount"] > 0), None)
    add_payment(order_id, last["method"] if last else "Cash", -o["refund"])
    add_log(order_id, f"Refunded Rs {o['refund']}")
    db().commit()
    return jsonify(full_order(order_id))


@bp.post("/api/orders/<int:order_id>/status")
@require("kitchen", "cashier")
def set_status(order_id):
    """placed -> preparing -> ready -> collected. Cooking and handing over need the bill to be paid."""
    o = get_or_404(order_id)
    to = (request.get_json(silent=True) or {}).get("status")
    if NEXT_STATUS.get(o["status"]) != to:
        raise ApiError(409, f"Cannot move from {o['status']} to {to}")
    if to == "collected" and g.user["role"] not in ("owner", "cashier"):
        raise ApiError(403, "Only the cashier hands over orders")
    if to in ("preparing", "collected") and o["due"] > 0:
        raise ApiError(409, "Collect payment first", due=o["due"])
    db().execute(f"UPDATE orders SET status = ?, {STATUS_COLUMN[to]} = ? WHERE id = ?", (to, now_ms(), order_id))
    add_log(order_id, f"Status: {to}")
    db().commit()
    return jsonify(full_order(order_id))


@bp.post("/api/orders/<int:order_id>/items")
@require("cashier")
def change_item(order_id):
    """Change one item's quantity by +1 or -1. Body: {item_id, delta, approved?}

    Locked once the order is ready. Removing after cooking has started needs approved=true.
    An order always keeps at least one item (cancel the order instead).
    """
    o = get_or_404(order_id)
    data = request.get_json(silent=True) or {}
    delta, approved = data.get("delta"), data.get("approved")
    if delta not in (1, -1) or isinstance(delta, bool):
        raise ApiError(400, "delta must be 1 or -1")
    item_id = as_int(data.get("item_id"), "Item", 1, 10 ** 9)
    if o["status"] not in ("placed", "preparing"):
        raise ApiError(409, "Locked: this order can no longer be edited. Create a new order.")
    d = db()
    line = next((i for i in o["items"] if i["id"] == item_id), None)
    if delta == 1:
        m = d.execute("SELECT m.id, m.name, m.price, m.available FROM menu m JOIN categories c ON c.id = m.category_id "
                      "WHERE m.id = ? AND m.active = 1 AND c.active = 1", (item_id,)).fetchone()
        if m is None:
            raise ApiError(400, "Unknown item")
        if not m["available"]:
            raise ApiError(409, f"{m['name']} is sold out")
        if line and line["qty"] >= 50:
            raise ApiError(400, "Quantity is too high")
        if line:
            d.execute("UPDATE order_items SET qty = qty + 1 WHERE order_id = ? AND item_id = ?", (order_id, item_id))
        else:  # the price is frozen at the moment the item is added
            d.execute("INSERT INTO order_items (order_id, item_id, name, price, qty) VALUES (?,?,?,?,?)",
                      (order_id, item_id, m["name"], m["price"], 1))
        add_log(order_id, f"Added 1 x {m['name']}")
    else:
        if line is None:
            raise ApiError(400, "That item is not in the order")
        if len(o["items"]) == 1 and line["qty"] == 1:
            raise ApiError(400, "An order needs at least one item. Cancel the order instead.")
        if o["status"] == "preparing" and not approved:
            raise ApiError(409, "Cooking has started. Staff approval needed.", needsApproval=True)
        if line["qty"] == 1:
            d.execute("DELETE FROM order_items WHERE order_id = ? AND item_id = ?", (order_id, item_id))
        else:
            d.execute("UPDATE order_items SET qty = qty - 1 WHERE order_id = ? AND item_id = ?", (order_id, item_id))
        add_log(order_id, f"Removed 1 x {line['name']}" + (" (approved)" if o["status"] == "preparing" else ""))
    d.commit()
    return jsonify(full_order(order_id))


@bp.post("/api/orders/<int:order_id>/cancel")
@require("cashier")
def cancel(order_id):
    o = get_or_404(order_id)
    if o["status"] in ("collected", "cancelled"):
        raise ApiError(409, f"This order is already {o['status']}")
    reason = clean_text((request.get_json(silent=True) or {}).get("reason"), 80, "Reason")
    db().execute("UPDATE orders SET status = 'cancelled', cancelled_at = ?, cancel_reason = ? WHERE id = ?",
                 (now_ms(), reason, order_id))
    add_log(order_id, "Order cancelled" + (f": {reason}" if reason else ""))
    db().commit()
    return jsonify(full_order(order_id))


@bp.post("/api/orders/<int:order_id>/notified")
@require("cashier", "kitchen")
def notified(order_id):
    """Logged when staff open the WhatsApp message to the customer."""
    get_or_404(order_id)
    add_log(order_id, "WhatsApp message opened for customer")
    db().commit()
    return jsonify(ok=True)


# ------------------------------------------------------------------ public (customer) API
@bp.get("/api/public/menu")
def public_menu():
    d, s = db(), all_settings()
    cats = []
    for c in d.execute("SELECT id, name FROM categories WHERE active = 1 ORDER BY sort_order, id").fetchall():
        items = [dict(r) for r in d.execute(
            "SELECT id, name, price, diet, available, description, image_v FROM menu WHERE category_id = ? AND active = 1 "
            "ORDER BY sort_order, id", (c["id"],))]
        if items:
            cats.append({"id": c["id"], "name": c["name"], "items": items})
    return jsonify(restaurant=s["restaurant_name"], accepting=s["accepting_orders"] == "1",
                   payment_mode=s["payment_mode"], eta_min=eta_minutes(s), categories=cats)


@bp.get("/img/<int:item_id>")
def item_image(item_id):
    """Menu photo. The address contains ?v=<image_v>, so browsers can keep it for a year."""
    row = db().execute("SELECT image, image_type FROM menu WHERE id = ? AND active = 1 AND image IS NOT NULL",
                       (item_id,)).fetchone()
    if row is None:
        raise ApiError(404, "No photo")
    resp = Response(row["image"], mimetype=row["image_type"])
    resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return resp


@bp.post("/api/public/orders")
def public_create():
    """Body: {items:[{id,q}], note?}. The customer must be signed in; name and phone come from the account."""
    c = g.get("customer")
    if c is None:
        raise ApiError(401, "Please sign up or log in to order")
    rate_limit("order:" + str(c["id"]), 12, 600,
               "Too many orders in a short time. Please wait a few minutes or order at the counter.")
    data = request.get_json(silent=True) or {}
    s = all_settings()
    pay = "UPI" if s["payment_mode"] == "demo" else None   # upi_manual: staff confirm money received
    oid = create_order("app", data.get("items"), pay, c["name"], c["phone"],
                       clean_text(data.get("note"), 200, "Note"), c["id"])
    return jsonify(public_view(full_order(oid), s)), 201


@bp.get("/api/public/orders/<code>")
def public_track(code):
    row = db().execute("SELECT id FROM orders WHERE code = ?", (code[:20],)).fetchone()
    if row is None:
        raise ApiError(404, "Order not found")
    return jsonify(public_view(full_order(row["id"]), all_settings()))


@bp.get("/api/public/board")
def public_board():
    """Tokens only. An unpaid order is not shown as 'preparing'."""
    s = all_settings()
    ready, preparing = [], []
    ids = db().execute("SELECT id FROM orders WHERE day = ? AND status IN ('placed','preparing','ready') ORDER BY id",
                       (today(),)).fetchall()
    for r in ids:
        o = full_order(r["id"])
        if o["status"] == "ready":
            ready.append(o["tok"])
        elif o["due"] == 0:
            preparing.append(o["tok"])
    return jsonify(restaurant=s["restaurant_name"], ready=ready, preparing=preparing)
