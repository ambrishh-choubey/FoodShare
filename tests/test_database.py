"""The database itself must reject invalid states (not just the app code)."""
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

import services
from database import DonationListing, db
from tests.helpers import AppTestCase


class DatabaseConstraints(AppTestCase):
    def setUp(self):
        super().setUp()
        self.donor = self.make_donor()
        self.ngo = self.make_ngo()
        self.listing = self.make_listing(self.donor)

    def assert_rejected(self, sql, **params):
        with self.assertRaises(IntegrityError):
            db.session.execute(text(sql), params)
            db.session.commit()
        db.session.rollback()

    def test_invalid_status_is_rejected(self):
        self.assert_rejected("UPDATE donation_listings SET status='Bogus' WHERE id=:i", i=self.listing.id)

    def test_pending_listing_cannot_have_a_claimant(self):
        self.assert_rejected("UPDATE donation_listings SET claimed_by_ngo_id=:n WHERE id=:i",
                             n=self.ngo.id, i=self.listing.id)

    def test_claimed_listing_must_have_a_claimant(self):
        self.assert_rejected("UPDATE donation_listings SET status='Claimed' WHERE id=:i", i=self.listing.id)

    def test_claimant_must_be_a_real_user(self):
        self.assert_rejected(
            "UPDATE donation_listings SET status='Claimed', claimed_by_ngo_id=99999 WHERE id=:i",
            i=self.listing.id)

    def test_donor_must_be_a_real_user(self):
        self.assert_rejected(
            "INSERT INTO donation_listings (donor_id, food_type, quantity, expiry_window, status, created_at, expires_at) "
            "VALUES (99999, 'x', '1', 4, 'Pending', '2026-01-01', '2026-01-02')")

    def test_expiry_window_must_be_between_1_and_168(self):
        self.assert_rejected("UPDATE donation_listings SET expiry_window=0 WHERE id=:i", i=self.listing.id)
        self.assert_rejected("UPDATE donation_listings SET expiry_window=500 WHERE id=:i", i=self.listing.id)

    def test_invalid_role_is_rejected(self):
        self.assert_rejected("UPDATE users SET role='Hacker' WHERE id=:i", i=self.donor.id)

    def test_invalid_coordinates_are_rejected(self):
        self.assert_rejected("UPDATE users SET latitude=123 WHERE id=:i", i=self.donor.id)

    def test_model_rejects_invalid_status_before_hitting_the_database(self):
        with self.assertRaises(ValueError):
            DonationListing(donor_id=self.donor.id, food_type="x", quantity="1",
                            expiry_window=4, status="Bogus")

    def test_service_validation_of_listing_input(self):
        for bad in (0, 169, "abc", None):
            with self.assertRaises(services.ServiceError):
                services.create_listing(self.donor, "Rice", "5 kg", bad)
        with self.assertRaises(services.ServiceError):
            services.create_listing(self.ngo, "Rice", "5 kg", 4)  # NGOs can't donate
