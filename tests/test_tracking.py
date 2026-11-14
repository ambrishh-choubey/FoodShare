"""Live donation tracking: stages, lifecycle timestamps and who may see them."""
from datetime import timedelta

import services
from database import DonationListing, db, utcnow
from tests.helpers import ADMIN_PASSWORD, AppTestCase


def row(listing_id, viewer):
    db.session.expire_all()
    return db.session.get(DonationListing, listing_id).to_dict(viewer)


class Stages(AppTestCase):
    def setUp(self):
        super().setUp()
        self.donor = self.make_donor()
        self.ngo = self.make_ngo()

    def test_available_then_claimed_then_completed_with_timestamps(self):
        lid = self.make_listing(self.donor).id
        d = row(lid, self.donor)
        self.assertEqual((d["stage"], d["stage_label"]), ("available", "Available"))
        self.assertIsNone(d["claimed_at"])
        services.claim_listing(self.ngo, lid)
        d = row(lid, self.donor)
        self.assertEqual(d["stage"], "pickup_pending")
        self.assertIsNotNone(d["claimed_at"])
        self.assertIsNone(d["picked_up_at"])
        services.mark_picked_up(self.ngo, lid)
        d = row(lid, self.donor)
        self.assertEqual(d["stage"], "completed")
        self.assertIsNotNone(d["picked_up_at"])
        self.assertLessEqual(d["created_at"], d["claimed_at"])
        self.assertLessEqual(d["claimed_at"], d["picked_up_at"])

    def test_withdrawn_stage_and_time(self):
        lid = self.make_listing(self.donor).id
        services.withdraw_listing(self.donor, lid)
        d = row(lid, self.donor)
        self.assertEqual(d["stage"], "withdrawn")
        self.assertIsNotNone(d["withdrawn_at"])

    def test_expired_stage(self):
        lid = self.make_listing(self.donor).id
        self.expire(lid)
        self.assertEqual(row(lid, self.donor)["stage"], "expired")


class TrackingAccess(AppTestCase):
    def setUp(self):
        super().setUp()
        self.donor = self.make_donor()
        self.other_donor = self.make_donor("Other Kitchen")
        self.ngo = self.make_ngo()
        self.rival = self.make_ngo()
        services.create_admin("boss@t.test", ADMIN_PASSWORD)
        self.lid = self.make_listing(self.donor).id
        services.claim_listing(self.ngo, self.lid)

    def test_lifecycle_times_only_for_donor_claiming_ngo_and_admin(self):
        for viewer in (self.donor, self.ngo):
            self.assertIn("claimed_at", row(self.lid, viewer))
        admin = db.session.query(type(self.donor)).filter_by(email="boss@t.test").one()
        self.assertIn("claimed_at", row(self.lid, admin))
        for viewer in (self.rival, self.other_donor):
            self.assertNotIn("claimed_at", row(self.lid, viewer))

    def test_other_users_cannot_open_or_list_the_donation(self):
        for email in (self.other_donor.email, self.rival.email):
            client = self.api_client(email)
            self.assertEqual(client.get(f"/api/v1/listings/{self.lid}").status_code, 404)
            ids = [l["id"] for l in client.get("/api/v1/listings?scope=mine").get_json()["data"]]
            self.assertNotIn(self.lid, ids)

    def test_donor_and_claiming_ngo_see_it_in_their_own_list(self):
        for email in (self.donor.email, self.ngo.email):
            data = self.api_client(email).get("/api/v1/listings?scope=mine").get_json()["data"]
            self.assertEqual([l["id"] for l in data], [self.lid])
            self.assertEqual(data[0]["stage"], "pickup_pending")

    def test_rival_ngo_cannot_complete_someone_elses_pickup(self):
        with self.assertRaises(services.ServiceError) as ctx:
            services.mark_picked_up(self.rival, self.lid)
        self.assertEqual(ctx.exception.status, 404)
