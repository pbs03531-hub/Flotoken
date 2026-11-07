"""Customer payment choices: pay at the counter, pay by UPI, or let the customer choose."""
import unittest

from tests.harness import add_hotel, anon, hotel_login, make_app, platform_client


class TestPaymentChoices(unittest.TestCase):
    def setUp(self):
        self.app = make_app()
        self.p = platform_client(self.app)
        add_hotel(self.p, name="Betty", slug="betty")
        self.owner = hotel_login(self.app, "betty")
        for u, r in (("cash", "cashier"), ("cook", "kitchen")):
            self.owner.post("/api/admin/users", json={"username": u, "password": "pass123", "role": r})
        self.cash, self.cook = anon(self.app), anon(self.app)
        self.cash.post("/api/auth/login", json={"username": "cash", "password": "pass123"})
        self.cook.post("/api/auth/login", json={"username": "cook", "password": "pass123"})
        self.c = anon(self.app)
        self.c.post("/api/customer/signup", json={"name": "Asha", "phone": "98450 12345", "password": "asha123", "consent": True})
        self.item = self.c.get("/api/public/menu").get_json()["categories"][0]["items"][0]["id"]

    def mode(self, mode, **kw):
        r = self.owner.put("/api/admin/settings", json={"payment_mode": mode, **kw})
        self.assertEqual(r.status_code, 200, r.get_json())

    def order(self, **kw):
        return self.c.post("/api/public/orders", json={"items": [{"id": self.item, "q": 1}], **kw})

    def test_new_restaurants_start_in_pay_at_counter_mode(self):
        add_hotel(self.p, name="New", slug="newhotel", owner="own", payment_mode="counter")
        self.assertEqual(anon(self.app, "newhotel").get("/api/public/menu").get_json()["payment_mode"], "counter")
        self.assertEqual(self.p.post("/api/platform/restaurants", json={"name": "Z", "slug": "zzz", "owner_username": "zed", "owner_password": "pass123", "payment_mode": "upi_manual"}).status_code, 400)
        r = self.p.post("/api/platform/restaurants", json={"name": "Z", "slug": "zzz", "owner_username": "zed", "owner_password": "pass123"})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(anon(self.app, "zzz").get("/api/public/menu").get_json()["payment_mode"], "counter")

    def test_pay_at_counter_full_flow(self):
        self.mode("counter")
        o = self.order().get_json()
        self.assertEqual((o["pay_pref"], o["paid"] , o["upi"]), ("counter", 0, None))
        self.assertGreater(o["due"], 0)
        oid = next(x["id"] for x in self.cash.get("/api/orders").get_json()["orders"] if x["code"] == o["code"])
        self.assertEqual(self.cook.post(f"/api/orders/{oid}/status", json={"status": "preparing"}).status_code, 409)   # unpaid: cannot cook
        self.assertEqual(self.cash.post(f"/api/orders/{oid}/pay", json={"method": "Cash"}).status_code, 200)            # customer paid the cashier
        self.assertEqual(self.cook.post(f"/api/orders/{oid}/status", json={"status": "preparing"}).status_code, 200)
        self.assertEqual(self.c.get(f"/api/public/orders/{o['code']}").get_json()["due"], 0)

    def test_upi_only_mode_shows_the_upi_details(self):
        self.assertEqual(self.owner.put("/api/admin/settings", json={"payment_mode": "upi_manual"}).status_code, 400)   # needs a UPI ID
        self.mode("upi_manual", upi_vpa="betty@upi", upi_name="Betty Hotel")
        o = self.order().get_json()
        self.assertEqual(o["pay_pref"], "upi")
        self.assertEqual(o["upi"]["vpa"], "betty@upi")
        self.assertTrue(o["upi"]["link"].startswith("upi://pay?pa=betty%40upi"))

    def test_customer_chooses_when_both_are_on(self):
        self.assertEqual(self.owner.put("/api/admin/settings", json={"payment_mode": "both"}).status_code, 400)
        self.mode("both", upi_vpa="betty@upi")
        self.assertEqual(self.order().status_code, 400)                          # must choose
        self.assertEqual(self.order(method="cheque").status_code, 400)
        a = self.order(method="upi").get_json(); b = self.order(method="counter").get_json()
        self.assertEqual((a["pay_pref"], bool(a["upi"])), ("upi", True))
        self.assertEqual((b["pay_pref"], b["upi"]), ("counter", None))           # no UPI card for someone paying at the counter

    def test_order_page_loads_the_sign_up_code(self):
        # a logged-out customer tapping View order opens the sign-up window; without account.js nothing happened
        html = self.c.get("/order").get_data(as_text=True)
        self.assertIn("/static/js/account.js", html)
        self.assertLess(html.index("js/account.js"), html.index("js/order.js"))
        self.assertIn("/static/js/account.js", anon(self.app).get("/t/abc").get_data(as_text=True))

    def test_checkout_page_text_matches_the_mode(self):
        js = self.c.get("/static/js/order.js").get_data(as_text=True)
        for text in ("Pay at the counter", "Pay by UPI now", "method: form.method"):
            self.assertIn(text, js)
        self.assertEqual(self.c.get("/api/public/menu").get_json()["payment_mode"], "demo")
        self.mode("both", upi_vpa="betty@upi")
        self.assertEqual(self.c.get("/api/public/menu").get_json()["payment_mode"], "both")


if __name__ == "__main__":
    unittest.main(verbosity=2)
