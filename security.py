"""CSRF protection and security headers.

Every state-changing request (POST/PUT/PATCH/DELETE) must carry the session's
CSRF token, either as the form field ``csrf_token`` or the ``X-CSRFToken``
header. Safe methods (GET/HEAD/OPTIONS) are never checked.
"""
import hmac
import secrets

from flask import g, render_template, request, session

from responses import fail

SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}
SESSION_KEY = "_csrf"


def generate_csrf_token():
    token = session.get(SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[SESSION_KEY] = token
    return token


def _token_matches(sent, expected):
    if not sent or not expected:
        return False
    # compare bytes: hmac.compare_digest raises TypeError on non-ASCII str
    return hmac.compare_digest(sent.encode("utf-8"), expected.encode("utf-8"))


def init_security(app):
    @app.before_request
    def csrf_protect():
        if not app.config.get("CSRF_ENABLED", True) or request.method in SAFE_METHODS:
            return None
        sent = request.headers.get("X-CSRFToken") or request.form.get("csrf_token") or ""
        if _token_matches(sent, session.get(SESSION_KEY, "")):
            return None
        if request.path.startswith("/api/"):
            return fail("csrf_failed",
                        "Missing or invalid CSRF token. GET /api/v1/csrf and send it "
                        "in the X-CSRFToken header.", 403)
        return render_template(
            "error.html", code=403,
            message="Your security token is missing or has expired. "
                    "Reload the page and try again."), 403

    @app.after_request
    def security_headers(response):
        h = response.headers
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        h.setdefault("Permissions-Policy", "geolocation=(self), camera=(), microphone=()")
        if request.path.startswith("/api/") or g.get("user") is not None:
            h.setdefault("Cache-Control", "no-store")
        if app.config.get("IS_PRODUCTION"):
            h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response
