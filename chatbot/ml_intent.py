"""A small ON-DEVICE text classifier that helps the assistant understand
different wordings and typos. It is used ONLY when the keyword rules found
nothing.

How it works (plain Python, no libraries, nothing downloaded, no cost):
  1. Words are tidied: typos are fixed ("regster" -> "register") and words
     with the same meaning are mapped to one concept (cancel / remove /
     delete -> "withdraw"). The concept table is SYNONYMS below.
  2. Each training sentence (training_data.py) and each incoming question
     becomes features (words + word pairs) weighted by TF-IDF, so rare,
     informative words count more than common ones.
  3. The question is compared (cosine similarity) with every training
     sentence; each intent keeps its best match.
  4. The intent is accepted only if the match is strong AND clearly better
     than the runner-up. Otherwise the assistant says it is not sure.

It is trained from the examples every time the app starts (milliseconds),
returns only an intent NAME, never touches user data, and cannot bypass the
role checks that run after it. It is a small statistical model, not an LLM.
"""
import difflib
import math
import threading
from collections import Counter

from .intent_handler import normalize
from .training_data import EXAMPLES

MIN_SIMILARITY = 0.45   # weaker matches are treated as "not sure"
MIN_MARGIN = 0.07       # best intent must beat the runner-up by this much ...
SURE_ENOUGH = 0.80      # ... unless the match is this strong
TYPO_CUTOFF = 0.80      # how close a misspelling must be to a known word

# words that carry no meaning for this task
_STOP = {"a", "an", "the", "is", "are", "am", "to", "of", "it", "this", "that", "please", "so", "just",
         "me", "you", "can", "could", "would", "will", "tell", "want", "like", "need", "there", "any",
         "do", "does", "did", "have", "has", "be", "been", "also", "get", "got", "know", "shall", "should"}

# words with the same meaning -> one concept word (lets "delete a listing" match "withdraw")
_GROUPS = {
    "withdraw": "withdraw cancel remove delete undo retract revoke_donation takedown pull discard",
    "donation": "donation listing post posted offer offered food meals meal donate donated donating listed",
    "pickup": "pickup collect collected collecting collection picked picking handover",
    "location": "location address home live lives located where_i",
    "approve": "approve approved approval approving verify verified verification verifies clearance cleared confirmed",
    "notify": "notify notification alert reminder told bell inform",
    "chart": "graph chart charts graphs visual",
    "support": "support complain complaint problem issue bug contact helpdesk error",
    "near": "near nearby close closer nearest around",
    "expire": "expire expired expires expiry expiration deadline timeout stale cutoff",
    "latest": "latest last recent newest most_recent",
    "history": "history past previous old earlier before record log ever",
    "admin": "admin administrator administrators",
    "password": "password passcode credentials",
    "login": "login signin log_in",
    "register": "register signup enroll enrol registration join profile",
    "status": "status state stage stages progress update news happening",
    "count": "count number numbers total totals altogether",
    "pending": "pending awaiting waiting unapproved queue review",
    "claim": "claim reserve grab",
}
SYNONYMS = {word: canon for canon, words in _GROUPS.items() for word in words.split()}

_lock = threading.Lock()
_model = None


_PHRASES = (("sign out", "logout"), ("log out", "logout"), ("sign in", "login"), ("log in", "login"),
            ("sign up", "register"), ("take down", "withdraw"), ("pick up", "pickup"),
            ("picked up", "pickup"), ("picking up", "pickup"))


def _raw_tokens(text):
    out = []
    norm = f" {normalize(text)} "
    for phrase, word in _PHRASES:
        norm = norm.replace(f" {phrase} ", f" {word} ")
    for tok in norm.split():
        if tok in _STOP:
            continue
        if len(tok) > 3 and tok.endswith("s") and not tok.endswith("ss"):
            tok = tok[:-1]  # donations -> donation
        out.append(tok)
    return out


def _canon(tokens, vocab):
    out = []
    for tok in tokens:
        if tok not in vocab and tok not in SYNONYMS and len(tok) >= 4:
            close = difflib.get_close_matches(tok, vocab, n=1, cutoff=TYPO_CUTOFF)
            if close:
                tok = close[0]
        out.append(SYNONYMS.get(tok, tok))
    return out


def _features(tokens):
    feats = Counter()
    for t in tokens:
        feats["w:" + t] += 1.0
    for a, b in zip(tokens, tokens[1:]):
        feats[f"b:{a} {b}"] += 1.0
    return feats


def _vector(feats, idf, unknown=None):
    """Unknown words still count toward the length (at `unknown` weight), so a
    question full of words the model has never seen can't look like a perfect
    match just because its one known word matches."""
    vec = {f: (1.0 + math.log(c)) * idf[f] for f, c in feats.items() if f in idf}
    extra = sum(((1.0 + math.log(c)) * unknown) ** 2 for f, c in feats.items() if f not in idf and f.startswith("w:")) if unknown else 0.0
    norm = math.sqrt(sum(v * v for v in vec.values()) + extra)
    return {f: v / norm for f, v in vec.items()} if norm else {}


def _train():
    sentences = [(intent, _raw_tokens(text)) for intent, texts in EXAMPLES.items() for text in texts]
    vocab = sorted({t for _, toks in sentences for t in toks})
    docs = [(intent, _features(_canon(toks, vocab))) for intent, toks in sentences]
    df = Counter(f for _, feats in docs for f in feats)
    n = len(docs)
    idf = {f: math.log((n + 1) / (c + 1)) + 1.0 for f, c in df.items()}
    return vocab, idf, [(intent, _vector(feats, idf)) for intent, feats in docs], max(idf.values())


def _get_model():
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                _model = _train()
    return _model


def scores(text):
    """Best similarity per intent, highest first: [(intent, 0..1), ...]."""
    vocab, idf, examples, unknown_weight = _get_model()
    query = _vector(_features(_canon(_raw_tokens(text), vocab)), idf, unknown_weight)
    if not query:
        return []
    best = {}
    for intent, vec in examples:
        sim = sum(w * vec.get(f, 0.0) for f, w in query.items())
        if sim > best.get(intent, 0.0):
            best[intent] = sim
    return sorted(best.items(), key=lambda kv: -kv[1])


def classify(text):
    """Returns an intent name, or None when the model is not sure."""
    ranked = scores(text)
    if not ranked:
        return None
    top_intent, top = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0.0
    if top < MIN_SIMILARITY:
        return None
    if top < SURE_ENOUGH and top - second < MIN_MARGIN:
        return None
    if top_intent == "offtopic":  # recognised as unrelated to FoodShare: answer "not sure"
        return None
    return top_intent
