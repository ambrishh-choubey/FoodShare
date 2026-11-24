"""Builds the answer: either a verified knowledge-base entry or a summary of
the user's OWN data, read through the existing service functions (the same
permission-checked code the website uses). The assistant never runs free-form
queries and never changes data.

Privacy rule for everything below: no passwords, tokens, emails, street
addresses or exact coordinates are ever put into a reply.
"""
from flask import current_app, url_for

import services
from services import ServiceError

from . import intent_handler, knowledge_base as kb

DONOR, NGO, ADMIN = "Donor", "NGO", "Admin"
STAGE_TEXT = {"available": "Available", "pickup_pending": "Claimed - pickup pending",
              "completed": "Completed", "withdrawn": "Withdrawn", "expired": "Expired"}

SUGGESTIONS = {
    DONOR: ["What is the status of my latest donation?", "How many donations have I completed?",
            "How do I post surplus food?", "How can I withdraw a donation?"],
    NGO: ["Show my pending pickups.", "Why can't I claim a donation?",
          "Am I approved?", "How does expiry work?"],
    ADMIN: ["How many NGOs are awaiting approval?", "Show platform statistics.",
            "How do I approve an NGO?", "Show recent activity."],
    None: ["How does FoodShare work?", "How do I register?", "What is the difference between a donor and an NGO?"],
}


# ------------------------------------------------------------------ helpers
def _role(user):
    return user.role if user else None


def _fmt(dt):
    return dt.strftime("%d %b %H:%M") + " UTC" if dt else "unknown"


def _stage(listing):
    stage = getattr(listing, "stage", None)
    if stage in STAGE_TEXT:
        return STAGE_TEXT[stage]
    if listing.status == "Claimed":
        return STAGE_TEXT["pickup_pending"]
    if listing.status == "Picked_Up":
        return STAGE_TEXT["completed"]
    if listing.status == "Withdrawn":
        return STAGE_TEXT["withdrawn"]
    return STAGE_TEXT["expired"] if listing.is_expired else STAGE_TEXT["available"]


def _newest_first(rows):
    """Newest first; the id breaks ties (MySQL stores whole seconds)."""
    return sorted(rows, key=lambda l: (l.created_at, l.id), reverse=True)


def _links(pairs):
    """Only link to pages that exist in this install; (label, url) for the browser."""
    out = []
    for label, endpoint in pairs:
        if endpoint in current_app.view_functions:
            out.append({"label": label, "url": url_for(endpoint)})
    return out


def _reply(intent, text, links=(), user=None, suggestions=None):
    return {"intent": intent, "reply": text, "links": _links(links),
            "suggestions": SUGGESTIONS[_role(user)] if suggestions is None else suggestions}


def welcome(user):
    role = _role(user)
    names = {DONOR: "donor", NGO: "NGO", ADMIN: "administrator", None: "visitor"}
    text = ("Hi! I'm the FoodShare Smart Assistant. I answer questions about how FoodShare works"
            + (f" and can look up your own {'platform ' if role == ADMIN else ''}information" if role else "")
            + f". You're using FoodShare as a {names[role]}. I use verified facts, simple rules and a small "
              "on-device model to understand your wording, so if I'm not sure I'll say so.")
    return {"role": role, "user_id": user.id if user else None, "reply": text,
            "suggestions": SUGGESTIONS[role], "provider": "rules+on-device-model"}


def _login_needed(intent):
    return _reply(intent, "Please log in so I can look at your own FoodShare information.",
                  [("Login", "login"), ("Register", "register")])


# ------------------------------------------------------------- data answers
def _listing_line(l):
    return f'"{l.food_type}" ({l.quantity}): {_stage(l)}'


def _donor_latest(user):
    rows = _newest_first(services.donor_listings(user))
    if not rows:
        return _reply("latest_status", "You haven't posted any donations yet.",
                      [("My Donations", "donor_dashboard")], user)
    l = rows[0]
    lines = [f'Your latest donation is "{l.food_type}" ({l.quantity}).', f"Status: {_stage(l)}.",
             f"Posted: {_fmt(l.created_at)}."]
    if l.status == "Claimed" and l.claimed_by:
        claimed_at = getattr(l, "claimed_at", None)
        lines.append(f"Claimed by {l.claimed_by.name}" + (f" at {_fmt(claimed_at)}." if claimed_at else "."))
    if l.status == "Picked_Up":
        if l.claimed_by:
            lines.append(f"Picked up by {l.claimed_by.name}.")
        if getattr(l, "picked_up_at", None):
            lines.append(f"Picked up at {_fmt(l.picked_up_at)}.")
    if l.status == "Pending":
        lines.append(f"Safe to collect until {_fmt(l.expires_at)}.")
    return _reply("latest_status", "\n".join(lines), [("My Donations", "donor_dashboard")], user)


def _count_stages(rows):
    counts = {k: 0 for k in STAGE_TEXT.values()}
    for l in rows:
        counts[_stage(l)] += 1
    return counts


def _donor_counts(user):
    rows = services.donor_listings(user)
    if not rows:
        return _reply("counts", "You haven't posted any donations yet.", [("My Donations", "donor_dashboard")], user)
    c = _count_stages(rows)
    parts = [f"{c['Completed']} completed", f"{c['Claimed - pickup pending']} awaiting pickup",
             f"{c['Available']} available", f"{c['Expired']} expired"]
    if kb.feature("withdrawn_status"):
        parts.append(f"{c['Withdrawn']} withdrawn")
    return _reply("counts", f"You have posted {len(rows)} donation(s): " + ", ".join(parts) + ".",
                  [("My Donations", "donor_dashboard")], user)


def _donor_list(user, intent, only_active):
    rows = _newest_first(services.donor_listings(user))
    if only_active:
        rows = [l for l in rows if _stage(l) in (STAGE_TEXT["available"], STAGE_TEXT["pickup_pending"])]
    if not rows:
        text = "You have no active donations right now." if only_active else "You haven't posted any donations yet."
        return _reply(intent, text, [("My Donations", "donor_dashboard")], user)
    shown = rows[:5]
    head = "Your active donations:" if only_active else "Your most recent donations:"
    lines = [head] + [f"- {_listing_line(l)}, posted {_fmt(l.created_at)}" for l in shown]
    if len(rows) > len(shown):
        lines.append(f"...and {len(rows) - len(shown)} more on My Donations.")
    return _reply(intent, "\n".join(lines), [("My Donations", "donor_dashboard")], user)


def _donor_pending_pickups(user):
    rows = [l for l in services.donor_listings(user) if l.status == "Claimed"]
    if not rows:
        return _reply("pending_pickups", "None of your donations is waiting for pickup right now.",
                      [("My Donations", "donor_dashboard")], user)
    lines = ["Your donations waiting to be collected:"]
    for l in rows[:5]:
        who = l.claimed_by.name if l.claimed_by else "an NGO"
        lines.append(f'- "{l.food_type}" ({l.quantity}), claimed by {who}')
    return _reply("pending_pickups", "\n".join(lines), [("My Donations", "donor_dashboard")], user)


def _ngo_pending_pickups(user):
    rows = [l for l in services.claimed_listings(user) if l.status == "Claimed"]
    if not rows:
        return _reply("pending_pickups", "You have no pending pickups right now.", [("Find Food", "ngo_dashboard")], user)
    lines = [f"You have {len(rows)} pending pickup(s):"]
    for l in rows[:5]:
        lines.append(f'- "{l.food_type}" ({l.quantity}) from {l.donor.name}, collect by {_fmt(l.expires_at)}')
    lines.append("Open Find Food for the exact pickup details.")
    return _reply("pending_pickups", "\n".join(lines), [("Find Food", "ngo_dashboard")], user)


def _ngo_counts(user):
    rows = services.claimed_listings(user)
    done = sum(1 for l in rows if l.status == "Picked_Up")
    pending = sum(1 for l in rows if l.status == "Claimed")
    return _reply("counts", f"You have claimed {len(rows)} donation(s): {done} completed pickup(s) "
                            f"and {pending} still pending.", [("Find Food", "ngo_dashboard")], user)


def _ngo_latest(user):
    rows = _newest_first(services.claimed_listings(user))
    if not rows:
        return _reply("latest_status", "You haven't claimed any donations yet.", [("Find Food", "ngo_dashboard")], user)
    l = rows[0]
    return _reply("latest_status", f'Your latest claim is "{l.food_type}" ({l.quantity}) from {l.donor.name}.\n'
                                   f"Status: {_stage(l)}.", [("Find Food", "ngo_dashboard")], user)


def _admin_stats(user):
    lines = []
    if hasattr(services, "analytics_for"):
        d = services.analytics_for(user)
        u, l = d["users"], d["listings"]
        lines = [f"Users: {u['donors']} donor(s), {u['ngos']} NGO(s) ({u['ngos_approved']} approved, "
                 f"{u['ngos_pending']} pending).",
                 f"Donations: {l['total']} posted, {l['active']} active, {l['completed']} completed, "
                 f"{l['withdrawn']} withdrawn, {l['expired']} expired."]
    else:
        s = services.get_stats()
        lines = [f"Users: {s['donors']} donor(s), {s['ngos']} NGO(s).",
                 f"Donations: {s['donations']} posted, {s['active']} active, {s['claimed']} claimed, "
                 f"{s['picked_up']} picked up."]
    return _reply("counts", "Platform statistics:\n" + "\n".join(lines), [("Admin page", "admin_panel")], user)


def _admin_pending(user):
    pending = services.pending_ngos()
    if not pending:
        return _reply("pending_ngos", "No NGOs are waiting for approval.", [("Admin page", "admin_panel")], user)
    names = ", ".join(n.name for n in pending[:5])
    more = f" and {len(pending) - 5} more" if len(pending) > 5 else ""
    return _reply("pending_ngos", f"{len(pending)} NGO(s) are awaiting approval: {names}{more}.",
                  [("Admin page", "admin_panel")], user)


def _admin_activity(user):
    if not hasattr(services, "recent_activity"):
        return _reply("recent_activity", "The recent-activity view is not available in this version of FoodShare.", (), user)
    events = services.recent_activity(user, limit=5)
    if not events:
        return _reply("recent_activity", "There is no activity yet.", [("Admin page", "admin_panel")], user)
    lines = ["Latest activity:"] + [f"- {_fmt(e['at'])}: {e['text']}" for e in events]
    return _reply("recent_activity", "\n".join(lines), [("Admin page", "admin_panel")], user)


def _my_approval(user):
    if user.is_approved:
        text = "Yes, your NGO account is approved. You can find and claim food."
    else:
        text = ("Your NGO account is still awaiting administrator approval. Until then you can sign in, "
                "but you cannot see or claim food.")
    return _reply("my_approval", text, [("Find Food", "ngo_dashboard")], user)


GENERIC_CLAIM_REASONS = (
    "A donation can't be claimed when:\n"
    "- your NGO account hasn't been approved yet,\n"
    "- another NGO claimed it first,\n"
    "- the donor withdrew it,\n"
    "- it has expired,\n"
    "- or it isn't visible to you (it no longer exists as an available donation).\n"
    "Refresh Find Food to see what is available now.")


def _why_cant_claim(user, text):
    if user is None:
        return _login_needed("why_cant_claim")
    if user.role != NGO:
        return _reply("why_cant_claim", "Only approved NGO accounts can claim donations.", (), user)
    if not user.is_approved:
        return _reply("why_cant_claim", "Your NGO account is awaiting administrator approval, so you can't "
                      "see or claim food yet. This is the most likely reason.", [("Find Food", "ngo_dashboard")], user)
    listing_id = intent_handler.extract_listing_id(text)
    if listing_id is None:
        return _reply("why_cant_claim", GENERIC_CLAIM_REASONS + "\nTell me the donation number (for example "
                      "'donation #12') and I'll check it.", [("Find Food", "ngo_dashboard")], user)
    try:
        listing = services.get_visible_listing(user, listing_id)  # same visibility rule as the website
    except ServiceError:
        return _reply("why_cant_claim", f"I can't find an available donation #{listing_id} for you. "
                      "It may not exist, or it was claimed by another NGO, withdrawn or expired.\n"
                      "Refresh Find Food to see what is available now.", [("Find Food", "ngo_dashboard")], user)
    if listing.claimed_by_ngo_id == user.id:
        return _reply("why_cant_claim", f"Donation #{listing_id} is already claimed by you "
                      f"(status: {_stage(listing)}). See My claimed pickups.", [("Find Food", "ngo_dashboard")], user)
    return _reply("why_cant_claim", f"Donation #{listing_id} looks available and nothing prevents you from "
                  "claiming it. If the claim fails, another NGO probably claimed it at the same moment. "
                  "Refresh Find Food and try again.", [("Find Food", "ngo_dashboard")], user)


# ----------------------------------------------------------------- dispatch
def _restricted(intent, who):
    return _reply(intent, f"That information is available to {who} only.", ())


def _data_answer(intent, user, text):
    """Returns a reply for the intents that read the user's own data, else None."""
    role = _role(user)
    needs_login = {"latest_status", "counts", "active_donations", "history", "pending_pickups",
                   "pending_ngos", "my_approval", "recent_activity"}
    if intent in needs_login and user is None:
        return _login_needed(intent)
    allowed = intent_handler.intent_roles(intent)
    if allowed and role not in allowed:
        return _restricted(intent, "administrators" if allowed == (ADMIN,) else "NGO accounts")
    if intent == "latest_status":
        return {DONOR: _donor_latest, NGO: _ngo_latest}.get(role, lambda u: _reply(
            intent, "Ask me for platform statistics or recent activity.", (), u))(user)
    if intent == "counts":
        return {DONOR: _donor_counts, NGO: _ngo_counts, ADMIN: _admin_stats}[role](user)
    if intent == "active_donations":
        return _donor_list(user, intent, True) if role == DONOR else _reply(
            intent, "This applies to donor accounts. NGOs can ask about pending pickups.", (), user)
    if intent == "history":
        return _donor_list(user, intent, False) if role == DONOR else _reply(
            intent, "Donation history is available to donors. NGOs can ask about their pickups.", (), user)
    if intent == "pending_pickups":
        return {DONOR: _donor_pending_pickups, NGO: _ngo_pending_pickups}.get(role, _admin_stats)(user)
    if intent == "pending_ngos":
        return _admin_pending(user)
    if intent == "recent_activity":
        return _admin_activity(user)
    if intent == "my_approval":
        return _my_approval(user)
    if intent == "why_cant_claim":
        return _why_cant_claim(user, text)
    return None


def _knowledge_answer(intent, user):
    entry = kb.ANSWERS.get(intent)
    if entry is None or (entry.get("requires") and not kb.feature(entry["requires"])):
        return None
    role = _role(user)
    if "text" in entry:
        text = entry["text"]() if callable(entry["text"]) else entry["text"]
    else:
        text = entry.get(role) or entry["default"]
    links = list(entry.get("links", [])) + entry.get("links_by_role", {}).get(role, [])
    return _reply(intent, text, links, user)


def _help(user):
    role = _role(user)
    topics = {
        DONOR: "post food, the status of your donations, withdrawing, how NGOs claim and pick up food, "
               "expiry and privacy",
        NGO: "approval, finding and claiming food, your pending pickups, completing pickups, expiry and "
             "why a donation can't be claimed",
        ADMIN: "approving NGOs, platform statistics, recent activity and managing accounts",
        None: "how FoodShare works, registering, logging in and the different roles",
    }[role]
    return _reply("help", f"I can help with: {topics}. Try one of the suggested questions below.", (), user)


def answer(user, intent, text):
    if intent == "greeting":
        return _reply("greeting", "Hello! How can I help you with FoodShare today?", (), user)
    if intent == "help":
        return _help(user)
    if intent:
        reply = _data_answer(intent, user, text) or _knowledge_answer(intent, user)
        if reply:
            return reply
    return _reply("unknown", "I'm not sure about that, and I don't want to guess. I can answer questions "
                  "about how FoodShare works and look up your own information. For anything else, please "
                  "contact the FoodShare administrator.", (), user)
