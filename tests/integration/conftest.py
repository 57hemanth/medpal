"""Integration fixtures: real Postgres from docker-compose, in a separate `<db>_test` database
that is dropped and rebuilt from migrations at the start of every run (hermetic, never touches dev data).

Two connections, on purpose:
  * `admin_url` (owner role) sets up fixtures and verifies results: it bypasses RLS, like an operator.
  * the app settings (`medpal_app`, non-superuser) are what the code under test uses: RLS applies.
Skips the whole module if Postgres is unreachable.
"""

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
    return urlunsplit(urlsplit(url)._replace(path=f"/{dbname}"))


def _test_name(url: str) -> str:
    return (urlsplit(url).path.lstrip("/") or "medpal") + "_test"


def _recreate_test_database(owner_url: str, test_db: str) -> bool:
    """Drop and create the test database. Returns False when Postgres is unreachable."""
    try:
        with psycopg.connect(_with_dbname(owner_url, "postgres"), autocommit=True, connect_timeout=2) as conn:
            conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(test_db)))
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(test_db)))
        return True
    except psycopg.OperationalError:
        return False


@pytest.fixture(scope="session", autouse=True)
def database() -> None:
    settings = get_settings()
    test_db = _test_name(settings.migration_database_url)
    if not _recreate_test_database(settings.migration_database_url, test_db):
        pytest.skip("Postgres not reachable: run `make up` first", allow_module_level=True)
    os.environ["MEDPAL_DATABASE_URL"] = _with_dbname(settings.database_url, test_db)
    os.environ["MEDPAL_MIGRATION_DATABASE_URL"] = _with_dbname(settings.migration_database_url, test_db)
    get_settings.cache_clear()  # every later get_settings() (app lifespan, pools) sees the test DB
    command.upgrade(Config("alembic.ini"), "head")


@pytest.fixture
def admin_url() -> str:
    """Owner connection for fixtures and assertions (bypasses RLS). Never what the app uses."""
    return get_settings().migration_database_url


@pytest.fixture
async def pool():
    p = app_pool(get_settings())
    await p.open()
    yield p
    await p.close()


@pytest.fixture
def world(admin_url: str) -> dict[str, str]:
    """A fresh, isolated clinic/doctor/specialty/patient/user set per test (unique names and ids)."""
    tag = uuid.uuid4().hex[:8]
    ids = {k: str(uuid.uuid4()) for k in ("clinic", "specialty", "doctor", "patient", "user", "slot")}
    ids["specialty_name"] = f"Test Specialty {tag}"
    starts = datetime.now(UTC) + timedelta(days=1)
    with psycopg.connect(admin_url) as conn, conn.transaction():
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


@pytest.fixture
def gm_world(admin_url: str) -> dict[str, str]:
    """A fresh General Medicine doctor with the earliest slot, so the stub specialty finds it first."""
    ids = {k: str(uuid.uuid4()) for k in ("clinic", "doctor", "slot", "patient", "user")}
    with psycopg.connect(admin_url) as conn, conn.transaction():
        conn.execute("INSERT INTO specialty (name) VALUES ('General Medicine') ON CONFLICT (name) DO NOTHING")
        spec = conn.execute("SELECT specialty_id FROM specialty WHERE name = 'General Medicine'").fetchone()
        assert spec is not None
        conn.execute(
            "INSERT INTO clinic (clinic_id, name, city, district, opens_at, closes_at)"
            " VALUES (%s, 'E2E Clinic', 'Pune', 'Pune', '09:00', '18:00')",
            (ids["clinic"],),
        )
        conn.execute(
            "INSERT INTO doctor (doctor_id, name, specialty_id) VALUES (%s, 'Dr E2E', %s)",
            (ids["doctor"], spec[0]),
        )
        conn.execute(
            "INSERT INTO slot (slot_id, doctor_id, clinic_id, starts_at) VALUES (%s, %s, %s, %s)",
            (ids["slot"], ids["doctor"], ids["clinic"], datetime.now(UTC) + timedelta(minutes=2)),
        )
        conn.execute("INSERT INTO patient (patient_id, name) VALUES (%s, 'E2E Patient')", (ids["patient"],))
        conn.execute(
            "INSERT INTO app_user (user_id, role, patient_id) VALUES (%s, 'patient', %s)",
            (ids["user"], ids["patient"]),
        )
    return ids
