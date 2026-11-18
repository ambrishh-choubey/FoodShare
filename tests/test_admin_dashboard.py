"""Admin dashboard: filters, pagination, activity feed, admin-only access."""
from datetime import timedelta

import services
from database import ADMIN, DonationListing, User, db, utcnow
from services import ServiceError
from tests.helpers import ADMIN_PASSWORD, AppTestCase


class DashboardCase(AppTestCase):
    def setUp(self):
        super().setUp()
        self.admin = services.create_admin("boss@t.test", ADMIN_PASSWORD)
        self.donor = self.make_donor("Cafe Bloom")
        self.ngo = self.make_ngo("Green Hands")
        ids = [self.make_listing(self.donor).id for _ in range(5)]
        self.available, self.expired, self.claimed, self.completed, self.withdrawn = ids
        self.expire(self.expired)
        services.claim_listing(self.ngo, self.claimed)
        services.claim_listing(self.ngo, self.completed)
        services.mark_picked_up(self.ngo, self.completed)
        services.withdraw_listing(self.donor, self.withdrawn)

    def page(self, **args):
        return services.admin_listings_page(self.admin, args)

    def ids(self, page):
        return {l.id for l in page["rows"]}


class Filters(DashboardCase):
    def test_no_filter_shows_everything(self):
        page = self.page()
        self.assertEqual(page["total"], 5)
        self.assertEqual(page["errors"], [])

    def test_each_status_filter_matches_exactly_its_donation(self):
        expected = {"available": self.available, "expired": self.expired,
                    "pickup_pending": self.claimed, "completed": self.completed,
                    "withdrawn": self.withdrawn}
        for status, listing_id in expected.items():
            self.assertEqual(self.ids(self.page(status=status)), {listing_id}, status)

    def test_range_stats_describe_only_the_filtered_donations(self):
        page = self.page(status="completed")
        self.assertEqual((page["range_stats"]["total"], page["range_stats"]["completed"]), (1, 1))

    def test_date_range_uses_the_posted_day_and_includes_the_end_day(self):
        old = utcnow() - timedelta(days=10)
        db.session.query(DonationListing).filter_by(id=self.available).update(
            {DonationListing.created_at: old})
        db.session.commit()
        today = utcnow().date().isoformat()
        self.assertNotIn(self.available, self.ids(self.page(**{"from": today})))
        self.assertEqual(self.ids(self.page(**{"from": old.date().isoformat(),
                                               "to": old.date().isoformat()})), {self.available})
        self.assertEqual(self.page(**{"to": today})["total"], 5)  # end day is included

    def test_bad_input_is_reported_and_ignored(self):
        for args in ({"status": "bogus"}, {"from": "16/11/2026"},
                     {"from": "2026-11-16", "to": "2026-11-01"}):
            page = self.page(**args)
            self.assertEqual(len(page["errors"]), 1, args)
            self.assertEqual(page["total"], 5)  # filters dropped, nothing crashes

    def test_pagination_is_bounded_and_clamped(self):
        for _ in range(20):
            self.make_listing(self.donor)  # 25 in total
        first, second = self.page(page="1"), self.page(page="2")
        self.assertEqual((len(first["rows"]), len(second["rows"]), first["pages"]), (20, 5, 2))
        self.assertEqual(self.page(page="999")["page"], 2)
        self.assertEqual(self.page(page="abc")["page"], 1)
        self.assertFalse(self.ids(first) & self.ids(second))


class Activity(DashboardCase):
    def test_feed_is_newest_first_limited_and_readable(self):
        feed = services.recent_activity(self.admin, limit=50)
        self.assertEqual([e["at"] for e in feed], sorted((e["at"] for e in feed), reverse=True))
        texts = " | ".join(e["text"] for e in feed)
        for needle in ("Cafe Bloom posted", "Green Hands claimed", "Green Hands picked up",
                       "Cafe Bloom withdrew", "expired unclaimed", "New NGO registered: Green Hands"):
            self.assertIn(needle, texts)
        self.assertLessEqual(len(services.recent_activity(self.admin, limit=3)), 3)


class AdminOnly(DashboardCase):
    def test_services_refuse_non_admins(self):
        for user in (self.donor, self.ngo):
            with self.assertRaises(ServiceError) as ctx:
                services.admin_listings_page(user, {})
            self.assertEqual(ctx.exception.status, 403)
            with self.assertRaises(ServiceError):
                services.recent_activity(user)

    def test_admin_page_access(self):
        self.assertEqual(self.app.test_client().get("/admin").status_code, 302)
        self.assertEqual(self.web_client(self.donor.email).get("/admin").status_code, 403)
        self.assertEqual(self.web_client(self.ngo.email).get("/admin").status_code, 403)
        res = self.web_client("boss@t.test", ADMIN_PASSWORD).get("/admin?status=completed")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn("Recent activity", html)
        self.assertIn("1</b> donation", html)

    def test_api_access_and_validation(self):
        self.assertEqual(self.app.test_client().get("/api/v1/admin/listings").status_code, 401)
        self.assertEqual(self.api_client(self.donor.email).get("/api/v1/admin/listings").status_code, 403)
        admin = self.api_client("boss@t.test", ADMIN_PASSWORD)
        body = admin.get("/api/v1/admin/listings?status=expired").get_json()
        self.assertEqual((body["meta"]["total"], body["data"][0]["stage"]), (1, "expired"))
        self.assertEqual(admin.get("/api/v1/admin/listings?from=nonsense").status_code, 400)


class ApprovalStillWorks(AppTestCase):
    def test_admin_can_approve_and_revoke_but_others_cannot(self):
        services.create_admin("boss@t.test", ADMIN_PASSWORD)
        ngo = self.make_ngo("Pending NGO", approved=False)
        donor = self.make_donor()
        admin_client = self.web_client("boss@t.test", ADMIN_PASSWORD)
        token = self.page_token(admin_client, "/admin")
        res = admin_client.post(f"/admin/ngos/{ngo.id}/approve", data={"csrf_token": token})
        self.assertEqual(res.status_code, 302)
        db.session.expire_all()
        self.assertTrue(db.session.get(User, ngo.id).is_approved)
        admin_client.post(f"/admin/ngos/{ngo.id}/revoke", data={"csrf_token": token})
        db.session.expire_all()
        self.assertFalse(db.session.get(User, ngo.id).is_approved)
        other = self.web_client(donor.email)
        res = other.post(f"/admin/ngos/{ngo.id}/approve",
                         data={"csrf_token": self.page_token(other, "/analytics")})
        self.assertEqual(res.status_code, 403)
