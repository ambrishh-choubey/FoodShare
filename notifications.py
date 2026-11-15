"""In-app notifications, stored in the database.

* Event notifications (an NGO claimed / picked up a donation) are created right
  after the status change, from services.py.
* Deadline notifications (expiring soon, pickup due, expired unclaimed) are
  created by run_deadline_scan(), which a SCHEDULER calls every few minutes
  (see scheduler.py and `flask --app app notify-deadlines`). It is never run
  inside a normal web request.
* No duplicates: every notification carries a dedupe_key such as "claimed:42",
  and the database enforces UNIQUE(user_id, dedupe_key). Running the scan twice,
  or from two workers at once, can never create the same notification twice.
* Every query is filtered by user_id, so a user can only ever see or change
  their own notifications.
"""
from datetime import timedelta

from flask import current_app
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from database import (CLAIMED, NGO, PENDING, DonationListing, Notification, User,
                      db, utcnow)

EXPIRY_WARNING_MINUTES = 60   # warn this long before a deadline
NEARBY_RADIUS_KM = 50.0       # which NGOs count as "relevant" for an expiring donation
LOOKBACK_DAYS = 7             # don't announce deadlines that passed long ago
KEEP_READ_DAYS = 30           # read notifications are deleted after this (must be > LOOKBACK_DAYS)


def _when(dt):
    return dt.strftime("%d %b %H:%M") + " UTC"


def _make(item):
    user_id, kind, listing_id, message, key = item
    return Notification(user_id=user_id, kind=kind, listing_id=listing_id,
                        message=message[:255], dedupe_key=key)


def _store(items):
    """Insert notifications that don't exist yet. items = (user_id, kind,
    listing_id, message, dedupe_key). Returns how many were created."""
    unique = {}
    for item in items:
        unique.setdefault((item[0], item[4]), item)
    if not unique:
        return 0
    keys = {key for _, key in unique}
    existing = {(user_id, key) for user_id, key in
                db.session.query(Notification.user_id, Notification.dedupe_key)
                .filter(Notification.dedupe_key.in_(keys))}
    fresh = [item for pair, item in unique.items() if pair not in existing]
    if not fresh:
        return 0
    try:
        db.session.add_all([_make(i) for i in fresh])
        db.session.commit()
        return len(fresh)
    except IntegrityError:  # another worker inserted one of them a moment ago
        db.session.rollback()
    created = 0
    for item in fresh:
        try:
            db.session.add(_make(item))
            db.session.commit()
            created += 1
        except IntegrityError:
            db.session.rollback()
    return created


def _safe(fn):
    """A failed notification must never break the donation action that caused it."""
    try:
        fn()
    except Exception:  # noqa: BLE001
        db.session.rollback()
        current_app.logger.exception("Could not create notification")


# ---------------------------------------------------------- event notifications
def on_claimed(listing, ngo):
    _safe(lambda: _store([(
        listing.donor_id, "claimed", listing.id,
        f'{ngo.name} claimed your donation "{listing.food_type}". Pickup is pending.',
        f"claimed:{listing.id}")]))


def on_picked_up(listing, ngo):
    _safe(lambda: _store([(
        listing.donor_id, "picked_up", listing.id,
        f'"{listing.food_type}" was picked up by {ngo.name}. Thank you!',
        f"picked_up:{listing.id}")]))


# --------------------------------------------------------- deadline notifications
def run_deadline_scan(now=None):
    """Create any deadline notifications that are due. Safe to run as often as
    you like. Returns the number of notifications created."""
    from services import haversine_km  # imported here: services imports this module

    now = now or utcnow()
    horizon = now + timedelta(minutes=EXPIRY_WARNING_MINUTES)
    oldest = now - timedelta(days=LOOKBACK_DAYS)
    items = []

    # 1) Available food about to expire -> approved NGOs nearby
    soon = (DonationListing.query.options(joinedload(DonationListing.donor))
            .filter(DonationListing.status == PENDING,
                    DonationListing.expires_at > now,
                    DonationListing.expires_at <= horizon).all())
    if soon:
        ngos = User.query.filter_by(role=NGO, is_approved=True).all()
        for listing in soon:
            lat, lng = listing.approx_location  # same approximate position NGOs already see
            for ngo in ngos:
                if haversine_km(ngo.latitude, ngo.longitude, lat, lng) <= NEARBY_RADIUS_KM:
                    items.append((ngo.id, "expiring", listing.id,
                                  f'"{listing.food_type}" ({listing.quantity}) from {listing.donor.name} '
                                  f'expires at {_when(listing.expires_at)}. Claim it soon.',
                                  f"expiring:{listing.id}"))

    # 2) Claimed food whose collection deadline is close (or just passed) -> the claiming NGO
    due = (DonationListing.query.options(joinedload(DonationListing.donor))
           .filter(DonationListing.status == CLAIMED,
                   DonationListing.expires_at <= horizon,
                   DonationListing.expires_at > oldest).all())
    for listing in due:
        items.append((listing.claimed_by_ngo_id, "pickup_due", listing.id,
                      f'Collect "{listing.food_type}" from {listing.donor.name} by '
                      f'{_when(listing.expires_at)}.', f"pickup_due:{listing.id}"))

    # 3) Donations nobody claimed in time -> the donor
    expired = (DonationListing.query
               .filter(DonationListing.status == PENDING,
                       DonationListing.expires_at <= now,
                       DonationListing.expires_at > oldest).all())
    for listing in expired:
        items.append((listing.donor_id, "expired", listing.id,
                      f'Your donation "{listing.food_type}" expired without being claimed.',
                      f"expired:{listing.id}"))

    created = _store(items)
    _purge_old_read(now)
    return created


def _purge_old_read(now):
    try:
        (Notification.query
         .filter(Notification.read_at.isnot(None),
                 Notification.read_at < now - timedelta(days=KEEP_READ_DAYS))
         .delete(synchronize_session=False))
        db.session.commit()
    except Exception:  # noqa: BLE001
        db.session.rollback()


# ----------------------------------------------------------- reading (per user)
def list_for(user, unread_only=False, limit=20):
    query = Notification.query.filter_by(user_id=user.id)
    if unread_only:
        query = query.filter(Notification.read_at.is_(None))
    return query.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit).all()


def unread_count(user):
    return (db.session.query(func.count(Notification.id))
            .filter(Notification.user_id == user.id, Notification.read_at.is_(None)).scalar() or 0)


def mark_read(user, notification_id):
    """True if it exists AND belongs to `user` (already-read counts as success);
    False otherwise, which the API reports as 404 so ids can't be probed."""
    db.session.query(Notification).filter(
        Notification.id == notification_id, Notification.user_id == user.id,
        Notification.read_at.is_(None)).update({Notification.read_at: utcnow()},
                                               synchronize_session=False)
    db.session.commit()
    return db.session.query(Notification.id).filter_by(id=notification_id, user_id=user.id).first() is not None


def mark_all_read(user):
    count = db.session.query(Notification).filter(
        Notification.user_id == user.id, Notification.read_at.is_(None)
    ).update({Notification.read_at: utcnow()}, synchronize_session=False)
    db.session.commit()
    return count
