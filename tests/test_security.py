"""Authentication, CSRF, authorization, secrets and location privacy."""
import os
from unittest import mock

import services
from app import create_app
from database import ADMIN, User, db
from services import ServiceError
from tests.helpers import ADMIN_PASSWORD, PASSWORD, AppTestCase


class AdminSetup(AppTestCase):
    def test_there_is_no_default_admin_account(self):
        self.assertEqual(User.query.filter_by(role=ADMIN).count(), 0)
        client = self.app.test_client()
        token = client.get("/api/v1/csrf").get_json()["data"]["csrf_token"]
        res = client.post("/api/v1/auth/login", headers={"X-CSRFToken": token},
                          json={"email": "admin@foodshare.local", "password": "admin123"})
        self.assertEqual(res.status_code, 401)

    def test_admin_password_must_be_strong(self):
        for weak in ("short", "admin123", "password123", "12345678901"):
            with self.assertRaises(ServiceError, msg=weak):
                services.create_admin("boss@t.test", weak)

    def test_strong_admin_can_be_created(self):
        admin = services.create_admin("boss@t.test", ADMIN_PASSWORD)
        self.assertEqual(admin.role, ADMIN)

    def test_public_registration_cannot_create_an_admin(self):
        for role in ("Admin", "admin", ""):
            with self.assertRaises(ServiceError):
                services.register_user("Eve", "eve@t.test", PASSWORD, role)
        client = self.app.test_client()
        token = client.get("/api/v1/csrf").get_json()["data"]["csrf_token"]
        res = client.post("/api/v1/auth/register", headers={"X-CSRFToken": token},
                          json={"name": "Eve", "email": "eve@t.test", "password": PASSWORD, "role": "Admin"})
        self.assertEqual(res.status_code, 400)

    def test_cli_command_creates_an_admin(self):
        runner = self.app.test_cli_runner()
        result = runner.invoke(args=["create-admin", "--email", "cli@t.test"],
                               input=f"{ADMIN_PASSWORD}\n{ADMIN_PASSWORD}\n")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(User.query.filter_by(email="cli@t.test", role=ADMIN).count(), 1)


class PasswordStorage(AppTestCase):
    def test_passwords_are_stored_as_salted_hashes(self):
        user = self.make_donor()
        self.assertNotIn(PASSWORD, user.password_hash)
        self.assertRegex(user.password_hash, r"^(scrypt|pbkdf2):")
        other = self.make_donor()
        self.assertNotEqual(user.password_hash, other.password_hash)  # unique salt
        self.assertTrue(user.check_password(PASSWORD))
        self.assertFalse(user.check_password("wrong"))

    def test_weak_and_oversized_passwords_are_rejected_on_signup(self):
        for pw in ("short", "password123", "x" * 200):
            with self.assertRaises(ServiceError, msg=pw[:12]):
                services.register_user("A", "a@t.test", pw, "Donor")


class SecretKey(AppTestCase):
    def test_secret_key_comes_from_the_environment(self):
        self.assertEqual(self.app.config["SECRET_KEY"], os.environ["SECRET_KEY"])

    def test_production_refuses_to_start_without_a_strong_key(self):
        for bad in ("", "short", "change-me"):
            with mock.patch.dict(os.environ, {"APP_ENV": "production", "SECRET_KEY": bad}):
                with self.assertRaises(RuntimeError, msg=repr(bad)):
                    create_app({}, database_uri=self.uri)

    def test_production_with_a_strong_key_starts_with_secure_cookies(self):
        with mock.patch.dict(os.environ, {"APP_ENV": "production", "SECRET_KEY": "k" * 64}):
            prod = create_app({}, database_uri=self.uri)
        self.assertTrue(prod.config["SESSION_COOKIE_SECURE"])
        self.assertFalse(prod.config["SHOW_DEMO_HINT"])


class Csrf(AppTestCase):
    def test_api_post_without_token_is_rejected(self):
        res = self.app.test_client().post("/api/v1/auth/login", json={"email": "a@b.c", "password": "x"})
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.get_json()["error"]["code"], "csrf_failed")

    def test_api_post_with_wrong_token_is_rejected(self):
        client = self.app.test_client()
        client.get("/api/v1/csrf")
        res = client.post("/api/v1/auth/login", headers={"X-CSRFToken": "forged"},
                          json={"email": "a@b.c", "password": "x"})
        self.assertEqual(res.status_code, 403)

    def test_state_changing_api_calls_need_the_token_after_login(self):
        ngo = self.make_ngo()
        listing = self.make_listing(self.make_donor())
        client = self.api_client(ngo.email)
        res = client.post(f"/api/v1/listings/{listing.id}/claim")  # no header
        self.assertEqual(res.status_code, 403)
        self.assertEqual(self.status_of(listing.id), "Pending")

    def test_web_form_post_without_token_is_rejected(self):
        res = self.app.test_client().post("/login", data={"email": "a@b.c", "password": "x"})
        self.assertEqual(res.status_code, 403)

    def test_logout_is_post_only_and_csrf_protected(self):
        donor = self.make_donor()
        client = self.web_client(donor.email)
        self.assertEqual(client.get("/logout").status_code, 405)
        self.assertEqual(client.post("/logout").status_code, 403)
        token = self.page_token(client, "/donor")
        self.assertEqual(client.post("/logout", data={"csrf_token": token}).status_code, 302)
        self.assertEqual(client.get("/donor").status_code, 302)  # logged out

    def test_forms_contain_the_token(self):
        html = self.app.test_client().get("/login").get_data(as_text=True)
        self.assertIn('name="csrf_token"', html)


class Authorization(AppTestCase):
    def setUp(self):
        super().setUp()
        self.donor = self.make_donor()
        self.ngo = self.make_ngo()
        self.admin = services.create_admin("boss@t.test", ADMIN_PASSWORD)

    def test_admin_page_is_closed_to_everyone_but_admins(self):
        self.assertEqual(self.app.test_client().get("/admin").status_code, 302)  # -> login
        self.assertEqual(self.web_client(self.donor.email).get("/admin").status_code, 403)
        self.assertEqual(self.web_client(self.ngo.email).get("/admin").status_code, 403)
        admin_client = self.web_client("boss@t.test", ADMIN_PASSWORD)
        self.assertEqual(admin_client.get("/admin").status_code, 200)

    def test_admin_api_is_closed_to_everyone_but_admins(self):
        self.assertEqual(self.app.test_client().get("/api/v1/users").status_code, 401)
        self.assertEqual(self.api_client(self.donor.email).get("/api/v1/users").status_code, 403)
        self.assertEqual(self.api_client(self.ngo.email).get("/api/v1/users").status_code, 403)
        res = self.api_client("boss@t.test", ADMIN_PASSWORD).get("/api/v1/users")
        self.assertEqual(res.status_code, 200)
        self.assertNotIn("password", res.get_data(as_text=True))

    def test_roles_are_enforced_on_the_server(self):
        listing = self.make_listing(self.donor)
        ngo_client = self.api_client(self.ngo.email)
        donor_client = self.api_client(self.donor.email)
        res = self.post(ngo_client, "/listings", json={"food_type": "x", "quantity": "1", "expiry_window": 2})
        self.assertEqual(res.status_code, 403)  # NGOs cannot donate
        res = self.post(donor_client, f"/listings/{listing.id}/claim")
        self.assertEqual(res.status_code, 403)  # donors cannot claim

    def test_users_cannot_read_listings_they_have_no_right_to(self):
        listing = self.make_listing(self.donor)
        other = self.make_donor("Rival")
        res = self.api_client(other.email).get(f"/api/v1/listings/{listing.id}")
        self.assertEqual(res.status_code, 404)

    def test_security_headers_are_set(self):
        res = self.app.test_client().get("/login")
        self.assertEqual(res.headers["X-Frame-Options"], "DENY")
        self.assertEqual(res.headers["X-Content-Type-Options"], "nosniff")


class LocationPrivacy(AppTestCase):
    def setUp(self):
        super().setUp()
        self.donor = self.make_donor(lat=12.978412, lng=77.640876, address="12 Church Street")
        self.ngo = self.make_ngo()
        self.listing = self.make_listing(self.donor)

    def test_ngo_sees_only_an_approximate_area_before_claiming(self):
        data = self.api_client(self.ngo.email).get("/api/v1/listings").get_json()["data"][0]
        donor = data["donor"]
        self.assertEqual(donor["location_precision"], "approximate")
        self.assertEqual((donor["latitude"], donor["longitude"]), (12.98, 77.64))
        self.assertNotIn("email", donor)
        self.assertNotIn("address", donor)
        raw = str(data)
        for secret in ("12.978412", "77.640876", "12 Church Street", self.donor.email):
            self.assertNotIn(secret, raw)

    def test_exact_details_are_revealed_only_to_the_claiming_ngo(self):
        client = self.api_client(self.ngo.email)
        claimed = self.post(client, f"/listings/{self.listing.id}/claim").get_json()["data"]["donor"]
        self.assertEqual(claimed["location_precision"], "exact")
        self.assertEqual((claimed["latitude"], claimed["longitude"]), (12.978412, 77.640876))
        self.assertEqual(claimed["address"], "12 Church Street")
        self.assertEqual(claimed["email"], self.donor.email)
        mine = client.get("/api/v1/listings?scope=mine").get_json()["data"][0]["donor"]
        self.assertEqual(mine["location_precision"], "exact")

    def test_other_ngos_cannot_see_a_claimed_listing_at_all(self):
        self.post(self.api_client(self.ngo.email), f"/listings/{self.listing.id}/claim")
        rival = self.api_client(self.make_ngo().email)
        self.assertEqual(rival.get(f"/api/v1/listings/{self.listing.id}").status_code, 404)
        self.assertEqual(rival.get("/api/v1/listings").get_json()["data"], [])

    def test_the_donor_always_sees_their_own_exact_location(self):
        data = self.api_client(self.donor.email).get("/api/v1/listings").get_json()["data"][0]
        self.assertEqual(data["donor"]["location_precision"], "exact")

    def test_approximate_circle_always_contains_the_real_point(self):
        from database import APPROX_RADIUS_M
        lat, lng = self.listing.approx_location
        dist_m = services.haversine_km(lat, lng, self.donor.latitude, self.donor.longitude) * 1000
        self.assertLess(dist_m, APPROX_RADIUS_M)
