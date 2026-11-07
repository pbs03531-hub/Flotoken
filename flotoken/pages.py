"""Restaurant pages, all under /r/<restaurant-code>/. Data comes from the JSON API, so pages are thin."""
import json

from flask import Blueprint, Response, abort, g, redirect, render_template, url_for

from auth import home_url, require
from db import all_settings
from orders import full_order
from portal import serve_sw

bp = Blueprint("pages", __name__)


@bp.get("/")
def home():
    """The restaurant's own address: staff go to their screen, customers to the menu."""
    return redirect(home_url(g.user["role"]) if g.get("user") else url_for("pages.order_page"))


@bp.get("/manifest.webmanifest")
def manifest():
    """Per-restaurant app manifest, so customers install the app under the restaurant's own name."""
    name = all_settings()["restaurant_name"]
    base = f"/r/{g.slug}"
    data = {
        "id": base + "/", "name": name, "short_name": name[:12], "start_url": base + "/", "scope": base + "/",
        "description": f"Order from {name} for pickup, skip the queue and watch your token live.",
        "display": "standalone", "background_color": "#F3F5F2", "theme_color": "#C2410C", "lang": "en-IN",
        "categories": ["food", "business"],
        "icons": [
            {"src": "/static/img/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": "/static/img/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": "/static/img/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
        "shortcuts": [
            {"name": "Order food", "url": base + "/order"},
            {"name": "Counter", "url": base + "/counter"},
            {"name": "Parcel screen", "url": base + "/parcel"},
        ],
    }
    resp = Response(json.dumps(data), mimetype="application/manifest+json")
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@bp.get("/sw.js")
def service_worker():
    return serve_sw()


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
