"""Shared test fixtures: a throw-away SQLite file per test + small HTTP helpers."""
import os
import re
import shutil
import tempfile
import unittest
from datetime import timedelta

# Must be set BEFORE the app is imported/created.
os.environ["SEED_DEMO"] = "false"
os.environ["APP_ENV"] = "testing"
os.environ.setdefault("SECRET_KEY", "unit-test-secret-key-" + "x" * 32)

import services  # noqa: E402
from app import create_app  # noqa: E402
from database import DONOR, NGO, DonationListing, db, utcnow  # noqa: E402

PASSWORD = "correct-horse-battery"
ADMIN_PASSWORD = "an-Extremely-strong-pass1"


class AppTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="foodshare-test-")
        self.uri = "sqlite:///" + os.path.join(self.tmp, "test.db").replace("\\", "/")
        self.app = create_app({"TESTING": True}, database_uri=self.uri)
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.counter = 0

    def tearDown(self):
        db.session.remove()
        db.engine.dispose()
        self.ctx.pop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---- data builders (all go through the real service layer) ----
    def make_donor(self, name="Test Kitchen", lat=12.978412, lng=77.640876,
                   address="12 Church Street"):
        self.counter += 1
        return services.register_user(name, f"donor{self.counter}@t.test", PASSWORD,
                                      DONOR, lat, lng, address)

    def make_ngo(self, name=None, lat=12.96, lng=77.64, approved=True):
        self.counter += 1
        ngo = services.register_user(name or f"NGO {self.counter}",
                                     f"ngo{self.counter}@t.test", PASSWORD, NGO, lat, lng)
        if approved:
            ngo.is_approved = True
            db.session.commit()
        return ngo
    def make_listing(self, donor, hours=4):
        return services.create_listing(donor, "Veg biryani", "20 meals", hours)

    def expire(self, listing_id):
        """Force a listing's expiry into the past directly in the database."""
        db.session.query(DonationListing).filter_by(id=listing_id).update(
            {DonationListing.expires_at: utcnow().replace(microsecond=0) - timedelta(minutes=5)})
        db.session.commit()

    def status_of(self, listing_id):
        db.session.expire_all()
        listing = db.session.get(DonationListing, listing_id)
        return None if listing is None else listing.status

    # ---- HTTP helpers ----
    def api_client(self, email, password=PASSWORD):
        client = self.app.test_client()
        token = client.get("/api/v1/csrf").get_json()["data"]["csrf_token"]
        res = client.post("/api/v1/auth/login", json={"email": email, "password": password},
                          headers={"X-CSRFToken": token})
        assert res.status_code == 200, res.get_json()
        client.token = res.get_json()["data"]["csrf_token"]
        return client

    @staticmethod
    def post(client, path, **kwargs):
        return client.post("/api/v1" + path, headers={"X-CSRFToken": client.token}, **kwargs)

    @staticmethod
    def page_token(client, path="/login"):
        html = client.get(path).get_data(as_text=True)
        match = re.search(r'name="csrf-token" content="([^"]+)"', html)
        assert match, "csrf meta tag missing"
        return match.group(1)

    def web_client(self, email, password=PASSWORD):
        client = self.app.test_client()
        token = self.page_token(client)
        res = client.post("/login", data={"email": email, "password": password,
                                          "csrf_token": token})
        assert res.status_code == 302, res.status_code
        return client
