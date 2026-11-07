"""Backend tests. Run from the project folder:  python -m unittest discover -s tests -v"""
import os
import sqlite3
import sys
import tempfile
import unittest

from tests.harness import RC, add_hotel, anon, hotel_login, make_app, platform_client, util  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.app = make_app()
        self.platform = platform_client(self.app)
        add_hotel(self.platform, name="Test Hotel", slug="betty")
        self.owner = hotel_login(self.app, "betty")
        self.cashier = self.login("cash", "cashier")
        self.kitchen = self.login("cook", "kitchen")
        self.anon = anon(self.app)
        menu = self.owner.get("/api/menu").get_json()["categories"]
        self.items = {i["name"]: i for c in menu for i in c["items"]}
        self.mb, self.ef, self.kd = (self.items[n]["id"] for n in ("Mutton Biryani", "Egg Fry", "Kal Dosa (2)"))

    def login(self, username, role):
        r = self.owner.post("/api/admin/users", json={"username": username, "password": "pass123", "role": role})
        self.assertEqual(r.status_code, 201, r.get_json())
        c = anon(self.app)
        self.assertEqual(c.post("/api/auth/login", json={"username": username, "password": "pass123"}).status_code, 200)
        return c

    def settings(self, **kw):
        r = self.owner.put("/api/admin/settings", json=kw)
        self.assertEqual(r.status_code, 200, r.get_json())

    def counter_order(self, items, pay=None, **extra):
        r = self.cashier.post("/api/orders", json={"items": items, "payMethod": pay, **extra})
        self.assertEqual(r.status_code, 201, r.get_json())
        return r.get_json()

    def status(self, client, oid, to):
        return client.post(f"/api/orders/{oid}/status", json={"status": to})


class TestAuth(Base):
    def test_login_rules(self):
        self.assertEqual(self.anon.post("/api/auth/login", json={"username": "boss", "password": "bad"}).status_code, 401)
        self.assertEqual(self.anon.get("/api/orders").status_code, 401)

    def test_json_required_blocks_csrf_style_posts(self):
        r = self.anon.post("/api/auth/login", data={"username": "boss", "password": "secret1"})
        self.assertEqual(r.status_code, 415)

    def test_login_rate_limit(self):
        for _ in range(8):
            self.anon.post("/api/auth/login", json={"username": "boss", "password": "nope"})
        self.assertEqual(self.anon.post("/api/auth/login", json={"username": "boss", "password": "secret1"}).status_code, 429)

    def test_roles(self):
        self.assertEqual(self.cashier.get("/api/admin/settings").status_code, 403)
        self.assertEqual(self.kitchen.get("/api/admin/reports").status_code, 403)
        self.assertEqual(self.kitchen.post("/api/orders", json={"items": [{"id": self.mb, "q": 1}]}).status_code, 403)
        self.assertEqual(self.owner.get("/api/admin/settings").status_code, 200)
        self.assertEqual(self.kitchen.get("/api/orders").status_code, 200)

    def test_user_guards(self):
        me = self.owner.get("/api/admin/users").get_json()["me"]
        self.assertEqual(self.owner.put(f"/api/admin/users/{me}", json={"role": "cashier"}).status_code, 409)
        self.assertEqual(self.owner.put(f"/api/admin/users/{me}", json={"active": False}).status_code, 409)
        dup = self.owner.post("/api/admin/users", json={"username": "BOSS", "password": "pass123", "role": "cashier"})
        self.assertEqual(dup.status_code, 409)
        self.assertEqual(self.owner.post("/api/admin/users", json={"username": "x y", "password": "pass123",
                                                                    "role": "cashier"}).status_code, 400)

    def test_deactivated_user_loses_access(self):
        users = self.owner.get("/api/admin/users").get_json()["users"]
        cid = next(u["id"] for u in users if u["username"] == "cash")
        self.owner.put(f"/api/admin/users/{cid}", json={"active": False})
        self.assertEqual(self.cashier.get("/api/orders").status_code, 401)

    def test_password_change(self):
        r = self.cashier.post("/api/auth/password", json={"current": "wrong", "new": "newpass1"})
        self.assertEqual(r.status_code, 400)
        r = self.cashier.post("/api/auth/password", json={"current": "pass123", "new": "newpass1"})
        self.assertEqual(r.status_code, 200)
        c = anon(self.app)
        self.assertEqual(c.post("/api/auth/login", json={"username": "cash", "password": "newpass1"}).status_code, 200)


class TestCounterFlow(Base):
    def test_unpaid_cannot_cook_or_collect(self):
        o = self.counter_order([{"id": self.mb, "q": 2}, {"id": self.ef, "q": 1}])
        self.assertEqual((o["tok"], o["total"], o["due"]), (1, 600, 600))
        self.assertEqual(self.status(self.kitchen, o["id"], "preparing").status_code, 409)
        self.assertEqual(self.kitchen.post(f"/api/orders/{o['id']}/pay", json={"method": "Cash"}).status_code, 403)
        r = self.cashier.post(f"/api/orders/{o['id']}/pay", json={"method": "Cash"}).get_json()
        self.assertEqual((r["due"], r["paid"]), (0, 600))
        self.assertEqual(self.cashier.post(f"/api/orders/{o['id']}/pay", json={"method": "Cash"}).status_code, 409)
        self.assertEqual(self.status(self.kitchen, o["id"], "ready").status_code, 409)       # cannot skip a step
        self.assertEqual(self.status(self.kitchen, o["id"], "preparing").status_code, 200)
        self.assertEqual(self.status(self.kitchen, o["id"], "ready").status_code, 200)
        self.assertEqual(self.status(self.kitchen, o["id"], "collected").status_code, 403)   # only cashier hands over
        done = self.status(self.cashier, o["id"], "collected").get_json()
        self.assertEqual(done["status"], "collected")
        self.assertIsNotNone(done["ready_at"])

    def test_edits_extra_due_approval_and_refund(self):
        o = self.counter_order([{"id": self.mb, "q": 2}, {"id": self.ef, "q": 1}], "Cash")
        oid = o["id"]
        self.status(self.cashier, oid, "preparing")
        r = self.cashier.post(f"/api/orders/{oid}/items", json={"item_id": self.ef, "delta": -1})
        self.assertEqual((r.status_code, r.get_json().get("needsApproval")), (409, True))
        r = self.cashier.post(f"/api/orders/{oid}/items", json={"item_id": self.ef, "delta": -1, "approved": True}).get_json()
        self.assertEqual((r["total"], r["refund"]), (560, 40))
        r = self.cashier.post(f"/api/orders/{oid}/refund", json={}).get_json()
        self.assertEqual((r["refund"], r["paid"]), (0, 560))
        r = self.cashier.post(f"/api/orders/{oid}/items", json={"item_id": self.kd, "delta": 1}).get_json()
        self.assertEqual(r["due"], 60)
        self.assertEqual(self.status(self.cashier, oid, "ready").status_code, 200)
        locked = self.cashier.post(f"/api/orders/{oid}/items", json={"item_id": self.kd, "delta": 1})
        self.assertEqual(locked.status_code, 409)
        self.assertEqual(self.status(self.cashier, oid, "collected").status_code, 409)       # extra 60 still due

    def test_cannot_empty_order_and_validation(self):
        o = self.counter_order([{"id": self.ef, "q": 1}], "UPI")
        r = self.cashier.post(f"/api/orders/{o['id']}/items", json={"item_id": self.ef, "delta": -1})
        self.assertEqual(r.status_code, 400)
        bad = [{"items": []}, {"items": [{"id": 9999, "q": 1}]}, {"items": [{"id": self.mb, "q": 0}]},
               {"items": [{"id": self.mb, "q": 51}]}, {"items": [{"id": self.mb, "q": True}]},
               {"items": [{"id": self.mb, "q": 1}], "payMethod": "Card"}]
        for body in bad:
            self.assertEqual(self.cashier.post("/api/orders", json=body).status_code, 400, body)

    def test_price_snapshot_survives_menu_edit_and_delete(self):
        o = self.counter_order([{"id": self.kd, "q": 1}], "UPI")
        self.owner.put(f"/api/admin/items/{self.kd}", json={"price": 999})
        self.assertEqual(self.cashier.get(f"/api/orders/{o['id']}").get_json()["total"], 60)
        self.owner.delete(f"/api/admin/items/{self.kd}", json={})
        self.assertEqual(self.cashier.get(f"/api/orders/{o['id']}").get_json()["items"][0]["name"], "Kal Dosa (2)")
        self.assertEqual(self.cashier.post("/api/orders", json={"items": [{"id": self.kd, "q": 1}]}).status_code, 400)

    def test_cancel_paid_order_creates_refund_and_leaves_board(self):
        o = self.counter_order([{"id": self.mb, "q": 1}], "Cash")
        r = self.cashier.post(f"/api/orders/{o['id']}/cancel", json={"reason": "Customer left"}).get_json()
        self.assertEqual((r["status"], r["refund"], r["due"]), ("cancelled", 280, 0))
        self.assertEqual(self.cashier.post(f"/api/orders/{o['id']}/cancel", json={}).status_code, 409)
        self.assertEqual(self.cashier.post(f"/api/orders/{o['id']}/refund", json={}).get_json()["refund"], 0)
        self.assertEqual(self.anon.get("/api/public/board").get_json()["preparing"], [])
        self.assertEqual(self.cashier.get("/api/orders").get_json()["orders"], [])

    def test_tokens_increment_and_history_search(self):
        a = self.counter_order([{"id": self.mb, "q": 1}], "UPI", name="Ravi", phone="98450 12345")
        b = self.counter_order([{"id": self.ef, "q": 1}], "Cash")
        self.assertEqual((a["tok"], b["tok"]), (1, 2))
        self.assertEqual(a["phone"], "9845012345")
        h = lambda q: [o["tok"] for o in self.cashier.get(f"/api/orders?scope=history&q={q}").get_json()["orders"]]
        self.assertEqual(h("2"), [2])
        self.assertEqual(h("98450"), [1])
        self.assertEqual(h("rav"), [1])
        self.assertEqual(len(self.cashier.get("/api/orders?scope=history").get_json()["orders"]), 2)
        s = self.cashier.get("/api/orders").get_json()["summary"]
        self.assertEqual((s["orders"], s["upi"], s["cash"]), (2, 280, 40))
        self.assertEqual(self.cashier.get("/api/orders?scope=history&date=bad").status_code, 400)

    def test_audit_log_records_who(self):
        o = self.counter_order([{"id": self.mb, "q": 1}])
        self.cashier.post(f"/api/orders/{o['id']}/pay", json={"method": "Cash"})
        full = self.cashier.get(f"/api/orders/{o['id']}").get_json()
        self.assertTrue(any(l["user"] == "cash" and "Cash payment" in l["text"] for l in full["log"]))
        self.assertEqual(full["payments"][0]["staff"], "cash")


class TestPublicFlow(Base):
    def setUp(self):
        super().setUp()
        self.cust = anon(self.app)          # a customer must be signed in to order
        r = self.cust.post("/api/customer/signup", json={"name": "Asha", "phone": "98450 12345", "password": "asha123", "consent": True})
        self.assertEqual(r.status_code, 201, r.get_json())

    def place(self, items=None):
        return self.cust.post("/api/public/orders", json={"items": items or [{"id": self.mb, "q": 2}]})

    def test_menu_and_demo_payment(self):
        m = self.anon.get("/api/public/menu").get_json()
        self.assertEqual([c["name"] for c in m["categories"]], ["Biryani", "Starters", "Meals & Tiffin"])
        self.assertTrue(m["accepting"])
        r = self.place()
        self.assertEqual(r.status_code, 201)
        v = r.get_json()
        self.assertEqual((v["tok"], v["total"], v["due"], v["upi"]), (1, 560, 0, None))
        self.assertNotIn("phone", v)
        t = self.anon.get(f"/api/public/orders/{v['code']}").get_json()
        self.assertEqual(t["status"], "placed")
        self.assertEqual(self.anon.get("/api/public/orders/nope").status_code, 404)
        self.assertEqual(self.anon.get("/api/public/board").get_json()["preparing"], [1])

    def test_login_required_to_order(self):
        r = self.anon.post("/api/public/orders", json={"items": [{"id": self.mb, "q": 1}], "phone": "9845012345", "name": "X"})
        self.assertEqual(r.status_code, 401)
        oid = self.cashier.get("/api/orders").get_json()["orders"]
        self.assertEqual(oid, [])                                  # nothing was created

    def test_upi_manual_needs_staff_confirmation(self):
        self.assertEqual(self.owner.put("/api/admin/settings", json={"payment_mode": "upi_manual"}).status_code, 400)
        self.settings(payment_mode="upi_manual", upi_vpa="myhotel@okbank", upi_name="My Hotel")
        v = self.place().get_json()
        self.assertEqual(v["due"], 560)
        self.assertTrue(v["upi"]["link"].startswith("upi://pay?pa=myhotel%40okbank"))
        self.assertIn("am=560.00", v["upi"]["link"])
        self.assertEqual(self.anon.get("/api/public/board").get_json()["preparing"], [])   # unpaid: not shown
        oid = self.cashier.get("/api/orders").get_json()["orders"][0]["id"]
        self.assertEqual(self.status(self.kitchen, oid, "preparing").status_code, 409)
        self.cashier.post(f"/api/orders/{oid}/pay", json={"method": "UPI"})
        self.assertEqual(self.status(self.kitchen, oid, "preparing").status_code, 200)
        self.status(self.kitchen, oid, "ready")
        b = self.anon.get("/api/public/board").get_json()
        self.assertEqual((b["ready"], b["preparing"]), ([1], []))
        self.assertIsNone(self.anon.get(f"/api/public/orders/{v['code']}").get_json()["upi"])

    def test_closing_phone_orders(self):
        self.settings(accepting_orders=False)
        self.assertEqual(self.place().status_code, 403)
        self.assertFalse(self.anon.get("/api/public/menu").get_json()["accepting"])
        self.counter_order([{"id": self.mb, "q": 1}], "Cash")          # counter still works

    def test_sold_out_blocks_orders_everywhere(self):
        self.assertEqual(self.kitchen.post(f"/api/menu/{self.mb}/available", json={"available": False}).status_code, 200)
        r = self.place()
        self.assertEqual((r.status_code, r.get_json()["item_id"]), (409, self.mb))
        self.assertEqual(self.cashier.post("/api/orders", json={"items": [{"id": self.mb, "q": 1}]}).status_code, 409)
        cats = self.anon.get("/api/public/menu").get_json()["categories"]
        self.assertFalse(next(i for c in cats for i in c["items"] if i["id"] == self.mb)["available"])
        self.kitchen.post(f"/api/menu/{self.mb}/available", json={"available": True})
        self.assertEqual(self.place().status_code, 201)

    def test_order_rate_limit(self):
        for _ in range(12):
            self.assertEqual(self.place([{"id": self.ef, "q": 1}]).status_code, 201)
        self.assertEqual(self.place([{"id": self.ef, "q": 1}]).status_code, 429)

    def test_eta_grows_with_queue(self):
        e1 = self.place().get_json()["eta_min"]
        e2 = self.place().get_json()["eta_min"]
        self.assertEqual((e1, e2), (10, 14))


class TestAdmin(Base):
    def test_menu_management(self):
        cid = self.owner.post("/api/admin/categories", json={"name": "Drinks"}).get_json()["id"]
        iid = self.owner.post("/api/admin/items", json={"category_id": cid, "name": "Buttermilk", "price": 30,
                                                         "diet": "veg"}).get_json()["id"]
        self.assertEqual(self.owner.delete(f"/api/admin/categories/{cid}", json={}).status_code, 409)
        self.assertEqual(self.owner.put(f"/api/admin/items/{iid}", json={"price": -5}).status_code, 400)
        self.owner.put(f"/api/admin/items/{iid}", json={"price": 35})
        cats = self.owner.get("/api/menu").get_json()["categories"]
        self.assertEqual(cats[-1]["name"], "Drinks")
        self.assertEqual(cats[-1]["items"][0]["price"], 35)
        self.owner.post(f"/api/admin/categories/{cid}/move", json={"dir": -1})
        self.assertEqual(self.owner.get("/api/menu").get_json()["categories"][-2]["name"], "Drinks")
        self.owner.delete(f"/api/admin/items/{iid}", json={})
        self.assertEqual(self.owner.delete(f"/api/admin/categories/{cid}", json={}).status_code, 200)

    def test_settings_validation(self):
        for bad in ({"nope": 1}, {"upi_vpa": "not a vpa"}, {"eta_base": 999}, {"payment_mode": "cash"},
                    {"restaurant_name": ""}):
            self.assertEqual(self.owner.put("/api/admin/settings", json=bad).status_code, 400, bad)
        self.settings(restaurant_name="Betty's Military Hotel", eta_base=15)
        self.assertEqual(self.anon.get("/api/public/menu").get_json()["restaurant"], "Betty's Military Hotel")

    def test_reports_and_csv(self):
        a = self.counter_order([{"id": self.mb, "q": 2}], "UPI")
        self.status(self.cashier, a["id"], "preparing")
        self.status(self.cashier, a["id"], "ready")
        self.status(self.cashier, a["id"], "collected")
        self.counter_order([{"id": self.ef, "q": 1}], "Cash")
        c = self.counter_order([{"id": self.kd, "q": 1}], "Cash")
        self.cashier.post(f"/api/orders/{c['id']}/cancel", json={"reason": "test"})
        self.cashier.post(f"/api/orders/{c['id']}/refund", json={})
        d = self.counter_order([{"id": self.kd, "q": 2}])                      # unpaid
        r = self.owner.get("/api/admin/reports").get_json()
        self.assertEqual((r["orders"], r["cancelled"], r["sales"]), (3, 1, 560 + 40 + 120))
        self.assertEqual((r["upi"], r["cash"], r["unpaid"]), (560, 40, 120))
        self.assertEqual(r["top_items"][0]["name"], "Mutton Biryani")
        self.assertEqual(sum(r["by_hour"]), 3)
        self.assertIsNotNone(r["avg_prep_min"])
        csv_text = self.owner.get("/api/admin/reports/export.csv").data.decode("utf-8-sig")
        self.assertEqual(len(csv_text.strip().splitlines()), 5)
        self.assertIn("2 x Mutton Biryani", csv_text)
        self.assertEqual(self.owner.get("/api/admin/reports?from=2026-02-01&to=2026-01-01").status_code, 400)
        self.assertEqual(self.owner.get(f"/api/orders/{d['id']}").status_code, 200)

    def test_backup_is_valid_sqlite(self):
        r = self.owner.get("/api/admin/backup")
        self.assertEqual(r.status_code, 200)
        path = os.path.join(tempfile.mkdtemp(), "b.db")
        with open(path, "wb") as fh:
            fh.write(r.data)
        n = sqlite3.connect(path).execute("SELECT COUNT(*) FROM users").fetchone()[0]
        self.assertEqual(n, 3)
        self.assertEqual(self.cashier.get("/api/admin/backup").status_code, 403)


if __name__ == "__main__":
    unittest.main(verbosity=2)
