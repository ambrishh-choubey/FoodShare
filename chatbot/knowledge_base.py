"""Verified facts about FoodShare. Every statement here was checked against the
source code (see the comment after each entry). Do not add a fact unless the
application really behaves that way. Features that may not be installed are
listed in FEATURES and the assistant only mentions them when they exist."""
import importlib.util

import database
import services

DONOR, NGO, ADMIN = "Donor", "NGO", "Admin"

# name -> function telling whether this install really has the feature
FEATURES = {
    "withdrawn_status": lambda: hasattr(database, "WITHDRAWN"),                  # soft-delete on withdraw
    "tracking": lambda: hasattr(database.DonationListing, "claimed_at"),         # claimed / pickup times
    "impact": lambda: hasattr(services, "analytics_for"),                        # Impact page
    "notifications": lambda: importlib.util.find_spec("notifications") is not None,
    "admin_filters": lambda: hasattr(services, "admin_listings_page"),
}


def feature(name):
    try:
        return bool(FEATURES[name]())
    except Exception:  # noqa: BLE001 - a broken check must never break the chat
        return False


# Each answer: text, or {role: text, "default": text}. links = (label, endpoint).
def _statuses():
    lines = ["Every donation is in one of these stages:",
             "- Available: posted and not expired, so NGOs can claim it.",
             "- Claimed - pickup pending: an NGO claimed it and will collect it.",
             "- Completed: the NGO marked the food as picked up."]
    if feature("withdrawn_status"):
        lines.append("- Withdrawn: the donor removed it before anyone claimed it.")
    lines.append("- Expired: nobody claimed it before its deadline.")
    if feature("tracking"):
        lines.append("Donors and NGOs also see when it was posted, claimed and picked up.")
    return "\n".join(lines)


ANSWERS = {
    "about": {
        "text": ("FoodShare connects people who have surplus food (donors such as restaurants, hotels "
                 "and households) with approved NGOs that collect it. A donor posts the food with a "
                 "quantity and a time window; nearby NGOs see it on a map and one NGO claims it; the NGO "
                 "collects it and marks it picked up. Administrators approve NGO accounts."),
        "links": [("Register", "register"), ("API docs", "api_docs")],
    },
    "roles": {
        "text": ("FoodShare has three roles:\n"
                 "- Donor: posts surplus food and tracks it.\n"
                 "- NGO: finds nearby food, claims it and marks pickups complete. Needs admin approval first.\n"
                 "- Admin: approves or revokes NGO accounts and monitors the platform."),
    },
    "register": {  # services.register_user, templates/register.html
        "text": ("Open the Register page and choose Donor or NGO. Enter your name, email and a password "
                 "(8 to 128 characters, not an easily guessed one), then set your location by clicking the "
                 "map, dragging the pin or using GPS. Donors can add an optional pickup address; it is shown "
                 "only to the NGO that claims their food. NGO accounts must be approved by an administrator "
                 "before they can see or claim food. Admin accounts cannot be created from this page."),
        "links": [("Register", "register"), ("Login", "login")],
    },
    "login": {  # throttle.py: 5 failures per account / 20 per IP in 15 minutes
        "text": ("Log in with your email and password on the Login page; use the Logout button in the top "
                 "bar to sign out. After several wrong attempts (5 for one account, or 20 from one network, "
                 "within 15 minutes) logins are paused for a short time, so wait and try again. FoodShare "
                 "does not currently include a password-reset feature."),
        "links": [("Login", "login")],
    },
    "post_food": {  # services.create_listing
        DONOR: ("Open My Donations and fill in 'List surplus food': the food type (up to 160 characters), "
                "the quantity as free text such as '20 meals' (up to 80 characters) and 'Safe to collect "
                "within' in hours (1 to 168). After you post, nearby approved NGOs can see it until that "
                "time passes."),
        "default": "Only donor accounts can post surplus food. Register as a Donor to list food.",
        "links_by_role": {DONOR: [("My Donations", "donor_dashboard")]},
    },
    "statuses": {"text": _statuses},
    "withdraw": {  # services.withdraw_listing
        "text": ("A donor can withdraw a donation only while it is still available, meaning no NGO has "
                 "claimed it. Click Withdraw on My Donations and confirm. Once an NGO has claimed it, it "
                 "can no longer be withdrawn."),
        "links_by_role": {DONOR: [("My Donations", "donor_dashboard")]},
    },
    "claim_rules": {  # services.claim_listing
        "text": ("Only approved NGOs can claim food. Open Find Food, choose a listing and click Claim "
                 "Food. Claims are first come, first served: if two NGOs click at the same moment only one "
                 "succeeds. You can claim only a donation that is still available and not expired. After "
                 "you claim it, the donor's exact address and contact details appear under 'My claimed "
                 "pickups'."),
        "links_by_role": {NGO: [("Find Food", "ngo_dashboard")]},
    },
    "pickup": {  # services.mark_picked_up
        "text": ("After collecting the food, the NGO that claimed it clicks 'Mark picked up' under 'My "
                 "claimed pickups'. Only the claiming NGO can do this, and only once. The donor then sees "
                 "the donation as completed."),
        "links_by_role": {NGO: [("Find Food", "ngo_dashboard")]},
    },
    "expiry": {  # DonationListing.expires_at
        "text": ("When a donor posts food they choose how long it stays safe to collect (1 to 168 hours). "
                 "When that time passes the donation disappears from NGO maps and can no longer be "
                 "claimed."),
    },
    "ngo_approval": {  # services.set_ngo_approval, _require_approved
        NGO: ("New NGO accounts start as pending. An administrator reviews and approves them. Until you "
              "are approved you can sign in, but you cannot see or claim food. An administrator can also "
              "revoke approval later."),
        ADMIN: ("Open the Admin page. Under 'NGO approvals' click Approve next to a pending NGO. In the "
                "Users table you can click Revoke next to an approved NGO to remove its access."),
        "default": ("NGO accounts must be approved by a FoodShare administrator before they can see or "
                    "claim food. Donor accounts do not need approval."),
        "links_by_role": {ADMIN: [("Admin page", "admin_panel")]},
    },
    "location_privacy": {  # models.DonationListing.to_dict / approx_location
        "text": ("To protect donors, NGOs see only an approximate area (a circle of roughly 800 metres) "
                 "for a donation until they claim it. After claiming, the claiming NGO sees the exact "
                 "location, address and email. Donors always see their own details; administrators can "
                 "see exact details too. This assistant never shows addresses or contact details."),
    },
    "find_food": {  # templates/ngo.html, services.nearby_listings
        "text": ("Find Food shows available donations near you on a map and in a list, nearest first. You "
                 "can change the search radius (1 to 500 km, default 50). It updates automatically."),
        "links_by_role": {NGO: [("Find Food", "ngo_dashboard")]},
    },
    "notifications": {
        "requires": "notifications",
        "text": ("The bell icon in the top bar shows your in-app notifications. Donors are told when an NGO "
                 "claims or picks up their donation, or when it expires unclaimed. NGOs are told when "
                 "nearby food is close to expiring or a claimed pickup deadline is close. Click a "
                 "notification to mark it read, or use 'Mark all read'."),
    },
    "impact": {
        "requires": "impact",
        "text": ("The Impact page shows statistics calculated from real FoodShare records, such as how many "
                 "donations were completed, are active, were withdrawn or expired. FoodShare does not "
                 "estimate kilograms or meals saved, because quantities are entered as free text."),
        "links": [("Impact", "analytics")],
    },
    "admin_how": {
        ADMIN: ("The Admin page has: platform statistics and donor/NGO counts, NGO approvals (Approve), the "
                "user list (Revoke approval for NGOs) and the list of donations."
                " Donations can be filtered by status and posted date." if feature("admin_filters") else
                "The Admin page has: platform statistics, NGO approvals (Approve), the user list (Revoke "
                "approval for NGOs) and the list of donations."),
        "default": "Account management and platform monitoring are available to administrators only.",
        "links_by_role": {ADMIN: [("Admin page", "admin_panel")]},
    },
    "support": {
        "text": ("FoodShare does not have a built-in live support or ticket system. For account or "
                 "platform problems, please contact the person who runs this FoodShare site (the "
                 "administrator)."),
    },
}
