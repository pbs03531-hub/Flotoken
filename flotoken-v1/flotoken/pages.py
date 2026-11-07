"""HTML pages. All data comes from the JSON API, so pages are thin."""
import json

from flask import Blueprint, Response, abort, current_app, g, redirect, render_template, send_from_directory, jsonify

from auth import HOME, require
from db import all_settings, db
from orders import full_order

bp = Blueprint("pages", __name__)


@bp.get("/")
def home():
    """Installed app opens here: staff go to their own screen, customers to the menu."""
    return redirect(HOME[g.user["role"]] if g.get("user") else "/order")


@bp.get("/manifest.webmanifest")
def manifest():
    """Per-restaurant app manifest, so customers install the app under the restaurant's own name."""
    name = all_settings()["restaurant_name"]
    data = {
        "id": "/", "name": name, "short_name": name[:12], "start_url": "/", "scope": "/",
        "description": f"Order from {name} for pickup, skip the queue and watch your token live.",
        "display": "standalone", "background_color": "#F3F5F2", "theme_color": "#C2410C", "lang": "en-IN",
        "categories": ["food", "business"],
        "icons": [
            {"src": "/static/img/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": "/static/img/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": "/static/img/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
        "shortcuts": [
            {"name": "Order food", "url": "/order"},
            {"name": "Counter", "url": "/counter"},
            {"name": "Parcel screen", "url": "/parcel"},
        ],
    }
    resp = Response(json.dumps(data), mimetype="application/manifest+json")
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@bp.get("/sw.js")
def service_worker():
    resp = send_from_directory(current_app.static_folder, "sw.js", mimetype="application/javascript")
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["Service-Worker-Allowed"] = "/"
    return resp


@bp.get("/offline")
def offline():
    return render_template("offline.html")


@bp.get("/healthz")
def healthz():
    """Used by the hosting service to check the app is alive."""
    db().execute("SELECT 1").fetchone()
    return Response("ok", mimetype="text/plain")


@bp.get("/order")
def order_page():
    return render_template("order.html", track_code="")


@bp.get("/t/<code>")
def track_page(code):
    return render_template("order.html", track_code=code[:20])


@bp.get("/board")
def board_page():
    return render_template("board.html")


@bp.get("/counter")
@require("cashier", page=True)
def counter_page():
    return render_template("counter.html")


@bp.get("/parcel")
@require("cashier", "kitchen", page=True)
def parcel_page():
    return render_template("parcel.html")


@bp.get("/history")
@require("cashier", page=True)
def history_page():
    return render_template("history.html")


@bp.get("/admin")
@require(page=True)          # no roles listed = owner only; others are redirected to their own screen
def admin_page():
    return render_template("admin.html")


@bp.get("/receipt/<int:order_id>")
@require("cashier", page=True)
def receipt_page(order_id):
    o = full_order(order_id)
    if o is None:
        abort(404)
    return render_template("receipt.html", o=o)


@bp.get("/pricing")
def pricing_page():
    return render_template("pricing.html")


@bp.get("/api/public/pricing")
def pricing_data():
    """Flotoken plans for restaurants. GST is shown as a plain formula only."""
    from customers import PLAN, gst_breakdown
    monthly_x12 = PLAN["monthly"] * 12
    return jsonify(plan=PLAN, yearly_per_month=round(PLAN["yearly"] / 12, 2), yearly_saving=monthly_x12 - PLAN["yearly"],
                   gst={"monthly": gst_breakdown(PLAN["monthly"]), "yearly": gst_breakdown(PLAN["yearly"])})

