"""Impact analytics: numbers come from real records, scoped per role."""
import re
from datetime import timedelta

import services
from database import DonationListing, db, utcnow
from tests.helpers import ADMIN_PASSWORD, AppTestCase


class Analytics(AppTestCase):
    def setUp(self):
        super().setUp()
        self.admin = services.create_admin("boss@t.test", ADMIN_PASSWORD)
        self.donor = self.make_donor()
        self.ngo = self.make_ngo()
        # five listings, one in each outcome
        ids = [self.make_listing(self.donor).id for _ in range(5)]
        self.withdrawn, self.expired, self.claimed, self.completed, self.available = ids
        services.withdraw_listing(self.donor, self.withdrawn)
        self.expire(self.expired)
        services.claim_listing(self.ngo, self.claimed)
        services.claim_listing(self.ngo, self.completed)
        services.mark_picked_up(self.ngo, self.completed)

    def test_donor_numbers_match_the_database(self):
        got = services.analytics_for(self.donor)["listings"]
        self.assertEqual(got, {"total": 5, "available": 1, "claimed": 1, "completed": 1,
                               "withdrawn": 1, "expired": 1, "active": 2})

    def test_every_donation_is_in_exactly_one_outcome(self):
        got = services.analytics_for(self.donor)["listings"]
        self.assertEqual(got["total"], got["available"] + got["claimed"] + got["completed"]
                         + got["withdrawn"] + got["expired"])

    def test_withdrawn_listing_is_kept_but_hidden_from_ngos(self):
        self.assertEqual(self.status_of(self.withdrawn), "Withdrawn")
        ids = [l.id for l, _ in services.nearby_listings(self.ngo, 50)]
        self.assertNotIn(self.withdrawn, ids)
        self.assertIn(self.available, ids)

    def test_donors_only_see_their_own_numbers(self):
        other = self.make_donor("Other Kitchen")
        self.make_listing(other)
        self.assertEqual(services.analytics_for(other)["listings"]["total"], 1)
        self.assertEqual(services.analytics_for(self.donor)["listings"]["total"], 5)

    def test_ngo_numbers(self):
        got = services.analytics_for(self.ngo)["claims"]
        self.assertEqual(got, {"claimed_total": 2, "completed": 1, "pending_pickups": 1,
                               "donors_helped": 1})
        rival = self.make_ngo()
        self.assertEqual(services.analytics_for(rival)["claims"],
                         {"claimed_total": 0, "completed": 0, "pending_pickups": 0,
                          "donors_helped": 0})

    def test_admin_numbers(self):
        self.make_ngo(approved=False)
        data = services.analytics_for(self.admin)
        self.assertEqual(data["users"], {"donors": 1, "ngos": 2, "ngos_approved": 1,
                                         "ngos_pending": 1})
        self.assertEqual(data["listings"]["total"], 5)
        self.assertEqual(data["listings"]["completed"], 1)
        self.assertEqual(data["listings"]["active"], 2)
        self.assertEqual(data["posted_last_7_days"], 5)

    def test_empty_datasets_return_zeros_not_errors(self):
        fresh_donor, fresh_ngo = self.make_donor("New"), self.make_ngo()
        donor = services.analytics_for(fresh_donor)
        self.assertEqual(donor["listings"]["total"], 0)
        self.assertEqual(donor["activity"]["values"], [0] * 14)
        self.assertEqual(services.analytics_for(fresh_ngo)["claims"]["claimed_total"], 0)

    def test_activity_series_counts_only_the_last_14_days(self):
        db.session.query(DonationListing).filter_by(id=self.available).update(
            {DonationListing.created_at: utcnow() - timedelta(days=20)})
        db.session.commit()
        series = services.analytics_for(self.donor)["activity"]
        self.assertEqual(len(series["labels"]), 14)
        self.assertEqual(sum(series["values"]), 4)


class AnalyticsAccess(AppTestCase):
    def setUp(self):
        super().setUp()
        self.donor = self.make_donor()
        self.other = self.make_donor("Other Kitchen")
        self.make_listing(self.donor)
        self.make_listing(self.other)
        self.make_listing(self.other)
        self.ngo = self.make_ngo()
        services.create_admin("boss@t.test", ADMIN_PASSWORD)

    def test_api_requires_login(self):
        self.assertEqual(self.app.test_client().get("/api/v1/analytics").status_code, 401)

    def test_each_role_gets_its_own_shape(self):
        donor = self.api_client(self.donor.email).get("/api/v1/analytics").get_json()["data"]
        ngo = self.api_client(self.ngo.email).get("/api/v1/analytics").get_json()["data"]
        admin = self.api_client("boss@t.test", ADMIN_PASSWORD).get("/api/v1/analytics").get_json()["data"]
        self.assertEqual((donor["role"], ngo["role"], admin["role"]), ("Donor", "NGO", "Admin"))
        self.assertEqual(donor["listings"]["total"], 1)
        self.assertNotIn("users", donor)
        self.assertNotIn("users", ngo)
        self.assertEqual(admin["listings"]["total"], 3)

    def test_a_user_cannot_request_someone_elses_numbers(self):
        client = self.api_client(self.donor.email)
        res = client.get(f"/api/v1/analytics?user_id={self.other.id}&role=Admin")
        self.assertEqual(res.get_json()["data"]["listings"]["total"], 1)  # still their own

    def test_pages_render_for_every_role_and_make_no_food_saved_claim(self):
        self.assertEqual(self.app.test_client().get("/analytics").status_code, 302)
        for client in (self.web_client(self.donor.email), self.web_client(self.ngo.email),
                       self.web_client("boss@t.test", ADMIN_PASSWORD)):
            res = client.get("/analytics")
            self.assertEqual(res.status_code, 200)
            html = res.get_data(as_text=True)
            self.assertIn('id="boot"', html)
            self.assertIsNone(re.search(r"\d+\s*(kg|kilograms|meals)\s+saved", html, re.I))
