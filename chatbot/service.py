"""Orchestration: validate -> rate limit -> understand -> answer.

Conversations are NOT stored on the server. The browser keeps the chat only for
the current tab (sessionStorage) and it is cleared on logout or "Clear".
"""
import threading
import time
from collections import defaultdict, deque

from services import ServiceError

from . import intent_handler, ml_intent, response_handler

MAX_MESSAGE_CHARS = 500
RATE_LIMIT_CALLS = 15      # messages ...
RATE_LIMIT_WINDOW = 60     # ... per this many seconds, per user (or per IP for visitors)


class RateLimiter:
    """Sliding window, kept in memory per server process (no database writes).
    With several worker processes each has its own counter, so the effective
    limit is per worker."""

    def __init__(self, max_calls, window):
        self.max_calls, self.window = max_calls, window
        self._hits = defaultdict(deque)
        self._lock = threading.Lock()

    def reset(self):
        with self._lock:
            self._hits.clear()

    def check(self, key):
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] >= self.window:
                hits.popleft()
            if len(hits) >= self.max_calls:
                wait = int(self.window - (now - hits[0])) + 1
                raise ServiceError("You're sending messages too quickly. "
                                   f"Please wait {wait} seconds and try again.",
                                   "rate_limited", 429, retry_after=wait)
            hits.append(now)
            if len(self._hits) > 5000:  # drop idle keys so memory stays bounded
                for k in [k for k, v in self._hits.items() if not v or now - v[-1] >= self.window]:
                    del self._hits[k]


_limiter = RateLimiter(RATE_LIMIT_CALLS, RATE_LIMIT_WINDOW)


def start(user):
    return response_handler.welcome(user)


def handle_message(user, body, client_key):
    _limiter.check(client_key)
    if not isinstance(body, dict) or not isinstance(body.get("message"), str):
        raise ServiceError('Send JSON like {"message": "your question"}.', "validation_error")
    text = "".join(ch for ch in body["message"] if ch.isprintable() or ch in "\n\t").strip()
    if not text:
        raise ServiceError("Please type a question.", "validation_error")
    if len(text) > MAX_MESSAGE_CHARS:
        raise ServiceError(f"Please keep your message under {MAX_MESSAGE_CHARS} characters.",
                           "validation_error")
    intent, source = understand(text)
    reply = response_handler.answer(user, intent, text)
    reply["understood_by"] = source if reply["intent"] != "unknown" else "none"
    return reply


RULE_PLAUSIBLE = 0.40  # model similarity at which a weak keyword match is kept


def understand(text):
    """(intent, how) where how is "rules" or "model". Whole-phrase rules are
    trusted first; if they found nothing, or only a loose keyword, the small
    on-device model gets a say. If the model is not sure, a loose keyword match
    is still used, and otherwise the answer is "I'm not sure"."""
    intent, score = intent_handler.detect_scored(text)
    if intent is None or score < 3:
        guess = ml_intent.classify(text)
        if guess and guess != intent:
            # A loose keyword match survives if the model also thinks that
            # intent is a plausible reading (e.g. "how do I approve an NGO?"
            # must not be turned into the NGO-only "am I approved?").
            keep_rule = intent is not None and dict(ml_intent.scores(text)).get(intent, 0) >= RULE_PLAUSIBLE
            if not keep_rule:
                return guess, "model"
        elif guess:
            return guess, "model"
    return intent, "rules" if intent else "none"
