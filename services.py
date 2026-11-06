"""Business logic shared by the web pages and the JSON API.

Every state change on a listing (claim, withdraw, pick up) is ONE atomic
conditional SQL statement whose WHERE clause carries the rules (status,
ownership, expiry). The database decides the winner of a race, so two NGOs can
never claim the same donation no matter how the requests interleave, on SQLite,
MySQL or PostgreSQL alike.
"""
import math
import time

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import joinedload
import throttle
from database import (ADMIN, CLAIMED, DEFAULT_LAT, DEFAULT_LNG, DONOR, NGO,
                      PENDING, PICKED_UP, DonationListing, User, db, utcnow)

WEAK_PASSWORDS = {"admin123", "password", "password1", "password123", "12345678",
                  "123456789", "1234567890", "admin", "administrator", "qwerty123",
                  "letmein123", "demo1234", "foodshare", "foodshare123"}
MIN_PASSWORD = 8
MIN_ADMIN_PASSWORD = 12
MAX_PASSWORD = 128  # hashing is deliberately slow; cap input size


class ServiceError(Exception):
    def __init__(self, message, code="bad_request", status=400, retry_after=None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status
        self.retry_after = retry_after  # seconds, for HTTP 429

# ----------------------------------------------------------------- helpers
def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def parse_coord(value, default, low, high):
    try:
        v = float(value)
        return v if low <= v <= high else default
    except (TypeError, ValueError):
        return default


def parse_radius(value, default=50.0):
    try:
        radius = float(value)
    except (TypeError, ValueError):
        radius = default
    if math.isnan(radius):
        radius = default
    return min(max(radius, 1.0), 500.0)


def _require_role(user, role, action):
    if user is None or user.role != role:
        raise ServiceError(f"Only {role} accounts can {action}.", "forbidden", 403)


def _check_email(email):
    domain = email.rsplit("@", 1)[-1]
    if len(email) > 160 or "@" not in email or "." not in domain or " " in email:
        raise ServiceError("Please enter a valid email address.", "validation_error")


def _check_password(password, email, minimum):
    if len(password) < minimum:
        raise ServiceError(f"Password must be at least {minimum} characters.", "validation_error")
    if len(password) > MAX_PASSWORD:
        raise ServiceError(f"Password must be at most {MAX_PASSWORD} characters.", "validation_error")
    if password.lower() in WEAK_PASSWORDS or password.lower() == email.split("@")[0]:
        raise ServiceError("That password is too easy to guess. Choose another.", "weak_password")


# -------------------------------------------------------------------- users
def register_user(name, email, password, role, lat=None, lng=None, address=None):
    """Public sign-up. Only Donor and NGO accounts can be self-registered."""
    name = (name or "").strip()
    email = (email or "").strip().lower()
    password = password or ""
    address = (address or "").strip() or None
    if not name or not email or not password:
        raise ServiceError("Name, email and password are required.", "validation_error")
    if len(name) > 120:
        raise ServiceError("Name is too long (max 120 characters).", "validation_error")
    if address and len(address) > 255:
        raise ServiceError("Address is too long (max 255 characters).", "validation_error")
    _check_email(email)
    if role not in (DONOR, NGO):
        raise ServiceError("Role must be 'Donor' or 'NGO'.", "validation_error")
    _check_password(password, email, MIN_PASSWORD)
    if User.query.filter_by(email=email).first():
        raise ServiceError("That email is already registered.", "email_taken", 409)

    user = User(name=name, email=email, role=role,
                latitude=parse_coord(lat, DEFAULT_LAT, -90, 90),
                longitude=parse_coord(lng, DEFAULT_LNG, -180, 180),
                address=address if role == DONOR else None,
                is_approved=(role != NGO))  # NGOs wait for an admin
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user


def create_admin(email, password, name="Platform Admin"):
    """Create an administrator. Used ONLY by `flask create-admin` - there is no
    web or API route that can create an admin and no default admin password."""
    email = (email or "").strip().lower()
    password = password or ""
    name = (name or "").strip() or "Platform Admin"
    _check_email(email)
    _check_password(password, email, MIN_ADMIN_PASSWORD)
    if User.query.filter_by(email=email).first():
        raise ServiceError("That email is already registered.", "email_taken", 409)
    admin = User(name=name, email=email, role=ADMIN,
                 latitude=DEFAULT_LAT, longitude=DEFAULT_LNG)
    admin.set_password(password)
    db.session.add(admin)
    db.session.commit()
    return admin


def authenticate(email, password, ip=None):
    email = (email or "").strip().lower()
    password = password or ""
    # Reject, never truncate: a 130-char guess must not match a 128-char password.
    if len(password) > MAX_PASSWORD:
        raise ServiceError(f"Password must be at most {MAX_PASSWORD} characters.",
                           "validation_error")
    try:
        throttle.check(email, ip)
    except throttle.Throttled as limited:
        minutes = max(1, math.ceil(limited.retry_after / 60))
        raise ServiceError(f"Too many failed login attempts. Try again in {minutes} minute(s).",
                           "rate_limited", 429, retry_after=limited.retry_after)
    user = User.query.filter_by(email=email).first()
    if not user or not user.check_password(password):
        throttle.record_failure(email, ip)  # also counts unknown emails (no enumeration)
        raise ServiceError("Invalid email or password.", "invalid_credentials", 401)
    throttle.clear_account(email)
    return user


# ------------------------------------------------------------ NGO approval
def _require_approved(ngo):
    if not ngo.is_approved:
        raise ServiceError("Your NGO account is awaiting admin approval. "
                           "You can browse and claim food once it is approved.",
                           "not_approved", 403)


def pending_ngos():
    return User.query.filter_by(role=NGO, is_approved=False).order_by(User.id).all()


def set_ngo_approval(admin, ngo_id, approved):
    _require_role(admin, ADMIN, "approve NGOs")
    ngo = db.session.get(User, ngo_id)
    if ngo is None or ngo.role != NGO:
        raise ServiceError("NGO not found.", "not_found", 404)
    ngo.is_approved = bool(approved)
    db.session.commit()
    return ngo
# ---------------------------------------------------------------- listings
def create_listing(donor, food_type, quantity, expiry_window):
    _require_role(donor, DONOR, "post food listings")
    food_type = (food_type or "").strip()
    quantity = (quantity or "").strip()
    try:
        expiry = int(expiry_window)
    except (TypeError, ValueError):
        expiry = 0
    if not food_type or not quantity:
        raise ServiceError("Food type and quantity are required.", "validation_error")
    if len(food_type) > 160 or len(quantity) > 80:
        raise ServiceError("Food type (max 160) or quantity (max 80) is too long.",
                           "validation_error")
    if not 1 <= expiry <= 168:
        raise ServiceError("Expiry window must be between 1 and 168 hours.",
                           "validation_error")
    listing = DonationListing(donor_id=donor.id, food_type=food_type,
                              quantity=quantity, expiry_window=expiry)
    db.session.add(listing)
    db.session.commit()
    return listing


def get_listing(listing_id):
    listing = db.session.get(DonationListing, listing_id)
    if not listing:
        raise ServiceError("Listing not found.", "not_found", 404)
    return listing


def get_visible_listing(viewer, listing_id):
    """A listing the viewer is allowed to see (else 404, never 403, so
    listing ids can't be probed)."""
    listing = get_listing(listing_id)
    allowed = (viewer.role == ADMIN
               or listing.donor_id == viewer.id
               or listing.claimed_by_ngo_id == viewer.id
               or (viewer.role == NGO and listing.status == PENDING and not listing.is_expired))
    if not allowed:
        raise ServiceError("Listing not found.", "not_found", 404)
    return listing


def donor_listings(donor):
    return (DonationListing.query.options(joinedload(DonationListing.claimed_by),
                                          joinedload(DonationListing.donor))
            .filter_by(donor_id=donor.id)
            .order_by(DonationListing.created_at.desc()).all())


def claimed_listings(ngo):
    return (DonationListing.query.options(joinedload(DonationListing.donor),
                                          joinedload(DonationListing.claimed_by))
            .filter_by(claimed_by_ngo_id=ngo.id)
            .order_by(DonationListing.created_at.desc()).all())


def all_listings(status=None):
    query = DonationListing.query.options(joinedload(DonationListing.donor),
                                          joinedload(DonationListing.claimed_by))
    if status:
        query = query.filter_by(status=status)
    return query.order_by(DonationListing.created_at.desc()).all()


def nearby_listings(ngo, radius_km=50.0):
    """Active (pending AND not expired) listings within radius, nearest first.

    Distances use the donor's APPROXIMATE coordinates - the same ones that are
    sent to the browser - so repeated queries can't be used to pin down an
    exact location.
    """
    _require_approved(ngo)
    rows = []
    query = (DonationListing.query.options(joinedload(DonationListing.donor))
             .filter(DonationListing.status == PENDING,
                     DonationListing.expires_at > utcnow()))
    for listing in query.all():
        lat, lng = listing.approx_location
        dist = haversine_km(ngo.latitude, ngo.longitude, lat, lng)
        if dist <= radius_km:
            rows.append((listing, dist))
    rows.sort(key=lambda row: row[1])
    return rows


def _write(statement):
    """Run one write statement + commit, retrying briefly if SQLite reports
    'database is locked' (writers queue up under concurrency)."""
    for attempt in range(5):
        try:
            result = statement()
            db.session.commit()
            return result
        except OperationalError as exc:
            db.session.rollback()
            if "locked" in str(exc).lower() and attempt < 4:
                time.sleep(0.05 * (attempt + 1))
                continue
            raise ServiceError("The service is busy. Please try again.", "busy", 503)
        except Exception:
            db.session.rollback()
            raise


def claim_listing(ngo, listing_id):
    """Atomically claim a listing.

    The single UPDATE only matches a row that is STILL Pending and NOT yet
    expired at this instant. Exactly one of any number of simultaneous callers
    gets rowcount == 1; everyone else gets 0 and a precise error.
    """
    _require_role(ngo, NGO, "claim food")
    _require_approved(ngo)
    now = utcnow()
    updated = _write(lambda: (
        db.session.query(DonationListing)
        .filter(DonationListing.id == listing_id,
                DonationListing.status == PENDING,
                DonationListing.expires_at > now)
        .update({DonationListing.status: CLAIMED,
                 DonationListing.claimed_by_ngo_id: ngo.id},
                synchronize_session=False)))
    if updated == 1:
        return get_listing(listing_id)

    # Lost the race (or invalid): work out why, from fresh data.
    listing = db.session.get(DonationListing, listing_id)
    if listing is None:
        raise ServiceError("Listing not found.", "not_found", 404)
    if listing.status != PENDING:
        if listing.claimed_by_ngo_id == ngo.id:
            raise ServiceError("You have already claimed this listing.",
                               "already_claimed_by_you", 409)
        raise ServiceError("Too late - another NGO already claimed this listing.",
                           "already_claimed", 409)
    raise ServiceError("Sorry, that listing has expired.", "expired", 410)


def withdraw_listing(donor, listing_id):
    """Delete a listing - only by its own donor and only while still Pending."""
    _require_role(donor, DONOR, "withdraw listings")
    deleted = _write(lambda: (
        db.session.query(DonationListing)
        .filter(DonationListing.id == listing_id,
                DonationListing.donor_id == donor.id,
                DonationListing.status == PENDING)
        .delete(synchronize_session=False)))
    if deleted == 1:
        return
    listing = db.session.get(DonationListing, listing_id)
    if listing is None or listing.donor_id != donor.id:
        raise ServiceError("Listing not found.", "not_found", 404)
    raise ServiceError("Only pending listings can be withdrawn.", "invalid_state", 409)


def mark_picked_up(ngo, listing_id):
    """Complete a pickup - only by the NGO that claimed it, once."""
    _require_role(ngo, NGO, "complete pickups")
    _require_approved(ngo)
    updated = _write(lambda: (
        db.session.query(DonationListing)
        .filter(DonationListing.id == listing_id,
                DonationListing.claimed_by_ngo_id == ngo.id,
                DonationListing.status == CLAIMED)
        .update({DonationListing.status: PICKED_UP}, synchronize_session=False)))
    if updated == 1:
        return get_listing(listing_id)
    listing = db.session.get(DonationListing, listing_id)
    if listing is None or listing.claimed_by_ngo_id != ngo.id:
        raise ServiceError("Listing not found.", "not_found", 404)
    raise ServiceError("Only claimed listings can be marked as picked up.",
                       "invalid_state", 409)


# ------------------------------------------------------------------- stats
def get_stats():
    return {
        "donations": DonationListing.query.count(),
        "active": DonationListing.query.filter(
            DonationListing.status == PENDING,
            DonationListing.expires_at > utcnow()).count(),
        "claimed": DonationListing.query.filter_by(status=CLAIMED).count(),
        "picked_up": DonationListing.query.filter_by(status=PICKED_UP).count(),
        "donors": User.query.filter_by(role=DONOR).count(),
        "ngos": User.query.filter_by(role=NGO).count(),
    }
