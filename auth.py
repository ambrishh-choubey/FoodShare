"""Session helpers and role-based access decorators (web + API).

Authorization is always checked on the server: the decorators below run before
the view, and services re-check ownership/role on every state change.
"""
from functools import wraps

from flask import abort, flash, g, redirect, session, url_for

from database import ADMIN, DONOR, NGO, User, db
from responses import fail


def load_current_user():
    uid = session.get("user_id")
    g.user = db.session.get(User, uid) if uid else None
    if uid and g.user is None:  # account no longer exists
        session.clear()


def login_user(user):
    session.clear()  # new session => new CSRF token, no session fixation
    session["user_id"] = user.id
    session.permanent = True


def home_url(user):
    endpoint = {DONOR: "donor_dashboard", NGO: "ngo_dashboard", ADMIN: "admin_panel"}[user.role]
    return url_for(endpoint)


def web_login_required(*roles):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if g.user is None:
                flash("Please log in to continue.", "warning")
                return redirect(url_for("login"))
            if roles and g.user.role not in roles:
                abort(403)
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def api_login_required(*roles):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if g.user is None:
                return fail("unauthorized", "Authentication required. Log in first.", 401)
            if roles and g.user.role not in roles:
                return fail("forbidden",
                            "This action requires the role: " + " or ".join(roles) + ".", 403)
            return fn(*args, **kwargs)
        return wrapper
    return decorator
