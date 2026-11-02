"""Integration fixtures: real Postgres from docker-compose, in a separate `<db>_test` database
so tests never write into the dev data. Skips the whole module if Postgres is unreachable."""

import os
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql

from services.platform.config import get_settings
from services.platform.db import app_pool


def _with_dbname(url: str, dbname: str) -> str:
    """Return the same postgresql:// URL pointing at another database (URL form, for Alembic too)."""
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=f"/{dbname}"))


def _test_database_url() -> str:
    dev_url = get_settings().database_url
    name = urlsplit(dev_url).path.lstrip("/") or "medpal"
    return _with_dbname(dev_url, f"{name}_test")


def _ensure_test_database(test_url: str) -> bool:
    """Create the test database if missing. Returns False when Postgres is unreachable."""
    test_db = urlsplit(test_url).path.lstrip("/")
    try:
        with psycopg.connect(_with_dbname(test_url, "postgres"), autocommit=True, connect_timeout=2) as conn:
            exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (test_db,)).fetchone()
            if not exists:
                conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(test_db)))
        return True
    except psycopg.OperationalError:
        return False


@pytest.fixture(scope="session", autouse=True)
def database() -> None:
    test_url = os.environ.get("MEDPAL_TEST_DATABASE_URL") or _test_database_url()
    if not _ensure_test_database(test_url):
        pytest.skip("Postgres not reachable: run `make up` first", allow_module_level=True)
    os.environ["MEDPAL_DATABASE_URL"] = test_url
    get_settings.cache_clear()  # every later get_settings() (app lifespan, pools) sees the test DB
    command.upgrade(Config("alembic.ini"), "head")


@pytest.fixture
async def pool():
    p = app_pool(get_settings())
    await p.open()
    yield p
    await p.close()


@pytest.fixture
def world() -> dict[str, str]:
    """A fresh, isolated clinic/doctor/specialty/patient/user set per test (unique names and ids)."""
    tag = uuid.uuid4().hex[:8]
    ids = {k: str(uuid.uuid4()) for k in ("clinic", "specialty", "doctor", "patient", "user", "slot")}
    ids["specialty_name"] = f"Test Specialty {tag}"
    starts = datetime.now(UTC) + timedelta(days=1)
    with psycopg.connect(get_settings().database_url) as conn, conn.transaction():
        conn.execute(
            "INSERT INTO clinic (clinic_id, name, city, district, opens_at, closes_at)"
            " VALUES (%s, %s, 'Pune', 'Pune', '09:00', '18:00')",
            (ids["clinic"], f"Clinic {tag}"),
        )
        conn.execute(
            "INSERT INTO specialty (specialty_id, name) VALUES (%s, %s)",
            (ids["specialty"], ids["specialty_name"]),
        )
        conn.execute(
            "INSERT INTO doctor (doctor_id, name, specialty_id) VALUES (%s, %s, %s)",
            (ids["doctor"], f"Dr {tag}", ids["specialty"]),
        )
        conn.execute(
            "INSERT INTO slot (slot_id, doctor_id, clinic_id, starts_at, capacity)"
            " VALUES (%s, %s, %s, %s, 1)",
            (ids["slot"], ids["doctor"], ids["clinic"], starts),
        )
        conn.execute("INSERT INTO patient (patient_id, name) VALUES (%s, %s)", (ids["patient"], f"P {tag}"))
        conn.execute(
            "INSERT INTO app_user (user_id, role, patient_id) VALUES (%s, 'patient', %s)",
            (ids["user"], ids["patient"]),
        )
    return ids
