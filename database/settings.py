"""Database settings: reads database/db.env (falling back to the committed
db.env.example) and real environment variables, and builds the SQLAlchemy
connection URI for SQLite, MySQL or PostgreSQL.

db.env may contain database passwords, so it is git-ignored. Copy
db.env.example to db.env to customise it.
"""
import os
from pathlib import Path
from urllib.parse import quote_plus

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
ENV_FILE = BASE_DIR / "db.env"
ENV_EXAMPLE = BASE_DIR / "db.env.example"

DEFAULT_PORTS = {"mysql": 3306, "postgresql": 5432}
ALIASES = {"sqlite3": "sqlite", "mariadb": "mysql", "postgres": "postgresql", "pg": "postgresql"}
SUPPORTED = ("sqlite", "mysql", "postgresql")


def load_env_file(path=None):
    """Load KEY=VALUE lines. Real environment variables always win."""
    path = Path(path) if path else (ENV_FILE if ENV_FILE.exists() else ENV_EXAMPLE)
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def env(name, default=""):
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def env_flag(name, default=False):
    value = os.environ.get(name)
    if value in (None, ""):
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def get_engine_name():
    name = env("DB_ENGINE", "sqlite").lower()
    name = ALIASES.get(name, name)
    if name not in SUPPORTED:
        raise RuntimeError(
            f"Unsupported DB_ENGINE '{name}'. Use one of: {', '.join(SUPPORTED)}.")
    return name


def build_database_uri():
    """Return the SQLAlchemy URI for the engine selected in db.env."""
    explicit = os.environ.get("DATABASE_URL")
    if explicit:
        if explicit.startswith("postgres://"):
            explicit = "postgresql://" + explicit[len("postgres://"):]
        return explicit

    engine = get_engine_name()
    if engine == "sqlite":
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        filename = Path(env("SQLITE_FILE", "foodshare.db")).name
        return "sqlite:///" + (DATA_DIR / filename).as_posix()

    user = quote_plus(env("DB_USER", "root"))
    password = quote_plus(env("DB_PASSWORD", ""))
    host = env("DB_HOST", "localhost")
    port = env("DB_PORT", str(DEFAULT_PORTS[engine]))
    name = env("DB_NAME", "foodshare")
    auth = f"{user}:{password}" if password else user
    if engine == "mysql":
        return f"mysql+pymysql://{auth}@{host}:{port}/{name}?charset=utf8mb4"
    return f"postgresql+psycopg2://{auth}@{host}:{port}/{name}"


def engine_options(uri):
    if uri.startswith("sqlite"):
        # wait for the write lock instead of failing instantly under concurrency
        return {"connect_args": {"timeout": 15}}
    return {"pool_pre_ping": True, "pool_recycle": 280}
