"""Database models: User and DonationListing.

Integrity rules are enforced by the database itself (CHECK constraints and
foreign keys), not only by application code:
  * role / status must be one of the allowed values
  * a Pending listing has no claimant; Claimed / Picked_Up listings always do
  * expiry window is 1-168 hours, coordinates are valid
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import validates
from werkzeug.security import check_password_hash, generate_password_hash

from .core import db

DONOR, NGO, ADMIN = "Donor", "NGO", "Admin"
ROLES = (DONOR, NGO, ADMIN)
PENDING, CLAIMED, PICKED_UP, WITHDRAWN = "Pending", "Claimed", "Picked_Up", "Withdrawn"
STATUSES = (PENDING, CLAIMED, PICKED_UP, WITHDRAWN)
DEFAULT_LAT, DEFAULT_LNG = 12.9716, 77.5946  # Bengaluru

# Before a claim, NGOs only see the donor's AREA: coordinates rounded to
# 2 decimals (~1.1 km grid) plus a circle that is guaranteed to contain the
# real point (worst case rounding error is ~0.8 km).
APPROX_DECIMALS = 2
APPROX_RADIUS_M = 800


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso(dt):
    return dt.isoformat(timespec="seconds") + "Z" if dt else None


def approx_coord(value):
    return round(value, APPROX_DECIMALS)


class User(db.Model):
    __tablename__ = "users"
    __table_args__ = (
        db.CheckConstraint("role IN ('Donor', 'NGO', 'Admin')", name="ck_users_role"),
        db.CheckConstraint("latitude BETWEEN -90 AND 90", name="ck_users_latitude"),
        db.CheckConstraint("longitude BETWEEN -180 AND 180", name="ck_users_longitude"),
    )
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(10), nullable=False)  # Donor, NGO, Admin
    email = db.Column(db.String(160), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    latitude = db.Column(db.Float, nullable=False, default=DEFAULT_LAT)
    longitude = db.Column(db.Float, nullable=False, default=DEFAULT_LNG)
    # Exact pickup address (optional). Only shown to the NGO that claimed a listing.
    address = db.Column(db.String(255), nullable=True)

    # NGOs start unapproved and need an admin before they can claim. Donors/admins: True.
    is_approved = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())


    def set_password(self, password):
        # Werkzeug: salted scrypt (or pbkdf2:sha256 where scrypt is unavailable)
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def to_dict(self):
        """The user's OWN profile (returned to themselves and to admins)."""
        return {"id": self.id, "name": self.name, "role": self.role,
                "email": self.email, "latitude": self.latitude,
                "longitude": self.longitude, "address": self.address,
                 "is_approved": self.is_approved}


class DonationListing(db.Model):
    __tablename__ = "donation_listings"
    __table_args__ = (
        db.CheckConstraint("status IN ('Pending', 'Claimed', 'Picked_Up', 'Withdrawn')", name="ck_listing_status"),
        db.CheckConstraint(
            "(status IN ('Pending', 'Withdrawn') AND claimed_by_ngo_id IS NULL) OR "
            "(status IN ('Claimed', 'Picked_Up') AND claimed_by_ngo_id IS NOT NULL)",
            name="ck_listing_claim_consistency"),
        db.CheckConstraint("expiry_window BETWEEN 1 AND 168", name="ck_listing_expiry_window"),
    )
    id = db.Column(db.Integer, primary_key=True)
    donor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    food_type = db.Column(db.String(160), nullable=False)
    quantity = db.Column(db.String(80), nullable=False)
    expiry_window = db.Column(db.Integer, nullable=False)  # hours from creation
    status = db.Column(db.String(12), nullable=False, default=PENDING, index=True)
    claimed_by_ngo_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    # Stored (not computed) so a claim can check expiry inside one atomic UPDATE.
    expires_at = db.Column(db.DateTime, nullable=False, index=True)

    donor = db.relationship("User", foreign_keys=[donor_id])
    claimed_by = db.relationship("User", foreign_keys=[claimed_by_ngo_id])

    def __init__(self, **kwargs):
        kwargs.setdefault("created_at", utcnow())
        if "expires_at" not in kwargs and "expiry_window" in kwargs:
            kwargs["expires_at"] = kwargs["created_at"] + timedelta(hours=kwargs["expiry_window"])
        super().__init__(**kwargs)

    @validates("status")
    def _validate_status(self, _key, value):
        if value not in STATUSES:
            raise ValueError(f"Invalid listing status: {value!r}")
        return value

    @property
    def is_expired(self):
        return self.status == PENDING and utcnow() >= self.expires_at

    @property
    def hours_left(self):
        return max(0.0, (self.expires_at - utcnow()).total_seconds() / 3600)

    @property
    def approx_location(self):
        return approx_coord(self.donor.latitude), approx_coord(self.donor.longitude)

    def can_view_exact(self, viewer):
        """Exact location / contact only for: the donor, the NGO that claimed
        it, and admins. Everyone else gets the approximate area."""
        if viewer is None:
            return False
        return (viewer.role == ADMIN
                or viewer.id == self.donor_id
                or (self.claimed_by_ngo_id is not None and viewer.id == self.claimed_by_ngo_id))

    def to_dict(self, viewer=None, distance_km=None):
        donor = {"name": self.donor.name}
        if self.can_view_exact(viewer):
            donor.update(id=self.donor.id, latitude=self.donor.latitude,
                         longitude=self.donor.longitude, location_precision="exact",
                         email=self.donor.email, address=self.donor.address)
        else:
            lat, lng = self.approx_location
            donor.update(latitude=lat, longitude=lng, location_precision="approximate",
                         approximate_radius_m=APPROX_RADIUS_M)
        claimed = None
        if self.claimed_by:
            claimed = {"id": self.claimed_by.id, "name": self.claimed_by.name}
        data = {
            "id": self.id,
            "food_type": self.food_type,
            "quantity": self.quantity,
            "expiry_window_hours": self.expiry_window,
            "status": self.status,
            "created_at": iso(self.created_at),
            "expires_at": iso(self.expires_at),
            "hours_left": round(self.hours_left, 2),
            "is_expired": self.is_expired,
            "donor": donor,
            "claimed_by": claimed,
        }
        if distance_km is not None:
            data["distance_km"] = round(distance_km, 1)
        return data

class LoginAttempt(db.Model):
    """One failed login, used by throttle.py for rate limiting."""
    __tablename__ = "login_attempts"
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(200), nullable=False, index=True)  # "acct:<email>" or "ip:<addr>"
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)




    