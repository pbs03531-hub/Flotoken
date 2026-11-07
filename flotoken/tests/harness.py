"""Shared test helpers: a fresh multi-restaurant app, a platform admin, and a client that talks to one restaurant."""
import os
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp()      # for the module-level app created on import

import util  # noqa: E402
from app import create_app  # noqa: E402

GLOBAL = re.compile(r"^/(r/|api/customer/|api/platform/|api/public/(restaurants|pricing)|platform|staff|customer|pricing|healthz|offline|static/)")


class RC:
    """Test client for ONE restaurant: '/api/orders' becomes '/r/<slug>/api/orders'. Global URLs pass through."""

    def __init__(self, client, slug):
        self.c, self.slug = client, slug

    def _u(self, url):
        return url if GLOBAL.match(url) else f"/r/{self.slug}{url}"

    def get(self, url, **kw): return self.c.get(self._u(url), **kw)
    def post(self, url, **kw): return self.c.post(self._u(url), **kw)
    def put(self, url, **kw): return self.c.put(self._u(url), **kw)
    def delete(self, url, **kw): return self.c.delete(self._u(url), **kw)
    def __getattr__(self, name): return getattr(self.c, name)


def make_app(**cfg):
    util._hits.clear()
    return create_app({"DATA_DIR": tempfile.mkdtemp(), "TESTING": True, **cfg})


def platform_client(app, username="flo", password="flopass1"):
    c = app.test_client()
    r = c.post("/api/platform/setup", json={"username": username, "password": password})
    assert r.status_code == 201, r.get_json()
    return c


def add_hotel(platform, name="Test Hotel", slug="betty", owner="boss", password="secret1", sample=True, plan="trial", payment_mode="demo"):
    r = platform.post("/api/platform/restaurants", json={"name": name, "slug": slug, "owner_username": owner,
                                                         "owner_password": password, "plan": plan, "sample_menu": sample,
                                                         "payment_mode": payment_mode})
    assert r.status_code == 201, r.get_json()
    return r.get_json()


def hotel_login(app, slug, username="boss", password="secret1"):
    c = RC(app.test_client(), slug)
    r = c.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.get_json()
    return c


def new_hotel(app=None, name="Test Hotel", slug="betty", **kw):
    """(app, platform client, owner client of the restaurant)"""
    app = app or make_app()
    p = platform_client(app)
    add_hotel(p, name=name, slug=slug, **kw)
    return app, p, hotel_login(app, slug)


def anon(app, slug="betty"):
    return RC(app.test_client(), slug)
