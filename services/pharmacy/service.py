"""Pharmacy: the medicine catalogue, clinic stock and restock needs, dispensing, and what patients see.

Stock counts come from the pharmacy's own system through the feed (services/scribe/stock_feeds.py);
MedPal never invents a count. It adds what the pharmacy can't see from its own system: what doctors
have prescribed and reserved, what is running low against that demand, and who is waiting to collect.
Row-level security decides every read: a pharmacist sees only their own clinic.
"""

from datetime import UTC, datetime, timedelta
from typing import Any, cast

from psycopg_pool import AsyncConnectionPool

from services.platform import audit
from services.platform.auth import AuthContext
from services.platform.db import scoped

STALE_AFTER = timedelta(hours=48)
LOW_STOCK_PACKS = 10  # at or below this many available packs, a medicine needs restocking
DEMAND_WINDOW_DAYS = 30
CATALOGUE_ROLES = frozenset({"doctor", "pharmacist", "desk", "compliance"})


class NotAllowed(PermissionError):
    pass


def _rows(rows: list[Any]) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], rows)


async def my_clinic(pool: AsyncConnectionPool, auth: AuthContext) -> dict[str, Any]:
    if auth["role"] != "pharmacist":
        raise NotAllowed("pharmacy workspace requires the pharmacist role")
    async with scoped(pool, auth) as conn:
        row = await (
            await conn.execute(
                "SELECT c.clinic_id::text, c.name, c.city FROM clinic c WHERE c.clinic_id = app_user_clinic()"
            )
        ).fetchone()
    if row is None:
        raise NotAllowed("this pharmacist is not assigned to a clinic")
    return cast(dict[str, Any], row)


async def catalogue(
    pool: AsyncConnectionPool, auth: AuthContext, *, query: str = "", limit: int = 100
) -> list[dict[str, Any]]:
    """Search by name, composition or class. Shows how many clinics have it available."""
    if auth["role"] not in CATALOGUE_ROLES:
        raise NotAllowed("the medicine catalogue is for clinical and pharmacy staff")
    pattern = f"%{query.strip().lower()}%"
    async with scoped(pool, auth) as conn:
        rows = await (
            await conn.execute(
                "SELECT m.medicine_id::text, m.name, m.composition, m.manufacturer, m.pack_size, m.price_inr,"
                " m.therapeutic_class, m.source,"
                " (SELECT count(*) FROM clinic c WHERE medicine_available(c.clinic_id, m.medicine_id) > 0)"
                "   AS clinics_available,"
                " (SELECT count(*) FROM clinic) AS clinics_total"
                " FROM medicine m"
                " WHERE %(q)s = '%%%%' OR lower(m.name) LIKE %(q)s OR lower(m.composition) LIKE %(q)s"
                " OR lower(coalesce(m.therapeutic_class, '')) LIKE %(q)s"
                " ORDER BY m.name LIMIT %(limit)s",
                {"q": pattern, "limit": max(1, min(limit, 500))},
            )
        ).fetchall()
    return _rows(rows)


def _stock_status(available: int, as_of: datetime | None, now: datetime) -> str:
    if as_of is None or now - as_of > STALE_AFTER:
        return "stale"
    if available <= 0:
        return "out_of_stock"
    return "low" if available <= LOW_STOCK_PACKS else "in_stock"


async def clinic_stock(pool: AsyncConnectionPool, auth: AuthContext) -> list[dict[str, Any]]:
    """Every formulary medicine at the pharmacist's clinic: count, reserved, available, demand, status.

    Sorted so what needs action comes first: out of stock, low and stale before healthy; within each, by
    prescriptions that couldn't be held (unmet), then by how often doctors prescribed it here in 30 days.
    """
    clinic = await my_clinic(pool, auth)
    async with scoped(pool, auth) as conn:
        rows = _rows(
            await (
                await conn.execute(
                    "SELECT m.medicine_id::text, m.name, m.composition, m.therapeutic_class, m.pack_size,"
                    " ms.qty, ms.as_of,"
                    " medicine_reserved(%(c)s, m.medicine_id) AS reserved,"
                    " medicine_available(%(c)s, m.medicine_id) AS available,"
                    " medicine_demand(%(c)s, m.medicine_id, %(days)s, false) AS demand,"
                    " medicine_demand(%(c)s, m.medicine_id, %(days)s, true) AS unmet"
                    " FROM medicine m"
                    " LEFT JOIN medicine_stock ms ON ms.medicine_id = m.medicine_id AND ms.clinic_id = %(c)s",
                    {"c": clinic["clinic_id"], "days": DEMAND_WINDOW_DAYS},
                )
            ).fetchall()
        )
    now = datetime.now(UTC)
    order = {"out_of_stock": 0, "low": 1, "stale": 2, "in_stock": 3}
    for row in rows:
        row["status"] = _stock_status(row["available"], row["as_of"], now)
    return sorted(rows, key=lambda r: (order[r["status"]], -r["unmet"], -r["demand"], r["name"]))


async def dispensing_queue(
    pool: AsyncConnectionPool, auth: AuthContext, *, status: str = "reserved"
) -> list[dict[str, Any]]:
    """Signed prescriptions held at this clinic, with who is collecting and who prescribed."""
    await my_clinic(pool, auth)
    async with scoped(pool, auth) as conn:
        rows = await (
            await conn.execute(
                "SELECT r.reservation_id::text, r.status, r.reserved_at, r.closed_at,"
                " p.name AS patient_name, rx.medicine_text, m.name AS medicine, m.pack_size,"
                " d.name AS doctor_name"
                " FROM medicine_reservation r"
                " JOIN prescription rx ON rx.rx_id = r.rx_id"
                " JOIN medicine m ON m.medicine_id = r.medicine_id"
                " LEFT JOIN patient p ON p.patient_id = r.patient_id"
                " LEFT JOIN doctor d ON d.doctor_id = r.doctor_id"
                " WHERE r.clinic_id = app_user_clinic() AND (%s = 'all' OR r.status = %s)"
                " ORDER BY r.reserved_at DESC LIMIT 300",
                (status, status),
            )
        ).fetchall()
    return _rows(rows)


async def dispense(pool: AsyncConnectionPool, auth: AuthContext, *, reservation_id: str) -> None:
    """Hand over: mark dispensed, take a pack off the count, and tell the patient (fixed template)."""
    clinic = await my_clinic(pool, auth)
    message = f"Your medicines are ready to collect at the {clinic['name']} pharmacy."
    async with scoped(pool, auth) as conn:
        done = await (
            await conn.execute("SELECT dispense_reservation(%s, %s) AS ok", (reservation_id, message))
        ).fetchone()
        if not done or not cast(dict[str, Any], done)["ok"]:
            raise LookupError("no reserved prescription with that id at your clinic")
        await audit.write(
            conn,
            auth,
            action="update",
            resource="medicine_reservation",
            record_id=reservation_id,
            patient_id=None,
            purpose="dispense",
        )


async def release(pool: AsyncConnectionPool, auth: AuthContext, *, reservation_id: str) -> None:
    """Not collected or not needed: return the pack to available stock."""
    await my_clinic(pool, auth)
    async with scoped(pool, auth) as conn:
        cur = await conn.execute(
            "UPDATE medicine_reservation"
            " SET status = 'released', closed_at = now(), closed_by = app_user_id()"
            " WHERE reservation_id = %s AND status = 'reserved' RETURNING patient_id::text",
            (reservation_id,),
        )
        row = await cur.fetchone()
        if row is None:
            raise LookupError("no reserved prescription with that id at your clinic")
        await audit.write(
            conn,
            auth,
            action="update",
            resource="medicine_reservation",
            record_id=reservation_id,
            patient_id=cast(dict[str, Any], row)["patient_id"],
            purpose="release",
        )


async def my_prescriptions(pool: AsyncConnectionPool, auth: AuthContext) -> list[dict[str, Any]]:
    """A patient's (or a consented caregiver's) prescriptions, with where they're held and their status."""
    async with scoped(pool, auth) as conn:
        rows = await (
            await conn.execute(
                "SELECT rx.rx_id::text, rx.medicine_text, m.name AS medicine, m.composition, m.pack_size,"
                " n.signed_at, d.name AS doctor_name, p.name AS patient_name,"
                " r.status AS reservation_status, c.name AS clinic_name"
                " FROM prescription rx"
                " JOIN note_version n ON n.note_id = rx.note_id AND n.version = rx.note_version"
                " LEFT JOIN doctor d ON d.doctor_id = n.doctor_id"
                " LEFT JOIN patient p ON p.patient_id = rx.patient_id"
                " LEFT JOIN medicine m ON m.medicine_id = rx.medicine_id"
                " LEFT JOIN medicine_reservation r ON r.rx_id = rx.rx_id"
                " LEFT JOIN clinic c ON c.clinic_id = r.clinic_id"
                " ORDER BY n.signed_at DESC LIMIT 200"
            )
        ).fetchall()
    return _rows(rows)


async def notifications(pool: AsyncConnectionPool, auth: AuthContext) -> list[dict[str, Any]]:
    async with scoped(pool, auth) as conn:
        rows = await (
            await conn.execute(
                "SELECT notification_id::text, kind, body, created_at, read_at FROM patient_notification"
                " ORDER BY created_at DESC LIMIT 50"
            )
        ).fetchall()
    return _rows(rows)


async def mark_read(pool: AsyncConnectionPool, auth: AuthContext, *, notification_id: str) -> None:
    async with scoped(pool, auth) as conn:
        await conn.execute(
            "UPDATE patient_notification SET read_at = now() WHERE notification_id = %s AND read_at IS NULL",
            (notification_id,),
        )
