"""Integration fixtures: real Postgres from docker-compose. Skips the whole module if unreachable."""

import uuid
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from services.platform.config import get_settings
from services.platform.db import app_pool


def _db_available() -> bool:
    try:
        with psycopg.connect(get_settings().database_url, connect_timeout=2):
            return True
    except psycopg.OperationalError:
        return False


@pytest.fixture(scope="session", autouse=True)
def database() -> None:
    if not _db_available():
        pytest.skip("Postgres not reachable: run `make up` first", allow_module_level=True)
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
