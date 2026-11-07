"""FoodShare - Food Waste Reduction & Donation Platform.

Development:
    pip install -r requirements.txt
    flask --app app create-admin     # there is NO default admin account
    python app.py                    # http://127.0.0.1:5000

Production (APP_ENV=production, SECRET_KEY set in the environment):
    gunicorn "app:create_app()"

Switch database (SQLite <-> MySQL <-> PostgreSQL) via database/db.env.
"""
import os
import secrets
import sys
from datetime import timedelta
from pathlib import Path

import click
from flask import (Flask,abort, flash, g, redirect, render_template, request,
                   session, url_for)

import services
from api import API_ENDPOINTS, bp as api_bp
from auth import home_url, load_current_user, login_user, web_login_required
from database import (ADMIN, CLAIMED, DONOR, NGO, PENDING, PICKED_UP, User, db,
                      describe_database, init_db, settings)
from responses import fail
from security import generate_csrf_token, init_security
from services import ServiceError

ROOT = Path(__file__).resolve().parent
WEAK_SECRETS = {"", "change-me", "changeme", "secret", "dev-secret-change-me"}


def _load_secret_key(is_production):
    """SECRET_KEY always comes from the environment. Production refuses to
    start without a strong one; development generates and stores a random key
    in instance/ (git-ignored) so sessions survive restarts."""
    secret = os.environ.get("SECRET_KEY", "")
    if is_production:
        if len(secret) < 32 or secret.lower() in WEAK_SECRETS:
            raise RuntimeError(
                "SECRET_KEY must be set in the environment to a random value of at "
                "least 32 characters when APP_ENV=production. Generate one with: "
                "python -c \"import secrets; print(secrets.token_hex(32))\"")
        return secret
    if secret and secret.lower() not in WEAK_SECRETS:
        return secret
    key_file = ROOT / "instance" / "dev_secret.key"
    try:
        if key_file.exists():
            stored = key_file.read_text(encoding="utf-8").strip()
            if len(stored) >= 32:
                return stored
        key_file.parent.mkdir(exist_ok=True)
        stored = secrets.token_hex(32)
        key_file.write_text(stored, encoding="utf-8")
        return stored
    except OSError:
        return secrets.token_hex(32)


def create_app(config=None, database_uri=None):
    settings.load_env_file(ROOT / ".env")  # optional local file; real env vars win
    env_name = os.environ.get("APP_ENV", "development").strip().lower()
    is_production = env_name == "production"

    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=_load_secret_key(is_production),
        APP_ENV=env_name,
        IS_PRODUCTION=is_production,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=is_production,  # HTTPS only in production
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        MAX_CONTENT_LENGTH=64 * 1024,
        JSON_SORT_KEYS=False,
        CSRF_ENABLED=True,
    )
    if config:
        app.config.update(config)

    # Behind a reverse proxy request.remote_addr is the proxy's IP. Set
    # TRUSTED_PROXY_COUNT=1 (number of proxies YOU control) to use the real client IP.
    # Leave 0 otherwise: trusting X-Forwarded-For with no proxy lets attackers spoof IPs.
    proxies = int(os.environ.get("TRUSTED_PROXY_COUNT", "0") or 0)
    if proxies:
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=proxies, x_proto=proxies, x_host=proxies)

    init_db(app, database_uri)
    app.register_blueprint(api_bp)

    @app.before_request
    def _load_user():
        load_current_user()

    init_security(app)  # registers the CSRF check + security headers

    @app.context_processor
    def _inject():
        return dict(PENDING=PENDING, CLAIMED=CLAIMED, PICKED_UP=PICKED_UP,
                    DONOR=DONOR, NGO=NGO, ADMIN=ADMIN,
                    csrf_token=generate_csrf_token,
                    db_info=describe_database())

    # ------------------------------------------------------------------ CLI
    @app.cli.command("create-admin")
    @click.option("--name", default="Platform Admin", show_default=True)
    @click.option("--email", prompt="Admin email")
    @click.password_option("--password", envvar="FOODSHARE_ADMIN_PASSWORD",
                           prompt="Admin password (min 12 characters)")
    def create_admin_command(name, email, password):
        """Create an administrator account (the only way to get one)."""
        try:
            admin = services.create_admin(email, password, name)
        except ServiceError as err:
            raise click.ClickException(err.message)
        click.echo(f"Admin account created for {admin.email}.")

    # -------------------------------------------------------- public / auth
    @app.route("/")
    def index():
        if g.user:
            return redirect(home_url(g.user))
        return render_template("index.html", stats=services.get_stats())

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            try:
                user = services.register_user(
                    request.form.get("name"), request.form.get("email"),
                    request.form.get("password"), request.form.get("role"),
                    request.form.get("latitude"), request.form.get("longitude"),
                    request.form.get("address"))
            except ServiceError as err:
                flash(err.message, "danger")
                return render_template("register.html", form=request.form), 400
            login_user(user)
            if user.role == NGO:
                flash("Account created. An administrator must approve your NGO "
                      "before you can claim food.", "info")
            else:
                flash(f"Welcome, {user.name}!", "success")
            return redirect(home_url(user))
        return render_template("register.html", form={})

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            try:
                user = services.authenticate(request.form.get("email"),
                                             request.form.get("password"),
                                             request.remote_addr)
            except ServiceError as err:
                flash(err.message, "danger")
                return render_template("login.html"), err.status
            login_user(user)
            flash("Logged in successfully.", "success")
            return redirect(home_url(user))
        return render_template("login.html")

    @app.route("/logout", methods=["POST"])  # POST + CSRF: no logout via link/img
    def logout():
        session.clear()
        flash("You have been logged out.", "info")
        return redirect(url_for("index"))

    # ---------------------------------------------------------------- donor
    @app.route("/donor", methods=["GET", "POST"])
    @web_login_required(DONOR)
    def donor_dashboard():
        if request.method == "POST":  # no-JavaScript fallback
            try:
                services.create_listing(g.user, request.form.get("food_type"),
                                        request.form.get("quantity"),
                                        request.form.get("expiry_window"))
                flash("Your surplus food has been listed. NGOs nearby can now claim it.",
                      "success")
            except ServiceError as err:
                flash(err.message, "danger")
            return redirect(url_for("donor_dashboard"))
        boot = {"listings": [l.to_dict(viewer=g.user) for l in services.donor_listings(g.user)]}
        return render_template("donor.html", boot=boot)

    @app.route("/donor/cancel/<int:listing_id>", methods=["POST"])
    @web_login_required(DONOR)
    def cancel_listing(listing_id):
        try:
            services.withdraw_listing(g.user, listing_id)
            flash("Listing withdrawn.", "info")
        except ServiceError as err:
            flash(err.message, "warning")
        return redirect(url_for("donor_dashboard"))

    # ------------------------------------------------------------------ NGO
    @app.route("/ngo")
    @web_login_required(NGO)
    def ngo_dashboard():
        if not g.user.is_approved:
            return render_template("ngo_pending.html")
        radius = services.parse_radius(request.args.get("radius"))
        boot = {
            "radius": radius,
            "me": {"name": g.user.name, "latitude": g.user.latitude,
                   "longitude": g.user.longitude},
            "nearby": [l.to_dict(viewer=g.user, distance_km=d)
                       for l, d in services.nearby_listings(g.user, radius)],
            "mine": [l.to_dict(viewer=g.user) for l in services.claimed_listings(g.user)],
        }
        return render_template("ngo.html", boot=boot, radius=radius)

    @app.route("/ngo/claim/<int:listing_id>", methods=["POST"])
    @web_login_required(NGO)
    def claim_listing(listing_id):
        try:
            services.claim_listing(g.user, listing_id)
            flash("Food claimed! Exact pickup details are shown under 'My claimed pickups'.",
                  "success")
        except ServiceError as err:
            flash(err.message, "warning")
        return redirect(url_for("ngo_dashboard"))

    @app.route("/ngo/pickup/<int:listing_id>", methods=["POST"])
    @web_login_required(NGO)
    def mark_picked_up(listing_id):
        try:
            services.mark_picked_up(g.user, listing_id)
            flash("Marked as picked up. Thank you for reducing food waste!", "success")
        except ServiceError as err:
            flash(err.message, "warning")
        return redirect(url_for("ngo_dashboard"))

    # ---------------------------------------------------------------- admin
    @app.route("/admin")
    @web_login_required(ADMIN)
    def admin_panel():
        return render_template("admin.html",
                               users=User.query.order_by(User.id).all(),
                               listings=services.all_listings(),
                               stats=services.get_stats(),
                               pending=services.pending_ngos())

    @app.route("/admin/ngos/<int:user_id>/<action>", methods=["POST"])
    @web_login_required(ADMIN)
    def review_ngo(user_id, action):
        if action not in ("approve", "revoke"):
            abort(404)
        try:
            ngo = services.set_ngo_approval(g.user, user_id, action == "approve")
            flash(f"{ngo.name} {'approved' if ngo.is_approved else 'approval revoked'}.", "success")
        except ServiceError as err:
            flash(err.message, "warning")
        return redirect(url_for("admin_panel"))


    @app.route("/analytics")
    @web_login_required()
    def analytics():
        return render_template("analytics.html", data=services.analytics_for(g.user))

    @app.route("/api/docs")
    def api_docs():
        return render_template("api_docs.html", endpoints=API_ENDPOINTS)

    # --------------------------------------------------------------- errors
    def _is_api():
        return request.path.startswith("/api/")

    @app.errorhandler(403)
    def forbidden(_):
        if _is_api():
            return fail("forbidden", "You don't have access to this resource.", 403)
        return render_template("error.html", code=403,
                               message="You don't have access to this page."), 403

    @app.errorhandler(404)
    def not_found(_):
        if _is_api():
            return fail("not_found", "That API endpoint or record doesn't exist.", 404)
        return render_template("error.html", code=404,
                               message="That page or record doesn't exist."), 404

    @app.errorhandler(405)
    def not_allowed(_):
        if _is_api():
            return fail("method_not_allowed", "That HTTP method isn't supported here.", 405)
        return render_template("error.html", code=405,
                               message="That action isn't supported here."), 405

    @app.errorhandler(413)
    def too_large(_):
        if _is_api():
            return fail("payload_too_large", "Request body is too large.", 413)
        return render_template("error.html", code=413,
                               message="That request was too large."), 413

    @app.errorhandler(500)
    def server_error(_):
        db.session.rollback()
        if _is_api():
            return fail("server_error", "Something went wrong on our side.", 500)
        return render_template("error.html", code=500,
                               message="Something went wrong on our side."), 500

    return app


if __name__ == "__main__":
    application = create_app()
    if application.config["IS_PRODUCTION"]:
        sys.exit("APP_ENV=production: do not use the development server. "
                 "Run: gunicorn \"app:create_app()\"")
    with application.app_context():
        if not User.query.filter_by(role=ADMIN).first():
            print("\n  No admin account exists yet. Create one with:\n"
                  "      flask --app app create-admin\n")
    application.run(debug=application.config["APP_ENV"] == "development")
