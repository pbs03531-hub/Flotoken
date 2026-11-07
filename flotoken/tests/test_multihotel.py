"""Several restaurants on one server: everything must stay separate, and the Flotoken owner sees all of it."""
import os
import unittest

import db as database
from tests.harness import add_hotel, anon, hotel_login, make_app, platform_client


class Two(unittest.TestCase):
    def setUp(self):
        self.app = make_app()
        self.p = platform_client(self.app)
        add_hotel(self.p, name="Betty Military Hotel", slug="betty", owner="boss", password="secret1")
        add_hotel(self.p, name="Sree Biryani", slug="sree", owner="boss", password="other22", plan="monthly")
        self.a_owner, self.b_owner = hotel_login(self.app, "betty"), hotel_login(self.app, "sree", password="other22")

    def item(self, client):
        return client.get("/api/public/menu").get_json()["categories"][0]["items"][0]

    def customer(self, phone="9845012345", name="Asha"):
        c = self.app.test_client()
        r = c.post("/api/customer/signup", json={"name": name, "phone": phone, "password": "asha123", "consent": True})
        self.assertEqual(r.status_code, 201, r.get_json())
        return c

    def order(self, c, slug):
        it = self.item(anon(self.app, slug))
        r = c.post(f"/r/{slug}/api/public/orders", json={"items": [{"id": it["id"], "q": 1}]})
        self.assertEqual(r.status_code, 201, r.get_json())
        return r.get_json()


class TestSeparation(Two):
    def test_staff_login_works_only_at_their_own_restaurant(self):
        # same username "boss" at both places, different passwords
        self.assertEqual(anon(self.app, "betty").post("/api/auth/login", json={"username": "boss", "password": "other22"}).status_code, 401)
        self.assertEqual(anon(self.app, "sree").post("/api/auth/login", json={"username": "boss", "password": "secret1"}).status_code, 401)

    def test_a_staff_session_is_not_valid_at_another_restaurant(self):
        c = self.app.test_client()
        c.post("/r/betty/api/auth/login", json={"username": "boss", "password": "secret1"})
        self.assertEqual(c.get("/r/betty/api/orders").status_code, 200)
        self.assertEqual(c.get("/r/sree/api/orders").status_code, 401)
        self.assertEqual(c.get("/r/sree/admin").status_code, 302)
        self.assertEqual(c.get("/r/sree/api/admin/settings").status_code, 401)

    def test_menus_orders_and_images_do_not_leak(self):
        cat = self.a_owner.get("/api/menu").get_json()["categories"][0]["id"]
        r = self.a_owner.post("/api/admin/items", json={"category_id": cat, "name": "Only At Betty", "price": 99})
        self.assertEqual(r.status_code, 201, r.get_json())
        names = lambda cl: [i["name"] for c in cl.get("/api/public/menu").get_json()["categories"] for i in c["items"]]
        self.assertIn("Only At Betty", names(self.a_owner))
        self.assertNotIn("Only At Betty", names(self.b_owner))
        c = self.customer()
        o = self.order(c, "betty")
        self.assertEqual(c.get(f"/r/sree/api/public/orders/{o['code']}").status_code, 404)    # code from one hotel is unknown at the other
        self.assertEqual(c.get(f"/r/betty/api/public/orders/{o['code']}").status_code, 200)
        self.assertEqual(len(self.a_owner.get("/api/orders").get_json()["orders"]), 1)
        self.assertEqual(len(self.b_owner.get("/api/orders").get_json()["orders"]), 0)

    def test_each_restaurant_has_its_own_database_file(self):
        base = self.app.config["DATA_DIR"]
        self.assertTrue(os.path.exists(os.path.join(base, "platform.db")))
        for s in ("betty", "sree"):
            self.assertTrue(os.path.exists(os.path.join(base, "restaurants", s + ".db")), s)

    def test_token_numbers_start_at_one_in_each_restaurant(self):
        c = self.customer()
        self.assertEqual((self.order(c, "betty")["tok"], self.order(c, "sree")["tok"]), (1, 1))

    def test_settings_and_staff_are_separate(self):
        self.a_owner.put("/api/admin/settings", json={"restaurant_name": "Betty 2"})
        self.assertEqual(self.b_owner.get("/api/public/menu").get_json()["restaurant"], "Sree Biryani")
        self.a_owner.post("/api/admin/users", json={"username": "cash", "password": "pass123", "role": "cashier"})
        self.assertEqual(anon(self.app, "sree").post("/api/auth/login", json={"username": "cash", "password": "pass123"}).status_code, 401)
        names = {r["name"] for r in self.p.get("/api/public/restaurants").get_json()["restaurants"]}
        self.assertEqual(names, {"Betty 2", "Sree Biryani"})                                    # the rename reaches the shared list

    def test_unknown_restaurant_is_404_and_suspended_is_blocked(self):
        self.assertEqual(self.app.test_client().get("/r/nothing/order").status_code, 404)
        rid = next(r["id"] for r in self.p.get("/api/platform/overview").get_json()["restaurants"] if r["slug"] == "sree")
        self.assertEqual(self.p.put(f"/api/platform/restaurants/{rid}", json={"status": "suspended"}).status_code, 200)
        self.assertEqual(anon(self.app, "sree").get("/order").status_code, 403)
        self.assertEqual(anon(self.app, "sree").post("/api/auth/login", json={"username": "boss", "password": "other22"}).status_code, 403)
        self.assertEqual(self.b_owner.get("/api/orders").status_code, 403)
        self.assertEqual([r["slug"] for r in self.app.test_client().get("/api/public/restaurants").get_json()["restaurants"]], ["betty"])
        self.assertEqual(self.p.put(f"/api/platform/restaurants/{rid}", json={"status": "active"}).status_code, 200)
        self.assertEqual(self.b_owner.get("/api/orders").status_code, 200)


class TestCustomerAcrossRestaurants(Two):
    def test_one_account_orders_at_both_and_sees_both_histories(self):
        c = self.customer()
        o1, o2 = self.order(c, "betty"), self.order(c, "sree")
        allo = c.get("/api/customer/orders").get_json()["orders"]
        self.assertEqual({o["restaurant"]["slug"] for o in allo}, {"betty", "sree"})
        self.assertEqual([o["restaurant"]["slug"] for o in c.get("/api/customer/orders?r=sree").get_json()["orders"]], ["sree"])
        self.assertEqual(c.get(f"/r/sree/api/public/orders/{o2['code']}").get_json()["mine"], True)

    def test_each_restaurant_sees_only_its_own_customers(self):
        c, ravi = self.customer(), self.customer("9000000001", "Ravi")
        self.order(c, "betty"); self.order(ravi, "sree")
        self.a_owner.post("/api/admin/users", json={"username": "cash", "password": "pass123", "role": "cashier"})
        a_csv = self.a_owner.get("/api/customers.csv").get_data(as_text=True)
        b_csv = self.b_owner.get("/api/customers.csv").get_data(as_text=True)
        self.assertIn("Asha", a_csv); self.assertNotIn("Ravi", a_csv)
        self.assertIn("Ravi", b_csv); self.assertNotIn("Asha", b_csv)
        cid = self.a_owner.get("/api/customers?q=9845012345").get_json()["customers"][0]["id"]
        self.assertEqual(self.b_owner.get(f"/api/customers/{cid}").status_code, 404)            # never ordered at Sree

    def test_logging_in_at_a_restaurant_page_needs_the_customer_login(self):
        self.assertEqual(anon(self.app, "betty").post("/api/public/orders", json={"items": [{"id": 1, "q": 1}]}).status_code, 401)

    def test_delete_account_clears_personal_details_in_every_restaurant(self):
        c = self.customer()
        o1, o2 = self.order(c, "betty"), self.order(c, "sree")
        self.assertEqual(c.delete("/api/customer/me", json={"password": "asha123"}).status_code, 200)
        for owner in (self.a_owner, self.b_owner):
            row = owner.get("/api/orders").get_json()["orders"][0]
            self.assertEqual((row["phone"], row.get("customer_id")), ("", None))
            self.assertNotEqual(row["customer_name"], "Asha")
        self.assertEqual(self.app.test_client().post("/api/customer/login", json={"phone": "9845012345", "password": "asha123"}).status_code, 401)


class TestPlatformDashboard(Two):
    def test_requires_login(self):
        c = self.app.test_client()
        for method, url in (("get", "/api/platform/overview"), ("get", "/api/platform/customers"), ("post", "/api/platform/restaurants"),
                            ("post", "/api/platform/restaurants/1/owner")):
            self.assertEqual(getattr(c, method)(url, **({"json": {}} if method == "post" else {})).status_code, 401, url)
        self.assertEqual(c.post("/api/platform/login", json={"username": "flo", "password": "bad"}).status_code, 401)
        self.assertEqual(self.a_owner.get("/api/platform/overview").status_code, 401)               # a restaurant owner is not the platform owner

    def test_overview_counts_everything(self):
        c, ravi = self.customer(), self.customer("9000000001", "Ravi")
        self.order(c, "betty"); self.order(c, "betty"); self.order(ravi, "sree")
        d = self.p.get("/api/platform/overview").get_json()
        t = d["totals"]
        self.assertEqual((t["restaurants"], t["active"], t["paying"], t["trial"], t["customers"], t["orders"], t["orders_today"]), (2, 2, 1, 1, 2, 3, 3))
        self.assertEqual(t["mrr"], 649)
        by = {r["slug"]: r for r in d["restaurants"]}
        self.assertEqual((by["betty"]["orders"], by["betty"]["customers"], by["betty"]["owner"]), (2, 1, "boss"))
        self.assertEqual((by["sree"]["orders"], by["sree"]["plan"]), (1, "monthly"))
        self.assertEqual((len(d["trend"]), d["trend"][-1]["orders"], d["trend"][-1]["signups"]), (14, 3, 2))

    def test_create_validation(self):
        r = lambda **kw: self.p.post("/api/platform/restaurants", json={"name": "N", "slug": "new-one", "owner_username": "own", "owner_password": "pass123", **kw})
        self.assertEqual(r(slug="betty").status_code, 409)             # taken
        self.assertEqual(r(slug="admin").status_code, 400)             # reserved
        self.assertEqual(r(slug="Bad Slug!").status_code, 400)
        self.assertEqual(r(owner_password="x").status_code, 400)
        self.assertEqual(r(plan="gold").status_code, 400)
        self.assertEqual(r().status_code, 201)

    def test_owner_forgot_username_and_password(self):
        rid = next(x["id"] for x in self.p.get("/api/platform/overview").get_json()["restaurants"] if x["slug"] == "betty")
        r = self.p.post(f"/api/platform/restaurants/{rid}/owner", json={"username": "newboss", "password": "fresh123"})
        self.assertEqual((r.status_code, r.get_json()["username"]), (200, "newboss"))
        self.assertEqual(anon(self.app, "betty").post("/api/auth/login", json={"username": "boss", "password": "secret1"}).status_code, 401)
        self.assertEqual(anon(self.app, "betty").post("/api/auth/login", json={"username": "newboss", "password": "fresh123"}).status_code, 200)
        self.assertEqual(anon(self.app, "betty").post("/api/auth/login", json={"username": "newboss", "password": "secret1"}).status_code, 401)
        self.assertEqual(self.p.post(f"/api/platform/restaurants/{rid}/owner", json={"password": "x"}).status_code, 400)

    def test_edit_plan_and_paid_until(self):
        rid = next(x["id"] for x in self.p.get("/api/platform/overview").get_json()["restaurants"] if x["slug"] == "betty")
        self.assertEqual(self.p.put(f"/api/platform/restaurants/{rid}", json={"plan": "yearly", "paid_until": "2000-01-01", "notes": "paid by UPI"}).status_code, 200)
        row = next(x for x in self.p.get("/api/platform/overview").get_json()["restaurants"] if x["id"] == rid)
        self.assertEqual((row["plan"], row["expired"], row["notes"]), ("yearly", True, "paid by UPI"))
        self.assertEqual(self.p.put(f"/api/platform/restaurants/{rid}", json={"paid_until": "31/03/2027"}).status_code, 400)
        self.assertEqual(self.p.put(f"/api/platform/restaurants/{rid}", json={"plan": "gold"}).status_code, 400)

    def test_customer_search_and_platform_password_change(self):
        self.customer(); self.customer("9000000001", "Ravi")
        self.assertEqual(len(self.p.get("/api/platform/customers?q=ravi").get_json()["customers"]), 1)
        self.assertEqual(len(self.p.get("/api/platform/customers?q=98450").get_json()["customers"]), 1)
        self.assertEqual(self.p.get("/api/platform/customers").get_json()["total"], 2)
        self.assertEqual(self.p.post("/api/platform/password", json={"current": "bad", "new": "newpass1"}).status_code, 400)
        self.assertEqual(self.p.post("/api/platform/password", json={"current": "flopass1", "new": "newpass1"}).status_code, 200)
        self.assertEqual(self.app.test_client().post("/api/platform/login", json={"username": "flo", "password": "newpass1"}).status_code, 200)

    def test_backup_belongs_to_the_logged_in_restaurant(self):
        r = self.a_owner.get("/api/admin/backup")
        self.assertEqual(r.status_code, 200)
        self.assertIn("flotoken-betty-backup", r.headers["Content-Disposition"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
