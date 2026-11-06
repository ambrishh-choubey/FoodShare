"""NGO approval, login password-length rule and login rate limiting."""
from datetime import timedelta

import services
from database import LoginAttempt, User, db, utcnow
from services import ServiceError
from tests.helpers import ADMIN_PASSWORD, PASSWORD, AppTestCase


class NgoApproval(AppTestCase):
    def setUp(self):
        super().setUp()
        self.admin = services.create_admin("boss@t.test", ADMIN_PASSWORD)
        self.donor = self.make_donor()
        self.listing_id = self.make_listing(self.donor).id
        self.ngo = self.make_ngo(approved=False)
        self.ngo_id = self.ngo.id

    def test_new_ngos_start_unapproved_but_donors_do_not(self):
        self.assertFalse(self.ngo.is_approved)
        self.assertTrue(self.donor.is_approved)

    def test_unapproved_ngo_cannot_browse_or_claim(self):
        for action in (lambda: services.claim_listing(self.ngo, self.listing_id),
                       lambda: services.nearby_listings(self.ngo, 50)):
            with self.assertRaises(ServiceError) as ctx:
                action()
            self.assertEqual((ctx.exception.code, ctx.exception.status), ("not_approved", 403))
        self.assertEqual(self.status_of(self.listing_id), "Pending")

    def test_unapproved_ngo_over_http(self):
        res = self.api_client(self.ngo.email).get("/api/v1/listings")
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.get_json()["error"]["code"], "not_approved")
        page = self.web_client(self.ngo.email).get("/ngo")
        self.assertEqual(page.status_code, 200)
        self.assertIn("awaiting approval", page.get_data(as_text=True))

    def test_admin_approval_unlocks_claiming_and_revoking_locks_it_again(self):
        services.set_ngo_approval(self.admin, self.ngo_id, True)
        db.session.refresh(self.ngo)
        self.assertEqual(services.claim_listing(self.ngo, self.listing_id).status, "Claimed")
        services.set_ngo_approval(self.admin, self.ngo_id, False)
        db.session.refresh(self.ngo)
        with self.assertRaises(ServiceError) as ctx:
            services.nearby_listings(self.ngo, 50)
        self.assertEqual(ctx.exception.code, "not_approved")

    def test_only_admins_can_approve(self):
        with self.assertRaises(ServiceError) as ctx:
            services.set_ngo_approval(self.donor, self.ngo_id, True)
        self.assertEqual(ctx.exception.status, 403)
        for email in (self.donor.email, self.ngo.email):  # a donor, and the NGO itself
            client = self.web_client(email)
            token = self.page_token(client, "/donor" if email == self.donor.email else "/ngo")
            res = client.post(f"/admin/ngos/{self.ngo_id}/approve", data={"csrf_token": token})
            self.assertEqual(res.status_code, 403)
        ngo_api = self.api_client(self.ngo.email)
        self.assertEqual(self.post(ngo_api, f"/users/{self.ngo_id}/approve").status_code, 403)
        db.session.expire_all()
        self.assertFalse(db.session.get(User, self.ngo_id).is_approved)

    def test_admin_can_approve_from_the_admin_page(self):
        admin = self.web_client("boss@t.test", ADMIN_PASSWORD)
        self.assertIn(self.ngo.name, admin.get("/admin").get_data(as_text=True))
        token = self.page_token(admin, "/admin")
        res = admin.post(f"/admin/ngos/{self.ngo_id}/approve", data={"csrf_token": token})
        self.assertEqual(res.status_code, 302)
        db.session.expire_all()
        self.assertTrue(db.session.get(User, self.ngo_id).is_approved)

    def test_only_ngos_can_be_approved(self):
        with self.assertRaises(ServiceError) as ctx:
            services.set_ngo_approval(self.admin, self.donor.id, True)
        self.assertEqual(ctx.exception.status, 404)


class PasswordLength(AppTestCase):
    def test_oversized_password_is_rejected_not_truncated(self):
        long_pw = ("Zx9-" * 32)[:128]
        services.register_user("Long", "long@t.test", long_pw, "Donor")
        self.assertEqual(services.authenticate("long@t.test", long_pw).email, "long@t.test")
        before = LoginAttempt.query.count()
        with self.assertRaises(ServiceError) as ctx:  # the old code truncated this and let it in
            services.authenticate("long@t.test", long_pw + "EXTRA")
        self.assertEqual((ctx.exception.code, ctx.exception.status), ("validation_error", 400))
        self.assertEqual(LoginAttempt.query.count(), before)
        with self.assertRaises(ServiceError) as ctx:
            services.authenticate("long@t.test", long_pw[:127])
        self.assertEqual(ctx.exception.code, "invalid_credentials")

    def test_oversized_password_over_http(self):
        client = self.app.test_client()
        token = client.get("/api/v1/csrf").get_json()["data"]["csrf_token"]
        res = client.post("/api/v1/auth/login", headers={"X-CSRFToken": token},
                          json={"email": "a@b.co", "password": "x" * 129})
        self.assertEqual(res.status_code, 400)


class LoginThrottle(AppTestCase):
    IP = "10.0.0.1"

    def setUp(self):
        super().setUp()
        self.donor = self.make_donor()

    def fail(self, email=None, ip=None):
        with self.assertRaises(ServiceError) as ctx:
            services.authenticate(email or self.donor.email, "wrong-password", ip or self.IP)
        return ctx.exception.code

    def test_account_is_locked_after_five_failures_even_for_the_right_password(self):
        email = self.donor.email
        for _ in range(5):
            self.assertEqual(self.fail(email), "invalid_credentials")
        with self.assertRaises(ServiceError) as ctx:
            services.authenticate(email, PASSWORD, self.IP)
        self.assertEqual((ctx.exception.code, ctx.exception.status), ("rate_limited", 429))
        self.assertGreater(ctx.exception.retry_after, 0)

    def test_lock_expires_after_the_window(self):
        email = self.donor.email
        for _ in range(5):
            self.fail(email)
        db.session.query(LoginAttempt).update(
            {LoginAttempt.created_at: utcnow() - timedelta(minutes=16)})
        db.session.commit()
        self.assertEqual(services.authenticate(email, PASSWORD, self.IP).email, email)

    def test_successful_login_resets_the_account_counter(self):
        email = self.donor.email
        for _ in range(4):
            self.fail(email)
        services.authenticate(email, PASSWORD, self.IP)
        for _ in range(4):
            self.assertEqual(self.fail(email), "invalid_credentials")  # not locked

    def test_unknown_emails_are_throttled_too(self):
        for _ in range(5):
            self.assertEqual(self.fail("ghost@t.test"), "invalid_credentials")
        self.assertEqual(self.fail("ghost@t.test"), "rate_limited")

    def test_one_ip_cannot_guess_across_many_accounts(self):
        for i in range(20):
            self.assertEqual(self.fail(f"user{i}@t.test"), "invalid_credentials")
        self.assertEqual(self.fail("another@t.test"), "rate_limited")
        self.assertEqual(services.authenticate(self.donor.email, PASSWORD, "10.9.9.9").role, "Donor")

    def test_api_returns_429_with_retry_after(self):
        client = self.app.test_client()
        token = client.get("/api/v1/csrf").get_json()["data"]["csrf_token"]
        body = {"email": self.donor.email, "password": "nope-nope"}
        ip = {"REMOTE_ADDR": "10.1.1.1"}
        for _ in range(5):
            res = client.post("/api/v1/auth/login", json=body, headers={"X-CSRFToken": token},
                              environ_overrides=ip)
            self.assertEqual(res.status_code, 401)
        res = client.post("/api/v1/auth/login", json=body, headers={"X-CSRFToken": token},
                          environ_overrides=ip)
        self.assertEqual(res.status_code, 429)
        self.assertEqual(res.get_json()["error"]["code"], "rate_limited")
        self.assertGreater(int(res.headers["Retry-After"]), 0)

    def test_web_login_page_returns_429(self):
        client = self.app.test_client()
        token = self.page_token(client)
        for _ in range(5):
            client.post("/login", data={"email": self.donor.email, "password": "bad-bad-bad",
                                        "csrf_token": token})
        res = client.post("/login", data={"email": self.donor.email, "password": PASSWORD,
                                          "csrf_token": token})
        self.assertEqual(res.status_code, 429)