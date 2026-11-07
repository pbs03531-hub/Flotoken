"""Tests for customer accounts, ratings, the customer list, the business dashboard and pricing."""
import os
import sqlite3
import sys
import tempfile
import unittest

import db as database  # noqa: E402
from customers import norm_phone  # noqa: E402
from pricing import PLAN, gst_breakdown  # noqa: E402
from tests.harness import add_hotel, anon, hotel_login, make_app, platform_client, util  # noqa: E402
from util import ApiError  # noqa: E402


def signup(client, name="Asha", phone="98450 12345", password="asha123", consent=True):
    return client.post("/api/customer/signup", json={"name": name, "phone": phone, "password": password, "consent": consent})


class Base(unittest.TestCase):
    def setUp(self):
        self.app = make_app()
        self.platform = platform_client(self.app)
        add_hotel(self.platform, name="Betty", slug="betty")
        self.owner = hotel_login(self.app, "betty")
        for name, role in (("cash", "cashier"), ("cook", "kitchen")):
            self.owner.post("/api/admin/users", json={"username": name, "password": "pass123", "role": role})
        self.cashier, self.kitchen, self.anon = anon(self.app), anon(self.app), anon(self.app)
        self.cashier.post("/api/auth/login", json={"username": "cash", "password": "pass123"})
        self.kitchen.post("/api/auth/login", json={"username": "cook", "password": "pass123"})
        self.item = self.anon.get("/api/public/menu").get_json()["categories"][0]["items"][0]
        self.asha = anon(self.app)
        self.assertEqual(signup(self.asha).status_code, 201)

    def order(self, client=None, qty=1):
        r = (client or self.asha).post("/api/public/orders", json={"items": [{"id": self.item["id"], "q": qty}]})
        self.assertEqual(r.status_code, 201, r.get_json())
        return r.get_json()

    def collect(self, code):
        oid = next(o["id"] for o in self.cashier.get("/api/orders").get_json()["orders"] if o["code"] == code)
        for who, to in ((self.kitchen, "preparing"), (self.kitchen, "ready"), (self.cashier, "collected")):
            self.assertEqual(who.post(f"/api/orders/{oid}/status", json={"status": to}).status_code, 200)
        return oid


class TestAccounts(Base):
    def test_phone_formats(self):
        for raw in ("9845012345", "98450 12345", "+91 98450-12345", "919845012345", "09845012345"):
            self.assertEqual(norm_phone(raw), "9845012345")
        for bad in ("12345", "5845012345", "", "abcdefghij", "98450123456789"):
            with self.assertRaises(ApiError):
                norm_phone(bad)

    def test_signup_rules(self):
        c = anon(self.app)
        self.assertEqual(signup(c, consent=False, phone="9000000001").status_code, 400)      # must agree
        self.assertEqual(signup(c, password="123", phone="9000000001").status_code, 400)
        self.assertEqual(signup(c, name="", phone="9000000001").status_code, 400)
        self.assertEqual(signup(c, phone="123").status_code, 400)
        dup = signup(c, phone="+91 98450 12345")                                              # same number, other format
        self.assertEqual(dup.status_code, 409)
        self.assertEqual(signup(c, name="Ravi", phone="9000000001").status_code, 201)

    def test_login_logout_me(self):
        c = anon(self.app)
        self.assertIsNone(c.get("/api/customer/me").get_json()["customer"])
        self.assertEqual(c.post("/api/customer/login", json={"phone": "9845012345", "password": "wrong1"}).status_code, 401)
        self.assertEqual(c.post("/api/customer/login", json={"phone": "9999999999", "password": "asha123"}).status_code, 401)
        r = c.post("/api/customer/login", json={"phone": "+91 98450 12345", "password": "asha123"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(c.get("/api/customer/me").get_json()["customer"]["name"], "Asha")
        c.post("/api/customer/logout", json={})
        self.assertIsNone(c.get("/api/customer/me").get_json()["customer"])

    def test_login_is_rate_limited_per_number(self):
        c = anon(self.app)
        codes = [c.post("/api/customer/login", json={"phone": "9845012345", "password": "bad" + str(i)}).status_code for i in range(8)]
        self.assertEqual(codes[:6], [401] * 6)
        self.assertEqual(codes[6], 429)

    def test_staff_and_customer_logins_are_separate(self):
        self.assertEqual(self.asha.get("/api/orders").status_code, 401)          # a customer is not staff
        self.assertEqual(self.asha.get("/api/customers").status_code, 401)
        self.assertEqual(self.cashier.post("/api/public/orders", json={"items": [{"id": self.item["id"], "q": 1}]}).status_code, 401)

    def test_profile_password_delete(self):
        self.assertEqual(self.asha.put("/api/customer/me", json={"name": "Asha K"}).status_code, 200)
        self.assertEqual(self.asha.post("/api/customer/password", json={"current": "nope12", "new": "newpass1"}).status_code, 400)
        self.assertEqual(self.asha.post("/api/customer/password", json={"current": "asha123", "new": "123"}).status_code, 400)
        self.assertEqual(self.asha.post("/api/customer/password", json={"current": "asha123", "new": "newpass1"}).status_code, 200)
        fresh = anon(self.app)
        self.assertEqual(fresh.post("/api/customer/login", json={"phone": "9845012345", "password": "asha123"}).status_code, 401)
        self.assertEqual(fresh.post("/api/customer/login", json={"phone": "9845012345", "password": "newpass1"}).status_code, 200)

    def test_delete_account_keeps_bills_but_removes_identity(self):
        v = self.order()
        self.assertEqual(self.asha.delete("/api/customer/me", json={"password": "wrong"}).status_code, 400)
        self.assertEqual(self.asha.delete("/api/customer/me", json={"password": "asha123"}).status_code, 200)
        self.assertEqual(self.asha.get("/api/customer/orders").status_code, 401)
        o = self.cashier.get("/api/orders").get_json()["orders"][0]
        self.assertEqual((o["customer_name"], o["phone"], o["total"], o["paid"]), ("Deleted customer", "", v["total"], v["total"]))
        self.assertEqual(self.owner.get("/api/customers").get_json()["total"], 0)
        self.assertEqual(signup(anon(self.app)).status_code, 201)         # the number can be used again


class TestOrdersAndRatings(Base):
    def test_order_uses_account_identity_and_ignores_forged_details(self):
        r = self.asha.post("/api/public/orders", json={"items": [{"id": self.item["id"], "q": 1}], "name": "Hacker", "phone": "9111111111"})
        self.assertEqual(r.status_code, 201)
        o = self.cashier.get("/api/orders").get_json()["orders"][0]
        self.assertEqual((o["customer_name"], o["phone"], o["source"]), ("Asha", "9845012345", "app"))

    def test_my_orders_are_private_and_reorderable(self):
        v = self.order(qty=2)
        ravi = anon(self.app)
        signup(ravi, name="Ravi", phone="9000000001")
        mine = self.asha.get("/api/customer/orders").get_json()["orders"]
        self.assertEqual([(o["code"], o["items"][0]["id"], o["items"][0]["qty"]) for o in mine], [(v["code"], self.item["id"], 2)])
        self.assertEqual(ravi.get("/api/customer/orders").get_json()["orders"], [])
        self.assertTrue(self.asha.get(f"/api/public/orders/{v['code']}").get_json()["mine"])
        self.assertFalse(ravi.get(f"/api/public/orders/{v['code']}").get_json()["mine"])
        self.assertFalse(self.anon.get(f"/api/public/orders/{v['code']}").get_json()["mine"])

    def test_rating_rules(self):
        v = self.order()
        rate = lambda c, n=5, note="": c.post(f"/api/public/orders/{v['code']}/rating", json={"rating": n, "note": note})
        self.assertEqual(rate(self.asha).status_code, 409)                         # not collected yet
        self.collect(v["code"])
        ravi = anon(self.app); signup(ravi, name="Ravi", phone="9000000001")
        self.assertEqual(rate(self.anon).status_code, 401)
        self.assertEqual(rate(ravi).status_code, 404)                              # someone else's order
        for bad in (0, 6, "x", None):
            self.assertEqual(rate(self.asha, bad).status_code, 400)
        self.assertEqual(rate(self.asha, 4, "Tasty").status_code, 200)
        self.assertEqual(rate(self.asha, 1).status_code, 409)                      # only once
        self.assertEqual(self.asha.get(f"/api/public/orders/{v['code']}").get_json()["rating"], 4)
        self.assertEqual(self.asha.get("/api/customer/orders").get_json()["orders"][0]["rating"], 4)

    def test_counter_order_can_attach_a_registered_customer(self):
        found = self.cashier.get("/api/customers?q=9845012345").get_json()["customers"]       # exact number finds the global account
        self.assertEqual((len(found), found[0]["name"]), (1, "Asha"))
        self.assertEqual(self.cashier.get("/api/customers?q=asha").get_json()["customers"], [])   # a name alone does not
        cid = found[0]["id"]
        r = self.cashier.post("/api/orders", json={"items": [{"id": self.item["id"], "q": 1}], "payMethod": "Cash", "customer_id": cid, "name": "ignored"})
        self.assertEqual(r.status_code, 201)
        o = r.get_json()
        self.assertEqual((o["customer_name"], o["phone"], o["customer_id"]), ("Asha", "9845012345", cid))
        self.assertEqual(len(self.asha.get("/api/customer/orders").get_json()["orders"]), 1)
        bad = self.cashier.post("/api/orders", json={"items": [{"id": self.item["id"], "q": 1}], "customer_id": 9999})
        self.assertEqual(bad.status_code, 400)

    def test_typing_someones_number_does_not_reveal_their_history(self):
        # phone numbers are not verified yet, so an old counter order with the same number must stay hidden
        self.cashier.post("/api/orders", json={"items": [{"id": self.item["id"], "q": 1}], "payMethod": "Cash", "phone": "9000000002", "name": "Meena"})
        stranger = anon(self.app)
        signup(stranger, name="Not Meena", phone="9000000002")
        self.assertEqual(stranger.get("/api/customer/orders").get_json()["orders"], [])


class TestRestaurantSide(Base):
    def test_permissions(self):
        for c, code in ((self.anon, 401), (self.kitchen, 403)):
            self.assertEqual(c.get("/api/customers").status_code, code)
            self.assertEqual(c.get("/api/customers/1").status_code, code)
        self.assertEqual(self.cashier.get("/api/customers").status_code, 200)
        self.assertEqual(self.cashier.get("/api/customers.csv").status_code, 403)       # export is owner only
        self.assertEqual(self.cashier.get("/api/admin/business").status_code, 403)
        self.assertEqual(self.owner.get("/api/customers.csv").status_code, 200)
        self.assertEqual(self.owner.get("/api/admin/business").status_code, 200)

    def test_search_detail_and_csv(self):
        ravi = anon(self.app); signup(ravi, name="Ravi Kumar", phone="9000000001")
        self.order(); self.order(qty=2); self.order(ravi)
        by_name = self.cashier.get("/api/customers?q=ash").get_json()
        self.assertEqual([c["name"] for c in by_name["customers"]], ["Asha"])
        self.assertEqual((by_name["customers"][0]["orders"], by_name["total"]), (2, 2))
        self.assertEqual([c["name"] for c in self.cashier.get("/api/customers?q=00000").get_json()["customers"]], ["Ravi Kumar"])
        self.assertEqual(self.cashier.get("/api/customers?q=%2B91%2098450").get_json()["customers"][0]["name"], "Asha")
        self.assertEqual(self.cashier.get("/api/customers?sort=orders").get_json()["customers"][0]["name"], "Asha")
        cid = by_name["customers"][0]["id"]
        d = self.cashier.get(f"/api/customers/{cid}").get_json()
        self.assertEqual((d["customer"]["orders"], len(d["orders"]), d["favourites"][0]["qty"]), (2, 2, 3))
        self.assertEqual(self.cashier.get("/api/customers/999").status_code, 404)
        csv = self.owner.get("/api/customers.csv").get_data(as_text=True)
        self.assertIn("Asha,9845012345", csv)
        self.assertEqual(csv.splitlines()[0].split(",")[0], "Name")

    def test_staff_cannot_reset_a_customer_password_only_flotoken_can(self):
        cid = self.cashier.get("/api/customers?q=9845012345").get_json()["customers"][0]["id"]
        self.assertEqual(self.cashier.post(f"/api/customers/{cid}/reset-password", json={}).status_code, 404)
        self.assertEqual(self.platform.post(f"/api/platform/customers/{cid}/reset-password", json={}).status_code, 200)
        temp = self.platform.post(f"/api/platform/customers/{cid}/reset-password", json={}).get_json()["temporary_password"]
        self.assertEqual(len(temp), 6)
        c = anon(self.app)
        self.assertEqual(c.post("/api/customer/login", json={"phone": "9845012345", "password": "asha123"}).status_code, 401)
        self.assertEqual(c.post("/api/customer/login", json={"phone": "9845012345", "password": temp}).status_code, 200)
        self.assertEqual(self.platform.post("/api/platform/customers/9999/reset-password", json={}).status_code, 404)
        self.assertEqual(anon(self.app).post(f"/api/platform/customers/{cid}/reset-password", json={}).status_code, 401)

    def test_business_dashboard_numbers(self):
        empty = self.owner.get("/api/admin/business").get_json()
        self.assertEqual((empty["customers"]["total"], empty["customers"]["repeat_percent"], empty["ratings"]["avg"]), (0, 0, None))     # nobody has ordered here yet
        ravi = anon(self.app); signup(ravi, name="Ravi", phone="9000000001")
        a1, a2, r1 = self.order(), self.order(), self.order(ravi)
        self.cashier.post("/api/orders", json={"items": [{"id": self.item["id"], "q": 1}], "payMethod": "Cash"})     # walk-in, no account
        self.collect(a1["code"])
        self.asha.post(f"/api/public/orders/{a1['code']}/rating", json={"rating": 5})
        d = self.owner.get("/api/admin/business").get_json()
        self.assertEqual((d["customers"]["total"], d["customers"]["new_7d"], d["customers"]["active_7d"]), (2, 2, 2))
        self.assertEqual((d["customers"]["repeat"], d["customers"]["repeat_percent"]), (1, 50))
        self.assertEqual((d["orders"]["total"], d["orders"]["linked"], d["orders"]["app"], d["orders"]["counter"], d["orders"]["linked_percent"]), (4, 3, 3, 1, 75))
        self.assertEqual((d["ratings"]["avg"], d["ratings"]["count"], d["ratings"]["distribution"]["5"]), (5.0, 1, 1))
        self.assertEqual(len(d["trend"]), 14)
        self.assertEqual((d["trend"][-1]["signups"], d["trend"][-1]["orders"]), (2, 4))
        self.assertEqual([t["name"] for t in d["top_customers"]], ["Asha", "Ravi"])
        self.assertEqual(d["staff"], {"owner": 1, "cashier": 1, "kitchen": 1})


class TestPricing(unittest.TestCase):
    def test_plan_numbers(self):
        self.assertEqual((PLAN["yearly"], PLAN["monthly"], PLAN["gst_percent"]), (7000, 649, 18))
        base = 7000 / 12
        self.assertTrue(1.10 <= PLAN["monthly"] / base <= 1.15)                  # 10 to 15 percent above yearly/12

    def test_gst_formula(self):
        m = gst_breakdown(649)
        self.assertEqual((m["add_gst"], m["add_total"]), (116.82, 765.82))
        self.assertEqual((m["incl_base"], m["incl_gst"]), (550.0, 99.0))
        y = gst_breakdown(7000)
        self.assertEqual((y["add_gst"], y["add_total"]), (1260.0, 8260.0))
        self.assertEqual(gst_breakdown(100, 5)["add_total"], 105.0)

    def test_pricing_page_and_api_are_public(self):
        app = make_app()
        c = app.test_client()
        self.assertEqual(c.get("/pricing").status_code, 200)                      # public, even before anything is set up
        anon = app.test_client()
        self.assertEqual(anon.get("/pricing").status_code, 200)
        d = anon.get("/api/public/pricing").get_json()
        self.assertEqual((d["plan"]["monthly"], d["yearly_saving"], d["yearly_per_month"]), (649, 788, 583.33))
        self.assertEqual(d["gst"]["monthly"]["add_total"], 765.82)


class TestMigrationV1(unittest.TestCase):
    def test_database_from_the_menu_release_gains_customer_columns(self):
        path = os.path.join(tempfile.mkdtemp(), "old.db")
        con = sqlite3.connect(path)
        con.executescript("""
            CREATE TABLE orders (id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT NOT NULL, tok INTEGER NOT NULL, code TEXT NOT NULL UNIQUE,
              source TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'placed', customer_name TEXT NOT NULL DEFAULT '', phone TEXT NOT NULL DEFAULT '',
              note TEXT NOT NULL DEFAULT '', eta_min INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL, preparing_at INTEGER, ready_at INTEGER,
              collected_at INTEGER, cancelled_at INTEGER, cancel_reason TEXT NOT NULL DEFAULT '', created_by INTEGER, UNIQUE (day, tok));
            INSERT INTO orders (day, tok, code, source, created_at) VALUES ('2026-11-01', 1, 'abc', 'counter', 1);""")
        con.commit(); con.close()
        database.init_db(path)
        database.init_db(path)
        con = sqlite3.connect(path)
        cols = {r[1] for r in con.execute("PRAGMA table_info(orders)")}
        self.assertTrue({"customer_id", "rating", "rating_note", "rated_at"} <= cols)
        self.assertEqual(con.execute("SELECT code, customer_id, rating FROM orders").fetchone(), ("abc", None, None))
        self.assertIn("idx_orders_customer", {r[1] for r in con.execute("PRAGMA index_list(orders)")})


if __name__ == "__main__":
    unittest.main(verbosity=2)
