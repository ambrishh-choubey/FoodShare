"""Deadline + status notifications: created once, stored, read/unread, private."""
from datetime import timedelta

from sqlalchemy.exc import IntegrityError

import notifications
import services
from database import DonationListing, Notification, db, utcnow
from tests.helpers import ADMIN_PASSWORD, AppTestCase

FAR = dict(lat=28.61, lng=77.21)  # Delhi: well outside 50 km of the Bengaluru donor


class NotificationCase(AppTestCase):
    def of(self, user, kind=None):
        query = Notification.query.filter_by(user_id=user.id)
        if kind:
            query = query.filter_by(kind=kind)
        return query.all()

    def expires_in(self, listing_id, minutes=None, days=None):
        delta = timedelta(minutes=minutes or 0, days=days or 0)
        db.session.query(DonationListing).filter_by(id=listing_id).update(
            {DonationListing.expires_at: utcnow().replace(microsecond=0) + delta})
        db.session.commit()

    def post(self, client, path):
        return client.post(f"/api/v1{path}", headers={"X-CSRFToken": client.token})


class StatusEvents(NotificationCase):
    def setUp(self):
        super().setUp()
        self.donor = self.make_donor()
        self.ngo = self.make_ngo("Green Hands")
        self.lid = self.make_listing(self.donor).id

    def test_claim_notifies_the_donor_once_and_it_starts_unread(self):
        services.claim_listing(self.ngo, self.lid)
        notes = self.of(self.donor)
        self.assertEqual([n.kind for n in notes], ["claimed"])
        self.assertIsNone(notes[0].read_at)
        self.assertIn("Green Hands", notes[0].message)
        self.assertEqual(self.of(self.ngo), [])  # the NGO is not notified about its own click

    def test_pickup_notifies_the_donor(self):
        services.claim_listing(self.ngo, self.lid)
        services.mark_picked_up(self.ngo, self.lid)
        self.assertEqual(sorted(n.kind for n in self.of(self.donor)), ["claimed", "picked_up"])

    def test_the_database_itself_rejects_a_duplicate_event(self):
        services.claim_listing(self.ngo, self.lid)
        db.session.add(Notification(user_id=self.donor.id, kind="claimed", listing_id=self.lid,
                                    message="again", dedupe_key=f"claimed:{self.lid}"))
        with self.assertRaises(IntegrityError):
            db.session.commit()
        db.session.rollback()


class DeadlineScan(NotificationCase):
    def setUp(self):
        super().setUp()
        self.donor = self.make_donor()
        self.near = self.make_ngo("Near NGO")
        self.far = self.make_ngo("Far NGO", **FAR)
        self.unapproved = self.make_ngo("Pending NGO", approved=False)
        self.lid = self.make_listing(self.donor, hours=4).id

    def test_nothing_happens_when_the_deadline_is_far_away(self):
        self.assertEqual(notifications.run_deadline_scan(), 0)

    def test_expiring_food_notifies_only_approved_nearby_ngos(self):
        self.expires_in(self.lid, minutes=30)
        notifications.run_deadline_scan()
        self.assertEqual(len(self.of(self.near, "expiring")), 1)
        for other in (self.far, self.unapproved, self.donor):
            self.assertEqual(self.of(other), [])

    def test_running_the_scan_again_never_duplicates(self):
        self.expires_in(self.lid, minutes=30)
        self.assertEqual(notifications.run_deadline_scan(), 1)
        self.assertEqual(notifications.run_deadline_scan(), 0)
        self.assertEqual(len(self.of(self.near)), 1)

    def test_claimed_food_near_its_deadline_notifies_only_the_claiming_ngo(self):
        rival = self.make_ngo("Rival NGO")
        services.claim_listing(self.near, self.lid)
        self.expires_in(self.lid, minutes=30)
        notifications.run_deadline_scan()
        self.assertEqual(len(self.of(self.near, "pickup_due")), 1)
        self.assertEqual(self.of(rival), [])

    def test_completed_pickups_do_not_trigger_reminders(self):
        services.claim_listing(self.near, self.lid)
        services.mark_picked_up(self.near, self.lid)
        self.expires_in(self.lid, minutes=30)
        notifications.run_deadline_scan()
        self.assertEqual(self.of(self.near), [])

    def test_unclaimed_expired_donation_notifies_the_donor_once(self):
        self.expire(self.lid)
        notifications.run_deadline_scan()
        notifications.run_deadline_scan()
        self.assertEqual([n.kind for n in self.of(self.donor)], ["expired"])
        self.assertEqual(self.of(self.near), [])

    def test_very_old_deadlines_are_not_announced(self):
        self.expires_in(self.lid, days=-10)
        self.assertEqual(notifications.run_deadline_scan(), 0)


class Privacy(NotificationCase):
    def setUp(self):
        super().setUp()
        self.donor = self.make_donor()
        self.other_donor = self.make_donor("Other Kitchen")
        self.ngo = self.make_ngo()
        services.create_admin("boss@t.test", ADMIN_PASSWORD)
        self.l1 = self.make_listing(self.donor).id
        self.l2 = self.make_listing(self.other_donor).id
        services.claim_listing(self.ngo, self.l1)
        services.claim_listing(self.ngo, self.l2)
        self.mine = self.of(self.donor)[0].id
        self.theirs = self.of(self.other_donor)[0].id

    def test_login_is_required(self):
        self.assertEqual(self.app.test_client().get("/api/v1/notifications").status_code, 401)

    def test_each_user_only_sees_their_own(self):
        client = self.api_client(self.donor.email)
        body = client.get("/api/v1/notifications").get_json()
        self.assertEqual([n["id"] for n in body["data"]], [self.mine])
        self.assertEqual(body["meta"]["unread"], 1)
        self.assertEqual(self.api_client(self.ngo.email).get("/api/v1/notifications").get_json()["data"], [])

    def test_admin_has_no_notification_inbox(self):
        client = self.api_client("boss@t.test", ADMIN_PASSWORD)
        self.assertEqual(client.get("/api/v1/notifications").status_code, 403)

    def test_cannot_mark_someone_elses_notification_as_read(self):
        client = self.api_client(self.donor.email)
        self.assertEqual(self.post(client, f"/notifications/{self.theirs}/read").status_code, 404)
        db.session.expire_all()
        self.assertIsNone(db.session.get(Notification, self.theirs).read_at)

    def test_mark_one_read_updates_the_unread_count(self):
        client = self.api_client(self.donor.email)
        self.assertEqual(self.post(client, f"/notifications/{self.mine}/read").status_code, 200)
        self.assertEqual(self.post(client, f"/notifications/{self.mine}/read").status_code, 200)  # idempotent
        body = client.get("/api/v1/notifications").get_json()
        self.assertTrue(body["data"][0]["read"])
        self.assertEqual(body["meta"]["unread"], 0)

    def test_mark_all_read_only_touches_my_notifications(self):
        client = self.api_client(self.donor.email)
        self.assertEqual(self.post(client, "/notifications/read-all").status_code, 200)
        db.session.expire_all()
        self.assertIsNotNone(db.session.get(Notification, self.mine).read_at)
        self.assertIsNone(db.session.get(Notification, self.theirs).read_at)
