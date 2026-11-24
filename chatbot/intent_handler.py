"""Understands a question with transparent keyword rules (no AI, no model).

Each intent lists phrases. A multi-word phrase found in the message scores 3
points, a single keyword scores 1. The best-scoring intent wins (ties go to the
higher `priority`); if nothing matches, the answer is "I'm not sure".
Add or tune intents here without touching anything else.
"""
import re
from dataclasses import dataclass

DONOR, NGO, ADMIN = "Donor", "NGO", "Admin"


@dataclass(frozen=True)
class Intent:
    name: str
    phrases: tuple
    priority: int = 1
    roles: tuple = ()   # who may use the DATA version; empty = everyone


INTENTS = (
    # ---- answers from the user's own data (role is enforced when answering) ----
    Intent("latest_status", ("latest donation", "last donation", "recent donation", "my latest",
                             "status of my", "my donation status", "latest claim", "latest pickup"), 6),
    Intent("counts", ("how many donations", "how many have i", "how many did i", "how many pickups",
                      "how many claims", "total donations", "completed donations", "completed pickups",
                      "how many donors", "how many users", "platform statistics", "platform stats",
                      "statistics", "stats", "my stats", "numbers"), 5),
    Intent("active_donations", ("active donations", "my active", "current donations", "ongoing",
                                "available donations"), 5),
    Intent("history", ("donation history", "my donations", "past donations", "list my donations",
                       "history"), 5),
    Intent("pending_pickups", ("pending pickups", "pending pickup", "my pickups", "show my pickups",
                               "to collect", "uncollected", "my claims", "claimed donations",
                               "waiting for pickup"), 6),
    Intent("pending_ngos", ("awaiting approval", "pending ngos", "pending approval", "ngos pending",
                            "how many ngos", "waiting for approval", "ngo requests",
                            "ngos waiting"), 7, (ADMIN,)),
    Intent("my_approval", ("am i approved", "my approval", "approval status", "is my account approved",
                           "is my ngo approved", "has my ngo been approved"), 7, (NGO,)),
    Intent("recent_activity", ("recent activity", "latest activity", "what happened", "platform activity",
                               "activity feed"), 6, (ADMIN,)),
    Intent("why_cant_claim", ("cant claim", "cannot claim", "unable to claim", "not able to claim",
                              "why cant i claim", "why can i not claim", "claim button", "claim failed",
                              "wont let me claim", "claim not working"), 8),
    # ---- verified knowledge ----
    Intent("greeting", ("hello", "hi", "hey", "good morning", "good evening", "thanks", "thank you",
                        "bye"), 1),
    Intent("about", ("what is foodshare", "how does foodshare work", "how it works", "about foodshare",
                     "what does this app do", "what is this", "foodshare work", "overview",
                     "how does this work", "purpose"), 3),
    Intent("roles", ("roles", "donor and ngo", "donor vs ngo", "who can use", "user types",
                     "types of users", "what is a donor", "what is an ngo"), 3),
    Intent("register", ("register", "sign up", "signup", "create account", "create an account",
                        "join", "new account"), 3),
    Intent("login", ("log in", "login", "sign in", "password", "logout", "log out", "forgot",
                     "locked out", "too many attempts"), 3),
    Intent("post_food", ("post food", "post surplus", "post a donation", "post donation", "list food",
                         "list surplus", "add donation", "donate food", "create donation",
                         "how to donate", "how do i donate", "surplus", "post"), 3),
    Intent("statuses", ("statuses", "status mean", "stages", "stage", "what does claimed mean",
                        "pending mean", "status", "timeline", "tracking", "track"), 2),
    Intent("withdraw", ("withdraw", "cancel donation", "cancel listing", "remove donation",
                        "delete donation", "take back", "cancel my donation", "remove my listing"), 4),
    Intent("claim_rules", ("how to claim", "how do i claim", "claim food", "claim rules",
                           "claiming", "claim"), 3),
    Intent("pickup", ("pickup", "pick up", "picked up", "mark picked", "collect", "collection",
                      "complete pickup", "completed pickup"), 3),
    Intent("expiry", ("expiry", "expire", "expires", "expired", "expiration", "safe to collect",
                      "deadline", "how long", "time window"), 3),
    Intent("ngo_approval", ("approval", "approve", "approved", "verification", "verify",
                            "get approved", "revoke"), 3),
    Intent("location_privacy", ("location", "privacy", "private", "address", "exact location",
                                "approximate", "who can see", "my details", "contact details"), 3),
    Intent("find_food", ("find food", "nearby", "near me", "map", "radius", "search food"), 3),
    Intent("notifications", ("notification", "notifications", "bell", "alert", "alerts", "reminder",
                             "reminders"), 3),
    Intent("impact", ("impact", "analytics", "charts", "chart", "dashboard"), 2),
    Intent("admin_how", ("manage users", "user accounts", "manage accounts", "admin panel",
                         "admin page", "monitor donations", "manage platform", "admin"), 3),
    Intent("support", ("support", "contact", "help desk", "report a problem", "report problem",
                       "complaint", "bug"), 3),
    Intent("help", ("help", "what can you do", "what can i ask", "capabilities", "commands",
                    "options"), 2),
)


def normalize(text):
    text = text.lower().replace("’", "'")
    text = re.sub(r"\b(can't|cant|can not)\b", "cant", text)
    text = re.sub(r"\b(won't|wont)\b", "wont", text)
    text = re.sub(r"[^a-z0-9# ]+", " ", text)
    return " ".join(text.split())


def detect(text):
    """Returns the best intent NAME, or None if nothing matches."""
    return detect_scored(text)[0]


def detect_scored(text):
    """(intent name or None, score). A score of 3 or more means a whole phrase
    matched (strong); 1 or 2 means only a loose keyword matched (weak)."""
    norm = normalize(text)
    padded, tokens = f" {norm} ", set(norm.split())
    best, best_key = None, (0, 0)
    for intent in INTENTS:
        if intent.name == "greeting" and len(tokens) > 4:
            continue  # "translate good morning to french" is not a greeting
        score = 0
        for phrase in intent.phrases:
            p = normalize(phrase)
            if " " in p:
                if f" {p} " in padded:
                    score += 3
            elif p in tokens:
                score += 1
        if score and (score, intent.priority) > best_key:
            best, best_key = intent.name, (score, intent.priority)
    return best, best_key[0]


def intent_roles(name):
    for intent in INTENTS:
        if intent.name == name:
            return intent.roles
    return ()


def extract_listing_id(text):
    """'#12', 'donation 12' or 'listing 12' -> 12, else None."""
    match = re.search(r"(?:#|donation\s+|listing\s+|id\s+)(\d{1,9})\b", text.lower())
    return int(match.group(1)) if match else None
