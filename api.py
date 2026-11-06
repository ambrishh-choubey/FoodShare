


"""JSON API (v1). Session-cookie authentication + CSRF header on every
state-changing request. All responses use the envelope in responses.py."""
from datetime import datetime, timezone

from flask import Blueprint, g, request, session

import services
from auth import api_login_required, login_user
from database import ADMIN, DONOR, NGO, User, describe_database
from responses import fail, ok
from security import generate_csrf_token
from services import ServiceError

bp = Blueprint("api", __name__, url_prefix="/api/v1")


def payload():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else request.form.to_dict()


def _with_token(user):
    data = user.to_dict()
    data["csrf_token"] = generate_csrf_token()  # session was just rotated on login
    return data


@bp.errorhandler(ServiceError)
def handle_service_error(err):
    response, status = fail(err.code, err.message, err.status)
    if err.retry_after:
        response.headers["Retry-After"] = str(err.retry_after)
    return response, status

# ------------------------------------------------------------------ system
@bp.get("/health")
def health():
    return ok({"status": "ok", "database": describe_database(),
               "time": datetime.now(timezone.utc).isoformat(timespec="seconds")})


@bp.get("/csrf")
def csrf():
    return ok({"csrf_token": generate_csrf_token(), "header": "X-CSRFToken"})


@bp.get("/stats")
def stats():
    return ok(services.get_stats())


# -------------------------------------------------------------------- auth
@bp.post("/auth/register")
def register():
    body = payload()
    user = services.register_user(body.get("name"), body.get("email"),
                                  body.get("password"), body.get("role"),
                                  body.get("latitude"), body.get("longitude"),
                                  body.get("address"))
    login_user(user)
    return ok(_with_token(user), "Account created.", 201)


@bp.post("/auth/login")
def login():
    body = payload()
    user = services.authenticate(body.get("email"), body.get("password"),
                                 request.remote_addr)
    login_user(user)
    return ok(_with_token(user), "Logged in.")


@bp.post("/auth/logout")
def logout():
    session.clear()
    return ok(None, "Logged out.")


@bp.get("/auth/me")
@api_login_required()
def me():
    return ok(g.user.to_dict())


# ---------------------------------------------------------------- listings
@bp.get("/listings")
@api_login_required()
def list_listings():
    user = g.user
    if user.role == NGO and request.args.get("scope") != "mine":
        radius = services.parse_radius(request.args.get("radius"))
        rows = services.nearby_listings(user, radius)
        data = [l.to_dict(viewer=user, distance_km=dist) for l, dist in rows]
        return ok(data, count=len(data), radius_km=radius, scope="nearby")

    if user.role == NGO:
        rows, scope = services.claimed_listings(user), "mine"
    elif user.role == DONOR:
        rows, scope = services.donor_listings(user), "mine"
    else:
        rows, scope = services.all_listings(request.args.get("status") or None), "all"
    data = [l.to_dict(viewer=user) for l in rows]
    return ok(data, count=len(data), scope=scope)


@bp.post("/listings")
@api_login_required(DONOR)
def create_listing():
    body = payload()
    listing = services.create_listing(g.user, body.get("food_type"),
                                      body.get("quantity"), body.get("expiry_window"))
    return ok(listing.to_dict(viewer=g.user), "Listing created.", 201)


@bp.get("/listings/<int:listing_id>")
@api_login_required()
def get_listing(listing_id):
    listing = services.get_visible_listing(g.user, listing_id)
    return ok(listing.to_dict(viewer=g.user))


@bp.delete("/listings/<int:listing_id>")
@api_login_required(DONOR)
def withdraw_listing(listing_id):
    services.withdraw_listing(g.user, listing_id)
    return ok(None, "Listing withdrawn.")


@bp.post("/listings/<int:listing_id>/claim")
@api_login_required(NGO)
def claim_listing(listing_id):
    listing = services.claim_listing(g.user, listing_id)
    return ok(listing.to_dict(viewer=g.user),
              "Food claimed! The exact pickup details are now visible to you.")


@bp.post("/listings/<int:listing_id>/pickup")
@api_login_required(NGO)
def pickup_listing(listing_id):
    listing = services.mark_picked_up(g.user, listing_id)
    return ok(listing.to_dict(viewer=g.user), "Marked as picked up. Thank you!")


# ------------------------------------------------------------------- admin
@bp.get("/users")
@api_login_required(ADMIN)
def list_users():
    users = User.query.order_by(User.id).all()
    return ok([u.to_dict() for u in users], count=len(users))

@bp.post("/users/<int:user_id>/approve")
@api_login_required(ADMIN)
def approve_ngo(user_id):
    return ok(services.set_ngo_approval(g.user, user_id, True).to_dict(), "NGO approved.")


@bp.post("/users/<int:user_id>/revoke")
@api_login_required(ADMIN)
def revoke_ngo(user_id):
    return ok(services.set_ngo_approval(g.user, user_id, False).to_dict(), "NGO approval revoked.")
# ------------------------------------------------------ docs (rendered page)
API_ENDPOINTS = [
    {"method": "GET", "path": "/health", "auth": "Public",
     "summary": "Service status and the active database engine.", "try": True,
     "example": '{\n  "success": true,\n  "data": {\n    "status": "ok",\n    "database": {"engine": "sqlite", "driver": "sqlite", "database": "foodshare.db", "host": "local file"},\n    "time": "2026-10-31T09:40:12+00:00"\n  }\n}'},
    {"method": "GET", "path": "/csrf", "auth": "Public", "try": True,
     "summary": "Get the CSRF token for your session. Send it as the X-CSRFToken header on every POST/DELETE. Logging in or out starts a new session, so use the csrf_token returned by login (or call this again).",
     "example": '{"success": true, "data": {"csrf_token": "k3J...", "header": "X-CSRFToken"}}'},
    {"method": "GET", "path": "/stats", "auth": "Public", "try": True,
     "summary": "Platform-wide counters (donations, active, claimed, picked up, donors, NGOs).",
     "example": '{\n  "success": true,\n  "data": {"donations": 7, "active": 5, "claimed": 1, "picked_up": 1, "donors": 4, "ngos": 2}\n}'},
    {"method": "POST", "path": "/auth/register", "auth": "Public + CSRF",
     "summary": "Create a Donor or NGO account and start a session. Admin accounts cannot be created here. Password: 8-128 characters. address is optional, donors only, and is shown only to the NGO that claims your food.",
     "body": '{"name": "Cafe Bloom", "email": "bloom@example.com", "password": "a-long-secret",\n "role": "Donor", "latitude": 12.97, "longitude": 77.59, "address": "5 Lake Road"}',
     "example": '{\n  "success": true,\n  "message": "Account created.",\n  "data": {"id": 9, "name": "Cafe Bloom", "role": "Donor", "email": "bloom@example.com", "csrf_token": "..."}\n}'},
    {"method": "POST", "path": "/auth/login", "auth": "Public + CSRF",
     "summary": "Log in with email and password (sets the session cookie, returns a fresh csrf_token).",
     "body": '{"email": "donor1@demo.local", "password": "demo1234"}',
     "example": '{"success": true, "message": "Logged in.", "data": {"id": 2, "role": "Donor", "csrf_token": "...", "...": "..."}}'},
    {"method": "POST", "path": "/auth/logout", "auth": "Any + CSRF",
     "summary": "End the session.", "example": '{"success": true, "data": null, "message": "Logged out."}'},
    {"method": "GET", "path": "/auth/me", "auth": "Logged in", "try": True,
     "summary": "The currently logged-in user.",
     "example": '{"success": true, "data": {"id": 2, "name": "Spice Garden Restaurant", "role": "Donor", "...": "..."}}'},
    {"method": "GET", "path": "/listings", "auth": "Logged in", "try": True,
     "summary": "Donor: own listings. NGO: active listings nearby (?radius=km, default 50) or ?scope=mine for ones you claimed. Admin: everything (?status=Pending). Before a claim an NGO only sees an APPROXIMATE donor area (rounded coordinates + radius); exact location, email and address appear only after that NGO claims it.",
     "example": '{\n  "success": true,\n  "meta": {"count": 1, "radius_km": 50.0, "scope": "nearby"},\n  "data": [{\n    "id": 1, "food_type": "Veg biryani & raita", "quantity": "40 meals",\n    "status": "Pending", "hours_left": 5.7, "distance_km": 2.1,\n    "expires_at": "2026-10-31T15:40:00Z",\n    "donor": {"name": "Spice Garden Restaurant", "latitude": 12.98, "longitude": 77.64,\n              "location_precision": "approximate", "approximate_radius_m": 800},\n    "claimed_by": null\n  }]\n}'},
    {"method": "POST", "path": "/listings", "auth": "Donor + CSRF",
     "summary": "List surplus food. expiry_window is hours (1-168).",
     "body": '{"food_type": "Cooked rice & dal", "quantity": "20 meals", "expiry_window": 4}',
     "example": '{"success": true, "message": "Listing created.", "data": {"id": 8, "status": "Pending", "...": "..."}}'},
    {"method": "GET", "path": "/listings/{id}", "auth": "Owner, claimant, NGO (active) or Admin",
     "summary": "One listing (404 if you may not see it).", "example": '{"success": true, "data": {"id": 1, "...": "..."}}'},
    {"method": "DELETE", "path": "/listings/{id}", "auth": "Donor (owner) + CSRF",
     "summary": "Withdraw a listing that is still Pending.",
     "example": '{"success": true, "data": null, "message": "Listing withdrawn."}\n\n409 -> {"success": false, "error": {"code": "invalid_state", "message": "Only pending listings can be withdrawn."}}'},
    {"method": "POST", "path": "/listings/{id}/claim", "auth": "NGO + CSRF",
     "summary": "Claim a pending, unexpired listing. Atomic - only one NGO can win. Response now includes the exact donor location, email and address.",
     "example": '{"success": true, "message": "Food claimed! ...", "data": {"status": "Claimed", "donor": {"location_precision": "exact", "...": "..."}}}\n\n409 -> {"success": false, "error": {"code": "already_claimed", "message": "Too late - another NGO already claimed this listing."}}\n410 -> {"success": false, "error": {"code": "expired", "message": "Sorry, that listing has expired."}}'},
    {"method": "POST", "path": "/listings/{id}/pickup", "auth": "NGO (claimant) + CSRF",
     "summary": "Mark a claimed listing as picked up (once).",
     "example": '{"success": true, "message": "Marked as picked up. Thank you!", "data": {"status": "Picked_Up", "...": "..."}}'},
    {"method": "GET", "path": "/users", "auth": "Admin", "try": True,
     "summary": "All registered users.",
     "example": '{"success": true, "meta": {"count": 7}, "data": [{"id": 1, "name": "Platform Admin", "role": "Admin", "...": "..."}]}'},
]
