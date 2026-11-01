"""SQLAlchemy instance and database initialisation."""
import sqlite3
from pathlib import Path

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event
from sqlalchemy.engine import Engine

from . import settings

db = SQLAlchemy()


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _record):
    """SQLite ignores FOREIGN KEY constraints unless this pragma is set."""
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def init_db(app, uri=None):
    """Configure the database from database/db.env, create tables, seed demo data."""
    settings.load_env_file()
    uri = uri or settings.build_database_uri()
    app.config["SQLALCHEMY_DATABASE_URI"] = uri
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = settings.engine_options(uri)
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)

    from . import models, seed  # noqa: F401  (models must load before create_all)

    demo_enabled = settings.env_flag("SEED_DEMO", False)
    is_production = bool(app.config.get("IS_PRODUCTION"))
    if demo_enabled and is_production:
        app.logger.warning("SEED_DEMO is ignored because APP_ENV=production.")
    app.config["SHOW_DEMO_HINT"] = demo_enabled and not is_production

    with app.app_context():
        try:
            db.create_all()
        except Exception as exc:  # connection / driver problems
            raise RuntimeError(
                f"Could not connect to the {settings.get_engine_name()} database "
                f"({exc.__class__.__name__}). Check database/db.env - for MySQL "
                "install PyMySQL, for PostgreSQL install psycopg2-binary, and make "
                "sure the server is running and the database exists.") from exc
        if app.config["SHOW_DEMO_HINT"]:
            seed.seed_demo()


def describe_database():
    """Safe, public description of the active database (no passwords/paths)."""
    engine = db.engine
    url = engine.url
    dialect = engine.dialect.name
    if dialect == "sqlite":
        name = Path(url.database or ":memory:").name
        host = "local file"
    else:
        name = url.database
        host = url.host
    return {"engine": dialect, "driver": url.drivername, "database": name, "host": host}
