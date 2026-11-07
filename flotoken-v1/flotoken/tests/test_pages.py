"""Page tests: every screen renders for the right role and is blocked for the wrong one."""
import os, sys, tempfile, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DB_FILE"] = os.path.join(tempfile.mkdtemp(), "import.db")
import util  # noqa: E402
from app import create_app  # noqa: E402


class TestPages(unittest.TestCase):
    def setUp(self):
        util._hits.clear()
        self.app = create_app({"DB_FILE": os.path.join(tempfile.mkdtemp(), "p.db"), "TESTING": True})
        self.anon = self.app.test_client()

    def test_first_run_goes_to_setup_then_login(self):
        r = self.anon.get("/login"); self.assertEqual((r.status_code, r.headers["Location"]), (302, "/setup"))
        self.assertEqual(self.anon.get("/setup").status_code, 200)
        self.anon.post("/api/auth/setup", json={"restaurant_name": "<b>Hotel & Co</b>", "username": "boss", "password": "secret1", "sample_menu": True})
        c = self.app.test_client()
        self.assertEqual(c.get("/setup").status_code, 302)
        r = c.get("/login"); self.assertEqual(r.status_code, 200)
        self.assertIn("&lt;b&gt;Hotel &amp; Co&lt;/b&gt;", r.get_data(as_text=True))   # restaurant name is escaped

    def test_pages_by_role(self):
        o = self.app.test_client()
        o.post("/api/auth/setup", json={"restaurant_name": "Test Hotel", "username": "boss", "password": "secret1", "sample_menu": True})
        o.post("/api/admin/users", json={"username": "cash", "password": "pass123", "role": "cashier"})
        o.post("/api/admin/users", json={"username": "cook", "password": "pass123", "role": "kitchen"})
        cash, cook = self.app.test_client(), self.app.test_client()
        cash.post("/api/auth/login", json={"username": "cash", "password": "pass123"})
        cook.post("/api/auth/login", json={"username": "cook", "password": "pass123"})
        order = cash.post("/api/orders", json={"items": [{"id": 1, "q": 1}], "payMethod": "Cash"}).get_json()

        for path in ("/order", "/t/abc", "/board", "/login"):
            self.assertIn(self.anon.get(path).status_code, (200, 302), path)
        for path in ("/counter", "/parcel", "/history", "/admin", f"/receipt/{order['id']}"):
            r = self.anon.get(path); self.assertEqual(r.status_code, 302, path); self.assertIn("/login", r.headers["Location"])
        for path in ("/", "/order", "/counter", "/parcel", "/history", "/admin", "/board", f"/receipt/{order['id']}"):
            r = o.get(path, follow_redirects=True); self.assertEqual(r.status_code, 200, path)
            self.assertIn("Test Hotel", r.get_data(as_text=True))
        for path in ("/counter", "/parcel", "/history", f"/receipt/{order['id']}"):
            self.assertEqual(cash.get(path).status_code, 200, path)
        self.assertEqual(cash.get("/admin").headers["Location"], "/counter")
        self.assertEqual(cook.get("/parcel").status_code, 200)
        self.assertEqual(cook.get("/counter").headers["Location"], "/parcel")
        self.assertEqual(cook.get("/history").headers["Location"], "/parcel")
        self.assertEqual(self.anon.get("/receipt/999").status_code, 302)
        self.assertEqual(o.get("/receipt/999").status_code, 404)
        self.assertEqual(self.anon.get("/nope").status_code, 404)
        self.assertEqual(self.anon.get("/api/nope").get_json()["error"], "Not found")
        html = cash.get(f"/receipt/{order['id']}").get_data(as_text=True)
        self.assertIn("TOKEN 1", html); self.assertIn("280", html)
        self.assertIn("/static/js/counter.js", cash.get("/counter").get_data(as_text=True))
        for asset in ("/static/app.css", "/static/js/core.js", "/static/js/order.js", "/static/js/counter.js", "/static/js/parcel.js",
                      "/static/js/board.js", "/static/js/history.js", "/static/js/admin.js", "/manifest.webmanifest", "/static/img/icon.svg"):
            self.assertEqual(self.anon.get(asset).status_code, 200, asset)

if __name__ == "__main__":
    unittest.main(verbosity=2)
