# FoodShare – Food Waste Reduction & Donation Platform

Flask + SQLAlchemy + Bootstrap 5 + Leaflet. Donors list surplus food, NGOs claim it from a live map, admins oversee.

## Quick start (development)
```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # optional (APP_ENV, SECRET_KEY)
flask --app app create-admin                           # REQUIRED: there is no default admin
python app.py                                          # http://127.0.0.1:5000
```
In development, demo donors/NGOs/listings are created on the first run (password `demo1234`,
e.g. `donor1@demo.local`, `ngo1@demo.local`). Turn off with `SEED_DEMO=false` in `database/db.env`.

> Upgrading from an earlier version? The schema gained columns and CHECK constraints, and
> `create_all()` does not alter existing tables. For a dev database just delete
> `database/data/foodshare.db`. For real data, use Alembic/Flask-Migrate.

## Tests
```bash
python -m unittest discover -v
```
Covers simultaneous claims (threads + HTTP), expired listings, withdrawals, pickup completion,
database constraints, CSRF, authorization, admin setup, secret-key handling and location privacy.

## Security model
| Area | What the code does |
|---|---|
| Admin | No default admin or password anywhere. Only `flask --app app create-admin` creates one (min 12 chars, weak list rejected). Public sign-up only allows Donor/NGO. |
| Passwords | Werkzeug salted hashes (scrypt/pbkdf2); 8–128 chars; never stored or logged in plain text. |
| CSRF | Every POST/DELETE needs the session token (`csrf_token` form field or `X-CSRFToken` header). Logout is POST-only. `GET /api/v1/csrf` for API clients. |
| Secrets | `SECRET_KEY` only from the environment. `APP_ENV=production` refuses to start without a ≥32-char key. `.env`, `database/db.env`, `instance/`, `*.db` are git-ignored. |
| Sessions | HttpOnly, SameSite=Lax, `Secure` in production, 8h lifetime, session rotated on login. |
| Authorization | Role decorators on every web/API route, plus ownership checks inside the service layer; unauthorized records return 404. |
| Headers | `X-Frame-Options`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`, HSTS (production), `no-store` for authenticated pages. |

## Claim reliability
* `status` / `role` / coordinates / expiry window are enforced by database **CHECK constraints**; a Pending listing can never have a claimant and a Claimed/Picked_Up listing always has one; foreign keys are enforced (also on SQLite).
* Claim, withdraw and pickup are each a **single atomic conditional UPDATE/DELETE** (`WHERE status='Pending' AND expires_at > now …`). The database picks exactly one winner on SQLite, MySQL and PostgreSQL, and expiry is checked on the server inside that same statement.

## Location privacy
Before a claim an NGO sees only the donor's **approximate area** (coordinates rounded to ~1 km + an 800 m circle; distances use the rounded point). Exact coordinates, address and email are returned only to the donor, the NGO that claimed the listing, and admins.

## Switching database
Copy `database/db.env.example` to `database/db.env` and set `DB_ENGINE=sqlite|mysql|postgresql`
(install `requirements-db.txt` drivers as needed). See comments in the file.

## Production
```bash
export APP_ENV=production
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"   # store in your secret manager
export DB_ENGINE=postgresql DB_HOST=... DB_NAME=... DB_USER=... DB_PASSWORD=...
flask --app app create-admin
gunicorn "app:create_app()"        # behind an HTTPS reverse proxy
```
See **PRODUCTION_CHECKLIST.md** for what still needs doing outside the code.

## Layout
```
app.py  api.py  services.py  auth.py  security.py  responses.py
database/   core.py models.py seed.py settings.py db.env.example data/
static/     css/ js/ img/
templates/  Jinja pages (+ /api/docs)
tests/      unittest suite
```
