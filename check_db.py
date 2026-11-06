"""Run from the project folder:  python check_db.py
Shows which database the app will really use and the exact connection error."""
from database import settings

settings.load_env_file()
if settings.ENV_FILE.exists():
    print("Settings file :", settings.ENV_FILE)
else:
    print("Settings file : NOT FOUND ->", settings.ENV_FILE)
    print("                (using db.env.example defaults = SQLite)")
print("DB_ENGINE     :", settings.get_engine_name())
uri = settings.build_database_uri()

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

print("Connection URL:", make_url(uri).render_as_string(hide_password=True))
try:
    with create_engine(uri).connect() as conn:
        print("CONNECTED. Server version:", conn.execute(text("SELECT VERSION()")).scalar()
              if not uri.startswith("sqlite") else "SQLite file")
except Exception as exc:
    print("\nCONNECTION FAILED:", type(exc).__name__)
    print(exc)