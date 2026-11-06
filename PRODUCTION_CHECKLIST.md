# Production checklist – things only you can do

The code now enforces the secure defaults; the items below need your accounts, servers or decisions.
Tick them off before real users touch the app.

## 1. Do these before the first deploy
- [ ] **Run the tests on your machine**: `pip install -r requirements.txt && python -m unittest discover -v`. They were written but could not be executed in the environment where this code was produced (no package-index access) – treat the first run as the real verification and send/fix any failure.
- [ ] **Generate and store a SECRET_KEY** (`python -c "import secrets; print(secrets.token_hex(32))"`) in your host's secret manager / environment variables. Never put it in a file in the repo.
- [ ] Set `APP_ENV=production` on the server (turns on Secure cookies, HSTS, strong-key check, disables demo data).
- [ ] **Create the admin** on the server: `flask --app app create-admin` (use a password-manager generated 16+ char password).
- [ ] Use **PostgreSQL or MySQL** in production, not SQLite. Create a dedicated DB user with only the privileges the app needs, strong password, no public network access.
- [ ] Serve over **HTTPS** (Nginx/Caddy/your PaaS) and run with `gunicorn "app:create_app()"` – never `python app.py`.
- [ ] Delete any old dev database (`database/data/*.db`) or migrate it – the schema changed (new columns + constraints).
- [ ] Behind a reverse proxy? Set TRUSTED_PROXY_COUNT=1 so login rate limiting sees real client IPs.

## 2. GitHub hygiene
- [ ] Run `git status` before the first commit and confirm `.env`, `database/db.env`, `instance/`, `*.db` are **not** listed (they are in `.gitignore`).
- [ ] If a secret/password was EVER committed: rotate it immediately (removing the file is not enough) and purge history (`git filter-repo` or BFG).
- [ ] Enable on the GitHub repo: Secret scanning + push protection, Dependabot alerts/updates, branch protection on `main`.
- [ ] Add a CI workflow that runs `python -m unittest discover` on every push (and ideally against a PostgreSQL service container too).

## 3. Strongly recommended next (not implemented here)
- [ ] **Database migrations**: add Flask-Migrate/Alembic so future schema changes don't need a wiped database.
- [x] **Rate limiting / brute-force protection** on `/login`, `/register` and `/api/v1/auth/*` (Flask-Limiter + Redis), optional account lockout/CAPTCHA.
- [x] **NGO verification**: anyone can currently register as an NGO and then see exact pickup details after claiming. Add an admin-approval step (e.g. `is_verified` flag) before an NGO may claim, and manually vet NGOs.
- [ ] Email verification and password reset (needs an email provider).
- [ ] **Content-Security-Policy** header tuned to your CDNs, or self-host Bootstrap/Leaflet and add SRI hashes to the CDN tags.
- [ ] Logging/monitoring and alerting (Sentry or similar); regular encrypted DB backups and a restore test.
- [ ] Re-test concurrent claims on your **real production database** (PostgreSQL/MySQL) under load.

## 4. Product / legal decisions
- [ ] Privacy policy + consent wording for collecting location, email and address; decide data-retention and deletion rules (GDPR/DPDP etc. as applicable).
- [ ] Food-safety disclaimer / terms of use (who is responsible for food quality and pickup).
- [ ] Decide whether the donor's display name should also be hidden before a claim (households may prefer "Anonymous donor").

## 5. Frontend verification (needs real devices/browsers)
- [ ] Open the app on a real phone (iOS Safari + Android Chrome) and click through register → post food → claim → pickup.
- [ ] Test with the network throttled/offline and with JavaScript disabled to see the error states.
- [ ] Run a Lighthouse/axe accessibility pass and fix anything it flags.
