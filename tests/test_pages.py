"""Smoke tests: every page renders (catches template errors)."""
import services
from tests.helpers import ADMIN_PASSWORD, AppTestCase


class PagesRender(AppTestCase):
    def test_public_pages(self):
        client = self.app.test_client()
        for path in ("/", "/login", "/register", "/api/docs", "/nope"):
            expected = 404 if path == "/nope" else 200
            self.assertEqual(client.get(path).status_code, expected, path)

    def test_dashboards_render_with_data(self):
        donor, ngo = self.make_donor(), self.make_ngo()
        self.make_listing(donor)
        services.create_admin("boss@t.test", ADMIN_PASSWORD)
        for email, path, pw in ((donor.email, "/donor", None), (ngo.email, "/ngo", None),
                                ("boss@t.test", "/admin", ADMIN_PASSWORD)):
            client = self.web_client(email, pw) if pw else self.web_client(email)
            res = client.get(path)
            self.assertEqual(res.status_code, 200, path)
            self.assertIn('id="boot"', res.get_data(as_text=True)) if path != "/admin" else None

    def test_api_unknown_route_returns_json(self):
        res = self.app.test_client().get("/api/v1/nope")
        self.assertEqual(res.status_code, 404)
        self.assertFalse(res.get_json()["success"])

    def test_web_claim_form_flow_with_csrf(self):
        donor, ngo = self.make_donor(), self.make_ngo()
        listing = self.make_listing(donor)
        client = self.web_client(ngo.email)
        token = self.page_token(client, "/ngo")
        res = client.post(f"/ngo/claim/{listing.id}", data={"csrf_token": token})
        self.assertEqual(res.status_code, 302)
        self.assertEqual(self.status_of(listing.id), "Claimed")
