import os
from pathlib import Path

import pytest

# Integration tests run against a dedicated test database, never the dev database.
from tests.db_safety import require_test_url

_TEST_URL = require_test_url(os.environ.get("TEST_DATABASE_URL"))
os.environ["DATABASE_URL"] = _TEST_URL  # tests wipe this database; never the dev one
os.environ["LLM_API_KEY"] = ""  # tests never call a real LLM
# Access control is exercised in tests: a per-run random API token and an enabled, token-protected reset.
import secrets  # noqa: E402

API_TOKEN = secrets.token_urlsafe(24)
ADMIN_TOKEN = secrets.token_urlsafe(24)
os.environ["API_TOKEN"] = API_TOKEN
os.environ["ENABLE_DATA_RESET"] = "true"
os.environ["ADMIN_TOKEN"] = ADMIN_TOKEN
AUTH = {"Authorization": f"Bearer {API_TOKEN}"}

ROOT = Path(__file__).resolve().parent.parent
DEMO_CSV = ROOT / "app" / "assets" / "data" / "synthetic_assessments.csv"

HEADER = ("school,student_id,grade,class,subject,topic_id,topic_name,assessment_id,assessment_type,"
          "assessment_date,comparison_group,item_id,score,max_score,textbook_id,teaching_hours")


def make_csv(rows: list[str], header: str = HEADER) -> bytes:
    return ("\n".join([header, *rows]) + "\n").encode("utf-8")


@pytest.fixture(scope="session")
def migrated_db():
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text

    from app.db import get_engine

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    command.upgrade(cfg, "head")  # proves the system starts from an empty database
    return engine


@pytest.fixture()
def client(migrated_db):
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    from app.main import app

    with migrated_db.begin() as conn:
        tables = conn.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename <> 'alembic_version'")).scalars().all()
        conn.execute(text("TRUNCATE " + ", ".join(tables) + " RESTART IDENTITY CASCADE"))
    with TestClient(app, headers=AUTH) as c:
        yield c
