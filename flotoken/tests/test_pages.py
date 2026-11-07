"""Page tests: every screen renders for the right role and is blocked for the wrong one."""
import unittest

from tests.harness import RC, add_hotel, anon, hotel_login, make_app, platform_client


class TestPages(unittest.TestCase):
    def setUp(self):
        self.app = make_app()
        self.raw = self.app.test_client()

    def test_first_run_asks_for_the_owner_login_once(self):
        self.assertEqual(self.raw.get("/").status_code, 200)                         # the start screen always opens
        self.assertEqual(self.raw.get("/platform").status_code, 200)
        r = self.raw.get("/r/betty/order"); self.assertEqual((r.status_code, r.headers["Location"]), (302, "/platform"))
        self.assertTrue(self.raw.get("/api/platform/me").get_json()["needs_setup"])
        p = platform_client(self.app)
        self.assertEqual(self.app.test_client().get("/").status_code, 200)
        self.assertFalse(p.get("/api/platform/me").get_json()["needs_setup"])
        self.assertEqual(self.app.test_client().post("/api/platform/setup", json={"username": "x1", "password": "secret1"}).status_code, 409)

    def test_screens_by_role_and_restaurant_name_is_escaped(self):
        p = platform_client(self.app)
        add_hotel(p, name="<b>Hotel & Co</b>", slug="hotel-co")
        o = hotel_login(self.app, "hotel-co")
        r = anon(self.app, "hotel-co").get("/login"); self.assertEqual(r.status_code, 200)
        self.assertIn("&lt;b&gt;Hotel &amp; Co&lt;/b&gt;", r.get_data(as_text=True))
        o.post("/api/admin/users", json={"username": "cash", "password": "pass123", "role": "cashier"})
        o.post("/api/admin/users", json={"username": "cook", "password": "pass123", "role": "kitchen"})
        a = anon(self.app, "hotel-co"); cash, cook = anon(self.app, "hotel-co"), anon(self.app, "hotel-co")
        cash.post("/api/auth/login", json={"username": "cash", "password": "pass123"})
        cook.post("/api/auth/login", json={"username": "cook", "password": "pass123"})
        mid = o.get("/api/menu").get_json()["categories"][0]["items"][0]["id"]
        order = cash.post("/api/orders", json={"items": [{"id": mid, "q": 1}], "payMethod": "Cash"}).get_json()

        for path in ("/order", "/t/abc", "/board", "/login"):
            self.assertIn(a.get(path).status_code, (200, 302), path)
        for path in ("/counter", "/parcel", "/history", "/admin", f"/receipt/{order['id']}"):
            r = a.get(path); self.assertEqual(r.status_code, 302, path); self.assertIn("/r/hotel-co/login", r.headers["Location"])
        for path in ("/", "/order", "/counter", "/parcel", "/history", "/admin", "/board", f"/receipt/{order['id']}"):
            r = o.get(path, follow_redirects=True); self.assertEqual(r.status_code, 200, path)
        for path in ("/counter", "/parcel", "/history", f"/receipt/{order['id']}"):
            self.assertEqual(cash.get(path).status_code, 200, path)
        self.assertEqual(cash.get("/admin").headers["Location"], "/r/hotel-co/counter")
        self.assertEqual(cook.get("/parcel").status_code, 200)
        self.assertEqual(cook.get("/counter").headers["Location"], "/r/hotel-co/parcel")
        self.assertEqual(a.get("/receipt/999").status_code, 302)
        self.assertEqual(o.get("/receipt/999").status_code, 404)
        self.assertEqual(self.raw.get("/nope").status_code, 404)
        self.assertEqual(self.raw.get("/r/nohotel/order").status_code, 404)
        self.assertEqual(self.raw.get("/r/hotel-co/api/nope").get_json()["error"], "Not found")
        html = cash.get(f"/receipt/{order['id']}").get_data(as_text=True)
        self.assertIn("TOKEN 1", html)
        self.assertIn("/static/js/counter.js", cash.get("/counter").get_data(as_text=True))
        for asset in ("app.css", "js/core.js", "js/account.js", "js/customer.js", "js/platform.js", "js/order.js", "js/counter.js", "js/parcel.js",
                      "js/board.js", "js/history.js", "js/admin.js", "js/pricing.js", "img/icon.svg", "sw.js"):
            self.assertEqual(self.raw.get("/static/" + asset).status_code, 200, asset)

    def test_platform_level_pages(self):
        platform_client(self.app)
        for path in ("/", "/staff", "/customer", "/platform", "/pricing", "/offline"):
            self.assertEqual(self.raw.get(path).status_code, 200, path)
        self.assertIn("Restaurant login", self.raw.get("/").get_data(as_text=True))
        page = self.raw.get("/staff?r=bad<script>").get_data(as_text=True)
        self.assertNotIn("<script>alert", page); self.assertIn('const PREFILL = "badscript"', page)


if __name__ == "__main__":
    unittest.main(verbosity=2)
