"""Menu, staff, settings, reports and backup.

Owner only, except: viewing the menu and marking items sold out (any staff).
"""
import base64
import binascii
import csv
import io
import os
import re
import sqlite3
import tempfile
from collections import defaultdict

from flask import Blueprint, Response, current_app, g, jsonify, request, send_file
from werkzeug.security import generate_password_hash

import db as database
from auth import ROLES, require, validate_password, validate_username
from db import all_settings, db, pdb, restaurant_path, set_setting
from util import ApiError, as_int, clean_text, ist, now_ms, parse_date, today

bp = Blueprint("admin", __name__)


# ------------------------------------------------------------------ menu (read: any staff)
def menu_tree():
    d = db()
    tree = []
    for c in d.execute("SELECT id, name, sort_order FROM categories WHERE active = 1 ORDER BY sort_order, id").fetchall():
        items = [dict(r) for r in d.execute(
            "SELECT id, category_id, name, price, diet, available, sort_order, description, image_v FROM menu "
            "WHERE category_id = ? AND active = 1 ORDER BY sort_order, id", (c["id"],))]
        tree.append({**dict(c), "items": items})
    return tree


@bp.get("/api/menu")
@require("cashier", "kitchen")
def get_menu():
    return jsonify(categories=menu_tree())


@bp.post("/api/menu/<int:item_id>/available")
@require("cashier", "kitchen")
def set_available(item_id):
    """Mark an item sold out / back on. Customers see it immediately."""
    available = 1 if (request.get_json(silent=True) or {}).get("available") else 0
    cur = db().execute("UPDATE menu SET available = ? WHERE id = ? AND active = 1", (available, item_id))
    if cur.rowcount == 0:
        raise ApiError(404, "Item not found")
    db().commit()
    return jsonify(ok=True, available=available)


# ------------------------------------------------------------------ menu (write: owner)
def _move(table, row_id, direction, where_sql, where_args):
    """Swap sort position with the neighbour above (-1) or below (+1)."""
    d = db()
    rows = d.execute(f"SELECT id FROM {table} WHERE active = 1 AND {where_sql} ORDER BY sort_order, id", where_args).fetchall()
    ids = [r["id"] for r in rows]
    if row_id not in ids:
        raise ApiError(404, "Not found")
    i, j = ids.index(row_id), ids.index(row_id) + direction
    if 0 <= j < len(ids):
        ids[i], ids[j] = ids[j], ids[i]
    for pos, rid in enumerate(ids):
        d.execute(f"UPDATE {table} SET sort_order = ? WHERE id = ?", (pos, rid))
    d.commit()


@bp.post("/api/admin/categories")
@require()
def add_category():
    name = clean_text((request.get_json(silent=True) or {}).get("name"), 40, "Category name", required=True)
    d = db()
    pos = d.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 FROM categories WHERE active = 1").fetchone()[0]
    cid = d.execute("INSERT INTO categories (name, sort_order) VALUES (?, ?)", (name, pos)).lastrowid
    d.commit()
    return jsonify(id=cid), 201


@bp.put("/api/admin/categories/<int:cid>")
@require()
def rename_category(cid):
    name = clean_text((request.get_json(silent=True) or {}).get("name"), 40, "Category name", required=True)
    if db().execute("UPDATE categories SET name = ? WHERE id = ? AND active = 1", (name, cid)).rowcount == 0:
        raise ApiError(404, "Category not found")
    db().commit()
    return jsonify(ok=True)


@bp.post("/api/admin/categories/<int:cid>/move")
@require()
def move_category(cid):
    direction = -1 if (request.get_json(silent=True) or {}).get("dir") == -1 else 1
    _move("categories", cid, direction, "1 = 1", [])
    return jsonify(ok=True)


@bp.delete("/api/admin/categories/<int:cid>")
@require()
def delete_category(cid):
    d = db()
    if d.execute("SELECT 1 FROM menu WHERE category_id = ? AND active = 1", (cid,)).fetchone():
        raise ApiError(409, "Delete or move this category's items first")
    d.execute("UPDATE categories SET active = 0 WHERE id = ?", (cid,))
    d.commit()
    return jsonify(ok=True)


IMAGE_TYPES = {"image/jpeg": (b"\xff\xd8\xff",), "image/png": (b"\x89PNG\r\n\x1a\n",), "image/webp": (b"RIFF",)}
MAX_IMAGE_BYTES = 200 * 1024


def parse_image(value):
    """Turn a data URL from the browser into (bytes, mime). Checks type, size and the real file signature."""
    match = re.fullmatch(r"data:(image/(?:jpeg|png|webp));base64,([A-Za-z0-9+/=\s]+)", str(value or ""))
    if not match:
        raise ApiError(400, "Photo must be a JPG, PNG or WebP image")
    mime = match.group(1)
    try:
        raw = base64.b64decode(match.group(2), validate=False)
    except (binascii.Error, ValueError):
        raise ApiError(400, "Photo could not be read")
    if len(raw) > MAX_IMAGE_BYTES:
        raise ApiError(400, "Photo is too large (the app shrinks photos automatically; try a different one)")
    if not raw.startswith(IMAGE_TYPES[mime]) or (mime == "image/webp" and raw[8:12] != b"WEBP"):
        raise ApiError(400, "Photo file is not a real image")
    return raw, mime


def _item_fields(data, partial=False):
    out = {}
    if not partial or "name" in data:
        out["name"] = clean_text(data.get("name"), 60, "Item name", required=True)
    if not partial or "price" in data:
        out["price"] = as_int(data.get("price"), "Price", 0, 100000)
    if not partial or "diet" in data:
        if data.get("diet", "") not in ("", "veg", "nonveg"):
            raise ApiError(400, "Diet must be veg, nonveg or empty")
        out["diet"] = data.get("diet", "")
    if not partial or "description" in data:
        out["description"] = clean_text(data.get("description"), 160, "Description")
    if "category_id" in data:
        cid = as_int(data.get("category_id"), "Category", 1, 10 ** 9)
        if not db().execute("SELECT 1 FROM categories WHERE id = ? AND active = 1", (cid,)).fetchone():
            raise ApiError(400, "Category not found")
        out["category_id"] = cid
    if "image" in data:                      # absent = keep the photo, empty/null = remove it
        if data["image"]:
            raw, mime = parse_image(data["image"])
            out.update(image=raw, image_type=mime, image_v=now_ms())
        else:
            out.update(image=None, image_type="", image_v=0)
    return out


@bp.post("/api/admin/items")
@require()
def add_item():
    data = request.get_json(silent=True) or {}
    f = _item_fields(data)
    if "category_id" not in f:
        raise ApiError(400, "Choose a category")
    d = db()
    pos = d.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 FROM menu WHERE category_id = ? AND active = 1",
                    (f["category_id"],)).fetchone()[0]
    iid = d.execute(
        "INSERT INTO menu (category_id, name, price, diet, sort_order, description, image, image_type, image_v) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (f["category_id"], f["name"], f["price"], f["diet"], pos, f["description"],
         f.get("image"), f.get("image_type", ""), f.get("image_v", 0))).lastrowid
    d.commit()
    return jsonify(id=iid), 201


@bp.put("/api/admin/items/<int:item_id>")
@require()
def edit_item(item_id):
    """Editing a price never changes bills that already exist (prices are copied into each order)."""
    f = _item_fields(request.get_json(silent=True) or {}, partial=True)
    if not f:
        raise ApiError(400, "Nothing to change")
    sets = ", ".join(f"{k} = ?" for k in f)
    if db().execute(f"UPDATE menu SET {sets} WHERE id = ? AND active = 1", [*f.values(), item_id]).rowcount == 0:
        raise ApiError(404, "Item not found")
    db().commit()
    return jsonify(ok=True)


@bp.post("/api/admin/items/<int:item_id>/move")
@require()
def move_item(item_id):
    row = db().execute("SELECT category_id FROM menu WHERE id = ? AND active = 1", (item_id,)).fetchone()
    if row is None:
        raise ApiError(404, "Item not found")
    direction = -1 if (request.get_json(silent=True) or {}).get("dir") == -1 else 1
    _move("menu", item_id, direction, "category_id = ?", [row["category_id"]])
    return jsonify(ok=True)


@bp.delete("/api/admin/items/<int:item_id>")
@require()
def delete_item(item_id):
    # Soft delete: old orders keep pointing at the row, so history and reports stay correct.
    if db().execute("UPDATE menu SET active = 0 WHERE id = ?", (item_id,)).rowcount == 0:
        raise ApiError(404, "Item not found")
    db().commit()
    return jsonify(ok=True)


# ------------------------------------------------------------------ staff accounts
@bp.get("/api/admin/users")
@require()
def list_users():
    rows = db().execute("SELECT id, username, role, active, created_at FROM users ORDER BY id")
    return jsonify(users=[dict(r) for r in rows], me=g.user["id"])


@bp.post("/api/admin/users")
@require()
def add_user():
    data = request.get_json(silent=True) or {}
    username = validate_username(data.get("username"))
    validate_password(data.get("password"))
    if data.get("role") not in ROLES:
        raise ApiError(400, "Role must be owner, cashier or kitchen")
    try:
        uid = db().execute("INSERT INTO users (username, password_hash, role, created_at) VALUES (?,?,?,?)",
                           (username, generate_password_hash(data["password"]), data["role"], now_ms())).lastrowid
    except sqlite3.IntegrityError:
        raise ApiError(409, "That username is already taken")
    db().commit()
    return jsonify(id=uid), 201


@bp.put("/api/admin/users/<int:uid>")
@require()
def edit_user(uid):
    data = request.get_json(silent=True) or {}
    d = db()
    user = d.execute("SELECT id, role, active FROM users WHERE id = ?", (uid,)).fetchone()
    if user is None:
        raise ApiError(404, "User not found")
    role = data.get("role", user["role"])
    active = 1 if data.get("active", user["active"]) else 0
    if role not in ROLES:
        raise ApiError(400, "Invalid role")
    # Never lock the restaurant out: keep at least one active owner, and do not demote yourself.
    owners_left = d.execute("SELECT COUNT(*) FROM users WHERE role = 'owner' AND active = 1 AND id != ?", (uid,)).fetchone()[0]
    if (role != "owner" or not active) and user["role"] == "owner" and user["active"] and owners_left == 0:
        raise ApiError(409, "There must be at least one active owner")
    if uid == g.user["id"] and (role != user["role"] or not active):
        raise ApiError(409, "You cannot change your own role or deactivate yourself")
    d.execute("UPDATE users SET role = ?, active = ? WHERE id = ?", (role, active, uid))
    if data.get("password"):
        validate_password(data["password"])
        d.execute("UPDATE users SET password_hash = ? WHERE id = ?", (generate_password_hash(data["password"]), uid))
    d.commit()
    return jsonify(ok=True)


# ------------------------------------------------------------------ settings
SETTING_RULES = {
    "restaurant_name": lambda v: clean_text(v, 60, "Restaurant name", required=True),
    "accepting_orders": lambda v: "1" if v in (True, 1, "1", "true") else "0",
    "payment_mode": lambda v: v if v in ("demo", "counter", "upi_manual", "both") else _bad("Choose a payment option"),
    "upi_vpa": lambda v: _vpa(v),
    "upi_name": lambda v: clean_text(v, 40, "UPI name"),
    "eta_base": lambda v: str(as_int(v, "Base time", 0, 120)),
    "eta_per_order": lambda v: str(as_int(v, "Extra time per order", 0, 30)),
    "whatsapp_template": lambda v: clean_text(v, 300, "WhatsApp message", required=True),
    "receipt_address": lambda v: clean_text(v, 160, "Address"),
    "receipt_phone": lambda v: clean_text(v, 30, "Phone"),
    "receipt_footer": lambda v: clean_text(v, 120, "Footer"),
}


def _bad(message):
    raise ApiError(400, message)


def _vpa(value):
    v = str(value or "").strip()
    if v and not re.fullmatch(r"[A-Za-z0-9._\-]{2,}@[A-Za-z0-9]{2,}", v):
        raise ApiError(400, "UPI ID looks wrong. It should look like name@bank")
    return v


@bp.get("/api/admin/settings")
@require()
def get_settings():
    return jsonify(settings=all_settings())


@bp.put("/api/admin/settings")
@require()
def put_settings():
    data = request.get_json(silent=True) or {}
    clean = {}
    for key, value in data.items():
        if key not in SETTING_RULES:
            raise ApiError(400, f"Unknown setting: {key}")
        clean[key] = SETTING_RULES[key](value)
    merged = {**all_settings(), **clean}
    if merged["payment_mode"] in ("upi_manual", "both") and not merged["upi_vpa"]:
        raise ApiError(400, "Enter your UPI ID before turning on UPI payments")
    for key, value in clean.items():
        set_setting(key, value)
    db().commit()
    if "restaurant_name" in clean:      # the platform list shows the same name
        pdb().execute("UPDATE restaurants SET name = ? WHERE id = ?", (clean["restaurant_name"], g.rest["id"]))
        pdb().commit()
    return jsonify(settings=all_settings())


# ------------------------------------------------------------------ reports
def _range():
    start = parse_date(request.args.get("from"), today())
    end = parse_date(request.args.get("to"), start)
    if end < start:
        raise ApiError(400, "The end date is before the start date")
    return start, end


@bp.get("/api/admin/reports")
@require()
def report():
    start, end = _range()
    d = db()
    orders = d.execute("SELECT id, day, source, status, created_at, ready_at, collected_at FROM orders "
                       "WHERE day BETWEEN ? AND ?", (start, end)).fetchall()
    totals = {r["order_id"]: r["t"] for r in d.execute(
        "SELECT oi.order_id, SUM(oi.price * oi.qty) AS t FROM order_items oi JOIN orders o ON o.id = oi.order_id "
        "WHERE o.day BETWEEN ? AND ? GROUP BY oi.order_id", (start, end))}

    live = [o for o in orders if o["status"] != "cancelled"]
    sales = sum(totals.get(o["id"], 0) for o in live)
    by_day, by_hour, by_source = defaultdict(lambda: [0, 0]), [0] * 24, {"counter": 0, "app": 0}
    prep, wait = [], []
    for o in live:
        by_day[o["day"]][0] += 1
        by_day[o["day"]][1] += totals.get(o["id"], 0)
        by_hour[ist(o["created_at"]).hour] += 1
        by_source[o["source"]] += 1
        if o["ready_at"]:
            prep.append((o["ready_at"] - o["created_at"]) / 60000)
        if o["collected_at"] and o["ready_at"]:
            wait.append((o["collected_at"] - o["ready_at"]) / 60000)

    money = {"UPI": 0, "Cash": 0}
    for r in d.execute("SELECT p.method AS m, SUM(p.amount) AS s FROM payments p JOIN orders o ON o.id = p.order_id "
                       "WHERE o.day BETWEEN ? AND ? GROUP BY p.method", (start, end)):
        money[r["m"]] = r["s"]
    top = [dict(r) for r in d.execute(
        "SELECT oi.name, SUM(oi.qty) AS qty, SUM(oi.qty * oi.price) AS revenue FROM order_items oi "
        "JOIN orders o ON o.id = oi.order_id WHERE o.day BETWEEN ? AND ? AND o.status != 'cancelled' "
        "GROUP BY oi.name ORDER BY qty DESC, revenue DESC LIMIT 10", (start, end))]
    outstanding = 0
    for o in live:
        paid = d.execute("SELECT COALESCE(SUM(amount), 0) FROM payments WHERE order_id = ?", (o["id"],)).fetchone()[0]
        outstanding += max(0, totals.get(o["id"], 0) - paid)

    return jsonify(
        start=start, end=end, orders=len(live), cancelled=len(orders) - len(live), sales=sales,
        avg_ticket=round(sales / len(live)) if live else 0, upi=money["UPI"], cash=money["Cash"],
        unpaid=outstanding, avg_prep_min=round(sum(prep) / len(prep), 1) if prep else None,
        avg_pickup_wait_min=round(sum(wait) / len(wait), 1) if wait else None,
        by_source=by_source, by_hour=by_hour, top_items=top,
        by_day=[{"day": k, "orders": v[0], "sales": v[1]} for k, v in sorted(by_day.items())])


@bp.get("/api/admin/reports/export.csv")
@require()
def export_csv():
    start, end = _range()
    d = db()
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Date", "Token", "Time", "Source", "Status", "Customer", "Phone", "Items", "Total (Rs)",
                "Paid (Rs)", "Payment methods"])
    for o in d.execute("SELECT * FROM orders WHERE day BETWEEN ? AND ? ORDER BY id", (start, end)).fetchall():
        items = d.execute("SELECT name, qty, price FROM order_items WHERE order_id = ?", (o["id"],)).fetchall()
        pays = d.execute("SELECT method, amount FROM payments WHERE order_id = ?", (o["id"],)).fetchall()
        methods = sorted({p["method"] for p in pays if p["amount"] > 0})
        w.writerow([o["day"], o["tok"], ist(o["created_at"]).strftime("%H:%M"), o["source"], o["status"],
                    o["customer_name"], o["phone"], "; ".join(f"{i['qty']} x {i['name']}" for i in items),
                    sum(i["qty"] * i["price"] for i in items), sum(p["amount"] for p in pays), "+".join(methods)])
    name = f"orders_{start}_to_{end}.csv"
    return Response("﻿" + out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ------------------------------------------------------------------ backup
@bp.get("/api/admin/backup")
@require()
def backup():
    """Download a consistent copy of the whole database. Keep one somewhere safe every week."""
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        src = sqlite3.connect(restaurant_path(g.rest["slug"]))
        dst = sqlite3.connect(tmp)
        src.backup(dst)
        src.close()
        dst.close()
        with open(tmp, "rb") as fh:
            data = io.BytesIO(fh.read())
    finally:
        os.remove(tmp)
    return send_file(data, mimetype="application/octet-stream", as_attachment=True,
                     download_name=f"flotoken-{g.rest['slug']}-backup-{today()}.db")
