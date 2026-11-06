"""Database-backed login throttling (works across gunicorn workers, no Redis).

Failed logins are recorded per ACCOUNT (email) and per IP address. Too many
recent failures => the login is refused before the password is even checked.
"""
from datetime import timedelta

from database import LoginAttempt, db, utcnow

WINDOW = timedelta(minutes=15)
LIMITS = {"acct": 5, "ip": 20}  # failures allowed per WINDOW


class Throttled(Exception):
    def __init__(self, retry_after):
        super().__init__("too many attempts")
        self.retry_after = retry_after  # seconds


def _keys(email, ip):
    keys = [("acct", "acct:" + (email or "")[:160])]
    if ip:
        keys.append(("ip", "ip:" + str(ip)[:64]))
    return keys


def check(email, ip):
    """Raise Throttled if this account or IP has too many recent failures."""
    now = utcnow()
    since = now - WINDOW
    for kind, key in _keys(email, ip):
        stamps = [row[0] for row in
                  db.session.query(LoginAttempt.created_at)
                  .filter(LoginAttempt.key == key, LoginAttempt.created_at > since)
                  .order_by(LoginAttempt.created_at).all()]
        limit = LIMITS[kind]
        if len(stamps) >= limit:
            # unblocked once enough old failures age out of the window
            frees_at = stamps[len(stamps) - limit] + WINDOW
            raise Throttled(max(1, int((frees_at - now).total_seconds())))


def record_failure(email, ip):
    now = utcnow()
    for _kind, key in _keys(email, ip):
        db.session.add(LoginAttempt(key=key, created_at=now))
    # housekeeping: forget failures that no longer count
    LoginAttempt.query.filter(LoginAttempt.created_at < now - WINDOW).delete(
        synchronize_session=False)
    db.session.commit()


def clear_account(email):
    """A successful login wipes that account's failure counter (not the IP's)."""
    LoginAttempt.query.filter(LoginAttempt.key == "acct:" + (email or "")[:160]).delete(
        synchronize_session=False)
    db.session.commit()