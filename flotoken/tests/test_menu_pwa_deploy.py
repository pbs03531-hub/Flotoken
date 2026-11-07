"""Tests for menu photos, the installable app, and hosting behaviour."""
import base64
import io
import os
import sqlite3
import sys
import tempfile
import unittest

import db as database  # noqa: E402
from PIL import Image  # noqa: E402
from tests.harness import add_hotel, anon, hotel_login, make_app, platform_client, util  # noqa: E402
from app import create_app  # noqa: E402


def data_url(mime="image/jpeg", fmt="JPEG", size=(80, 60)):
    buf = io.BytesIO()
    Image.new("RGB", size, (200, 80, 20)).save(buf, fmt)
    return f"data:{mime};base64," + base64.b64encode(buf.getvalue()).decode(), buf.getvalue()


class Env:
    """Set environment variables for a block, then restore them."""
    def __init__(self, **kw):
        self.kw, self.old = kw, {}

    def __enter__(self):
        for k, v in self.kw.items():
            self.old[k] = os.environ.get(k)
            os.environ[k] = v

    def __exit__(self, *a):
        for k, v in self.old.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


def new_app(**cfg):
    return make_app(**cfg)


def setup_owner(app, name="Betty Military Hotel", slug="betty"):
    """Platform admin adds the restaurant (once per app); returns the owner's client."""
    p = platform_client(app) if app.test_client().get("/api/platform/me").get_json()["needs_setup"] else None
    if p is None:
        p = app.test_client(); p.post("/api/platform/login", json={"username": "flo", "password": "flopass1"})
    add_hotel(p, name=name, slug=slug)
    return hotel_login(app, slug)


class TestMenuPhotos(unittest.TestCase):
    def setUp(self):
        self.app = new_app()
        self.owner = setup_owner(self.app)
        self.owner.post("/api/admin/users", json={"username": "cash", "password": "pass123", "role": "cashier"})
        self.cash = anon(self.app)
        self.cash.post("/api/auth/login", json={"username": "cash", "password": "pass123"})
        self.anon = anon(self.app)
        self.cat = self.owner.get("/api/menu").get_json()["categories"][0]["id"]

    def add(self, **extra):
        body = {"category_id": self.cat, "name": "Ghee Rice", "price": 90, "diet": "veg", **extra}
        return self.owner.post("/api/admin/items", json=body)

    def item(self, iid):
        return next(i for c in self.owner.get("/api/menu").get_json()["categories"] for i in c["items"] if i["id"] == iid)

    def test_add_item_with_photo_and_description_then_serve(self):
        url, raw = data_url()
        r = self.add(image=url, description="  Served   with raita ")
        self.assertEqual(r.status_code, 201, r.get_json())
        iid = r.get_json()["id"]
        it = self.item(iid)
        self.assertEqual((it["description"], it["image_v"] > 0), ("Served with raita", True))
        img = self.anon.get(f"/img/{iid}?v={it['image_v']}")                    # customers need no login
        self.assertEqual((img.status_code, img.mimetype, img.data), (200, "image/jpeg", raw))
        self.assertIn("immutable", img.headers["Cache-Control"])
        pub = next(i for c in self.anon.get("/api/public/menu").get_json()["categories"] for i in c["items"] if i["id"] == iid)
        self.assertEqual((pub["description"], pub["image_v"] == it["image_v"]), ("Served with raita", True))
        self.assertNotIn("image", pub)                                           # the bytes never travel in the menu JSON

    def test_edit_keeps_photo_unless_told_otherwise(self):
        url, _ = data_url()
        iid = self.add(image=url).get_json()["id"]
        v1 = self.item(iid)["image_v"]
        self.assertEqual(self.owner.put(f"/api/admin/items/{iid}", json={"price": 95}).status_code, 200)
        self.assertEqual((self.item(iid)["price"], self.item(iid)["image_v"]), (95, v1))     # photo untouched
        url2, raw2 = data_url(size=(40, 40))
        self.owner.put(f"/api/admin/items/{iid}", json={"image": url2})
        self.assertNotEqual(self.item(iid)["image_v"], v1)                       # new version = new cache address
        self.assertEqual(self.anon.get(f"/img/{iid}").data, raw2)
        self.owner.put(f"/api/admin/items/{iid}", json={"image": ""})
        self.assertEqual((self.item(iid)["image_v"], self.anon.get(f"/img/{iid}").status_code), (0, 404))

    def test_bad_photos_rejected(self):
        gif, _ = data_url("image/gif", "GIF")
        png_label_jpeg_bytes = "data:image/png;base64," + data_url()[0].split(",", 1)[1]
        huge = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff" + os.urandom(210 * 1024)).decode()
        for bad in (gif, png_label_jpeg_bytes, huge, "data:image/jpeg;base64,!!!", "not an image", "data:text/html;base64,PGI+"):
            r = self.add(image=bad)
            self.assertEqual(r.status_code, 400, bad[:40])
        self.assertEqual(self.add(description="x" * 161).status_code, 400)
        self.assertEqual(self.add(image=data_url("image/png", "PNG")[0]).status_code, 201)       # PNG is fine
        self.assertEqual(self.add(image=data_url("image/webp", "WEBP")[0]).status_code, 201)     # so is WebP

    def test_only_owner_edits_menu_but_cashier_can_mark_sold_out(self):
        iid = self.add().get_json()["id"]
        self.assertEqual(self.cash.put(f"/api/admin/items/{iid}", json={"price": 1}).status_code, 403)
        self.assertEqual(self.anon.put(f"/api/admin/items/{iid}", json={"price": 1}).status_code, 401)
        self.assertEqual(self.cash.post(f"/api/menu/{iid}/available", json={"available": False}).status_code, 200)
        self.assertEqual(self.item(iid)["available"], 0)

    def test_price_change_never_alters_existing_bill_and_new_orders_use_new_price(self):
        iid = self.add().get_json()["id"]
        old = self.cash.post("/api/orders", json={"items": [{"id": iid, "q": 2}], "payMethod": "Cash"}).get_json()
        self.owner.put(f"/api/admin/items/{iid}", json={"price": 120})
        self.assertEqual(self.cash.get(f"/api/orders/{old['id']}").get_json()["total"], 180)
        new = self.cash.post("/api/orders", json={"items": [{"id": iid, "q": 1}]}).get_json()
        self.assertEqual(new["total"], 120)


class TestMigration(unittest.TestCase):
    def test_old_database_gains_new_columns_and_keeps_data(self):
        path = os.path.join(tempfile.mkdtemp(), "old.db")
        con = sqlite3.connect(path)
        con.executescript("""
            CREATE TABLE categories (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, sort_order INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE menu (id INTEGER PRIMARY KEY AUTOINCREMENT, category_id INTEGER NOT NULL, name TEXT NOT NULL,
              price INTEGER NOT NULL, diet TEXT NOT NULL DEFAULT '', available INTEGER NOT NULL DEFAULT 1,
              active INTEGER NOT NULL DEFAULT 1, sort_order INTEGER NOT NULL DEFAULT 0);
            INSERT INTO categories (name) VALUES ('Biryani');
            INSERT INTO menu (category_id, name, price) VALUES (1, 'Mutton Biryani', 280);""")
        con.commit(); con.close()
        database.init_db(path)
        database.init_db(path)                                           # running twice must be harmless
        con = sqlite3.connect(path)
        cols = {r[1] for r in con.execute("PRAGMA table_info(menu)")}
        self.assertTrue({"description", "image", "image_type", "image_v"} <= cols)
        self.assertEqual(con.execute("SELECT name, price, description, image_v FROM menu").fetchone(), ("Mutton Biryani", 280, "", 0))


class TestInstallableApp(unittest.TestCase):
    def setUp(self):
        self.app = new_app()
        self.owner = setup_owner(self.app, "Betty Military Hotel")
        self.anon = anon(self.app)
        self.raw = self.app.test_client()

    def test_support_files_are_public(self):
        for path in ("/healthz", "/sw.js", "/manifest.webmanifest", "/offline", "/static/img/icon-192.png", "/r/betty/sw.js", "/r/betty/manifest.webmanifest"):
            self.assertEqual(self.raw.get(path).status_code, 200, path)

    def test_start_screen_has_both_choices_and_works_with_no_setup(self):
        fresh = make_app().test_client()
        for path in ("/", "/staff", "/customer", "/pricing", "/healthz"):          # reachable even before the first hotel exists
            self.assertEqual(fresh.get(path).status_code, 200, path)
        page = self.raw.get("/").get_data(as_text=True)
        self.assertIn('href="/staff"', page); self.assertIn("Restaurant login", page)
        self.assertIn('href="/customer"', page); self.assertIn("customer", page.lower())

    def test_each_restaurant_manifest_is_named_and_scoped(self):
        m = self.raw.get("/r/betty/manifest.webmanifest").get_json()
        self.assertEqual((m["name"], m["short_name"], m["display"], m["start_url"], m["scope"]), ("Betty Military Hotel", "Betty Milita", "standalone", "/r/betty/", "/r/betty/"))
        sizes = {(i["sizes"], i["purpose"]) for i in m["icons"]}
        self.assertTrue({("192x192", "any"), ("512x512", "any"), ("512x512", "maskable")} <= sizes)
        for icon in m["icons"]:
            self.assertEqual(self.raw.get(icon["src"]).status_code, 200, icon["src"])
        self.assertIn('rel="manifest" href="/r/betty/manifest.webmanifest"', self.raw.get("/r/betty/order").get_data(as_text=True))
        top = self.raw.get("/manifest.webmanifest").get_json()
        self.assertEqual((top["name"], top["start_url"]), ("Flotoken", "/"))

    def test_service_worker_headers(self):
        for path in ("/sw.js", "/r/betty/sw.js"):
            r = self.raw.get(path)
            self.assertEqual((r.mimetype, r.headers["Cache-Control"]), ("application/javascript", "no-cache"), path)
        self.assertIn("You are offline", self.raw.get("/offline").get_data(as_text=True))

    def test_home_sends_each_person_to_their_own_screen(self):
        self.owner.post("/api/admin/users", json={"username": "cook", "password": "pass123", "role": "kitchen"})
        cook = anon(self.app); cook.post("/api/auth/login", json={"username": "cook", "password": "pass123"})
        self.assertEqual(self.anon.get("/").headers["Location"], "/r/betty/order")
        self.assertEqual(cook.get("/").headers["Location"], "/r/betty/parcel")
        self.assertEqual(self.owner.get("/").headers["Location"], "/r/betty/admin")


class TestHosting(unittest.TestCase):
    def test_rate_limit_is_per_visitor_behind_a_proxy(self):
        with Env(TRUST_PROXY="1"):
            app = new_app(); setup_owner(app); c = anon(app)
            bad = lambda ip: c.post("/api/auth/login", json={"username": "boss", "password": "x"}, headers={"X-Forwarded-For": ip}).status_code
            self.assertEqual([bad("1.1.1.1") for _ in range(9)][-2:], [401, 429])     # visitor A locked out...
            self.assertEqual(bad("2.2.2.2"), 401)                                      # ...visitor B is not

    def test_without_proxy_trust_forged_headers_are_ignored(self):
        app = new_app(); setup_owner(app); c = anon(app)
        codes = [c.post("/api/auth/login", json={"username": "boss", "password": "x"}, headers={"X-Forwarded-For": f"9.9.9.{i}"}).status_code for i in range(10)]
        self.assertEqual(codes[-1], 429)                                               # cannot dodge the limit by spoofing

    def test_render_mode_uses_secure_cookies_and_hsts(self):
        with Env(RENDER="true"):
            app = new_app(); setup_owner(app)
            r = anon(app).post("/api/auth/login", json={"username": "boss", "password": "secret1"}, headers={"X-Forwarded-Proto": "https"})
            self.assertEqual(r.status_code, 200)
            cookie = r.headers.get("Set-Cookie", "")
            self.assertIn("Secure", cookie); self.assertIn("HttpOnly", cookie); self.assertIn("SameSite=Lax", cookie)
            self.assertIn("max-age", r.headers.get("Strict-Transport-Security", ""))

    def test_platform_and_first_hotel_are_created_from_environment(self):
        data = tempfile.mkdtemp()
        env = dict(PLATFORM_USERNAME="Flo.Owner", PLATFORM_PASSWORD="platpass1", OWNER_USERNAME="Owner.One", OWNER_PASSWORD="firstpass",
                   RESTAURANT_NAME="Demo Hotel", SAMPLE_MENU="1")
        with Env(**env):
            util._hits.clear()
            app = create_app({"DATA_DIR": data, "TESTING": True})
            c = app.test_client()
            listed = c.get("/api/public/restaurants").get_json()["restaurants"]
            self.assertEqual([r["name"] for r in listed], ["Demo Hotel"])
            slug = listed[0]["slug"]
            h = anon(app, slug)
            self.assertEqual(h.post("/api/auth/login", json={"username": "owner.one", "password": "firstpass"}).status_code, 200)
            self.assertGreater(len(h.get("/api/public/menu").get_json()["categories"]), 0)
            self.assertEqual(c.post("/api/platform/login", json={"username": "Flo.Owner", "password": "platpass1"}).status_code, 200)
        with Env(**{**env, "OWNER_PASSWORD": "changedpw", "PLATFORM_PASSWORD": "newplat22"}):      # restart: hotel untouched, platform password re-synced
            util._hits.clear()
            app2 = create_app({"DATA_DIR": data, "TESTING": True})
            self.assertEqual(anon(app2, slug).post("/api/auth/login", json={"username": "owner.one", "password": "firstpass"}).status_code, 200)
            c2 = app2.test_client()
            self.assertEqual(c2.post("/api/platform/login", json={"username": "Flo.Owner", "password": "newplat22"}).status_code, 200)
            self.assertEqual(len(c2.get("/api/public/restaurants").get_json()["restaurants"]), 1)

    def test_bad_environment_owner_is_ignored(self):
        with Env(OWNER_USERNAME="bad name!", OWNER_PASSWORD="x", RESTAURANT_NAME="Bad"):
            app = new_app()
            self.assertEqual(app.test_client().get("/api/public/restaurants").get_json()["restaurants"], [])
            self.assertEqual(app.test_client().get("/").status_code, 200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
