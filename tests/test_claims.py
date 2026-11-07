"""Claim reliability: simultaneous claims, expiry, withdrawals, pickups."""
import threading

import services
from database import CLAIMED, PENDING, PICKED_UP, DonationListing, User, db
from services import ServiceError
from tests.helpers import AppTestCase


def run_in_threads(app, jobs):
    """Run callables simultaneously (released together by a barrier). Each job
    gets its own app context => its own database session, like a real request."""
    barrier = threading.Barrier(len(jobs))
    results, lock = [], threading.Lock()

    def runner(job):
        with app.app_context():
            barrier.wait(timeout=15)
            try:
                outcome = ("ok", job())
            except ServiceError as err:
                outcome = ("err", err.code)
            except Exception as exc:  # anything else is a bug
                outcome = ("crash", repr(exc))
            finally:
                db.session.remove()
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=runner, args=(job,)) for job in jobs]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    return results


class SimultaneousClaims(AppTestCase):
    def test_eight_ngos_claim_at_once_exactly_one_wins(self):
        listing = self.make_listing(self.make_donor())
        listing_id = listing.id  # plain ints only inside worker threads
        ngo_ids = [self.make_ngo().id for _ in range(8)]

        def claimer(ngo_id):
            def job():
                ngo = db.session.get(User, ngo_id)
                return services.claim_listing(ngo, listing_id).claimed_by_ngo_id
            return job

        results = run_in_threads(self.app, [claimer(i) for i in ngo_ids])
        self.assertEqual([r for r in results if r[0] == "crash"], [])
        winners = [r[1] for r in results if r[0] == "ok"]
        losers = [r[1] for r in results if r[0] == "err"]
        self.assertEqual(len(winners), 1, results)
        self.assertEqual(losers, ["already_claimed"] * 7)
        db.session.expire_all()
        stored = db.session.get(DonationListing, listing_id)
        self.assertEqual(stored.status, CLAIMED)
        self.assertEqual(stored.claimed_by_ngo_id, winners[0])

    def test_simultaneous_claims_over_http_one_200_rest_409(self):
        listing_id = self.make_listing(self.make_donor()).id
        emails = [self.make_ngo().email for _ in range(5)]
        clients = [self.api_client(e) for e in emails]

        def claimer(client):
            def job():
                return self.post(client, f"/listings/{listing_id}/claim").status_code
            return job

        results = run_in_threads(self.app, [claimer(c) for c in clients])
        codes = sorted(r[1] for r in results if r[0] == "ok")
        self.assertEqual(codes, [200, 409, 409, 409, 409], results)

    def test_claim_racing_withdraw_has_exactly_one_winner(self):
        donor = self.make_donor()
        listing_id = self.make_listing(donor).id
        ngo_id = self.make_ngo().id
        donor_id = donor.id

        def claim():
            return services.claim_listing(db.session.get(User, ngo_id), listing_id).id

        def withdraw():
            services.withdraw_listing(db.session.get(User, donor_id), listing_id)
            return listing_id

        results = run_in_threads(self.app, [claim, withdraw])
        self.assertEqual([r for r in results if r[0] == "crash"], [])
        self.assertEqual(len([r for r in results if r[0] == "ok"]), 1, results)
        self.assertIn(self.status_of(listing_id), (CLAIMED, "Withdrawn"))


class ClaimRules(AppTestCase):
    def setUp(self):
        super().setUp()
        self.donor = self.make_donor()
        self.ngo = self.make_ngo()
        self.listing = self.make_listing(self.donor)
        self.lid = self.listing.id  # keep a plain int: the row may be deleted later

    def test_claim_succeeds_and_records_the_claimant(self):
        claimed = services.claim_listing(self.ngo, self.lid)
        self.assertEqual(claimed.status, CLAIMED)
        self.assertEqual(claimed.claimed_by_ngo_id, self.ngo.id)

    def test_second_ngo_is_told_too_late(self):
        services.claim_listing(self.ngo, self.lid)
        other = self.make_ngo()
        with self.assertRaises(ServiceError) as ctx:
            services.claim_listing(other, self.lid)
        self.assertEqual((ctx.exception.code, ctx.exception.status), ("already_claimed", 409))

    def test_same_ngo_claiming_twice_gets_a_specific_error(self):
        services.claim_listing(self.ngo, self.lid)
        with self.assertRaises(ServiceError) as ctx:
            services.claim_listing(self.ngo, self.lid)
        self.assertEqual(ctx.exception.code, "already_claimed_by_you")

    def test_expired_listing_cannot_be_claimed_on_the_server(self):
        self.expire(self.lid)
        with self.assertRaises(ServiceError) as ctx:
            services.claim_listing(self.ngo, self.lid)
        self.assertEqual((ctx.exception.code, ctx.exception.status), ("expired", 410))
        self.assertEqual(self.status_of(self.lid), PENDING)

    def test_expired_listing_cannot_be_claimed_over_http(self):
        self.expire(self.lid)
        client = self.api_client(self.ngo.email)
        res = self.post(client, f"/listings/{self.lid}/claim")
        self.assertEqual(res.status_code, 410)
        self.assertEqual(res.get_json()["error"]["code"], "expired")

    def test_expired_listings_are_hidden_from_nearby(self):
        self.expire(self.lid)
        self.assertEqual(services.nearby_listings(self.ngo, 50), [])
        self.assertEqual(services.get_stats()["active"], 0)

    def test_unknown_listing_is_404(self):
        with self.assertRaises(ServiceError) as ctx:
            services.claim_listing(self.ngo, 99999)
        self.assertEqual(ctx.exception.status, 404)

    def test_donors_cannot_claim(self):
        with self.assertRaises(ServiceError) as ctx:
            services.claim_listing(self.donor, self.lid)
        self.assertEqual(ctx.exception.status, 403)
        self.assertEqual(self.status_of(self.lid), PENDING)


class Withdrawals(AppTestCase):
    def setUp(self):
        super().setUp()
        self.donor = self.make_donor()
        self.ngo = self.make_ngo()
        self.listing = self.make_listing(self.donor)
        self.lid = self.listing.id  # keep a plain int: the row may be deleted later

    def test_donor_can_withdraw_a_pending_listing(self):
        services.withdraw_listing(self.donor, self.lid)
        self.assertEqual(self.status_of(self.lid), "Withdrawn")

    def test_cannot_withdraw_after_it_was_claimed(self):
        services.claim_listing(self.ngo, self.lid)
        with self.assertRaises(ServiceError) as ctx:
            services.withdraw_listing(self.donor, self.lid)
        self.assertEqual((ctx.exception.code, ctx.exception.status), ("invalid_state", 409))
        self.assertEqual(self.status_of(self.lid), CLAIMED)

    def test_another_donor_cannot_withdraw_it(self):
        other = self.make_donor("Other Kitchen")
        with self.assertRaises(ServiceError) as ctx:
            services.withdraw_listing(other, self.lid)
        self.assertEqual(ctx.exception.status, 404)
        self.assertEqual(self.status_of(self.lid), PENDING)

    def test_withdrawn_listing_can_no_longer_be_claimed(self):
        services.withdraw_listing(self.donor, self.lid)
        with self.assertRaises(ServiceError) as ctx:
            services.claim_listing(self.ngo, self.lid)
        self.assertEqual(ctx.exception.status, 404)

    def test_withdraw_over_http(self):
        client = self.api_client(self.donor.email)
        res = client.delete(f"/api/v1/listings/{self.lid}",
                            headers={"X-CSRFToken": client.token})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.status_of(self.lid), "Withdrawn")


class PickupCompletion(AppTestCase):
    def setUp(self):
        super().setUp()
        self.donor = self.make_donor()
        self.ngo = self.make_ngo()
        self.listing = self.make_listing(self.donor)
        self.lid = self.listing.id  # keep a plain int: the row may be deleted later
        services.claim_listing(self.ngo, self.lid)

    def test_claimant_completes_the_pickup(self):
        done = services.mark_picked_up(self.ngo, self.lid)
        self.assertEqual(done.status, PICKED_UP)

    def test_pickup_cannot_be_completed_twice(self):
        services.mark_picked_up(self.ngo, self.lid)
        with self.assertRaises(ServiceError) as ctx:
            services.mark_picked_up(self.ngo, self.lid)
        self.assertEqual((ctx.exception.code, ctx.exception.status), ("invalid_state", 409))

    def test_only_the_claiming_ngo_can_complete_it(self):
        other = self.make_ngo()
        with self.assertRaises(ServiceError) as ctx:
            services.mark_picked_up(other, self.lid)
        self.assertEqual(ctx.exception.status, 404)
        self.assertEqual(self.status_of(self.lid), CLAIMED)

    def test_a_pending_listing_cannot_be_marked_picked_up(self):
        fresh = self.make_listing(self.donor)
        with self.assertRaises(ServiceError):
            services.mark_picked_up(self.ngo, fresh.id)
        self.assertEqual(self.status_of(fresh.id), PENDING)

    def test_picked_up_listing_cannot_be_withdrawn_or_reclaimed(self):
        services.mark_picked_up(self.ngo, self.lid)
        with self.assertRaises(ServiceError) as ctx:
            services.withdraw_listing(self.donor, self.lid)
        self.assertEqual(ctx.exception.status, 409)
        with self.assertRaises(ServiceError) as ctx:
            services.claim_listing(self.make_ngo(), self.lid)
        self.assertEqual(ctx.exception.code, "already_claimed")

    def test_pickup_over_http(self):
        client = self.api_client(self.ngo.email)
        res = self.post(client, f"/listings/{self.lid}/pickup")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["data"]["status"], PICKED_UP)
