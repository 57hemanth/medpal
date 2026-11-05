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
                " r.status AS reservation_status, c.name AS clinic_name,"
                " rx.status AS rx_status, rx.stop_reason, rx.stopped_at,"
                " (SELECT o.medicine_text FROM prescription o WHERE o.rx_id = rx.replaces_rx_id) AS replaces"
                " FROM prescription rx"
                " JOIN note_version n ON n.note_id = rx.note_id AND n.version = rx.note_version"
                " LEFT JOIN doctor d ON d.doctor_id = n.doctor_id"
                " LEFT JOIN patient p ON p.patient_id = rx.patient_id"
                " LEFT JOIN medicine m ON m.medicine_id = rx.medicine_id"
                " LEFT JOIN medicine_reservation r ON r.rx_id = rx.rx_id"
                " LEFT JOIN clinic c ON c.clinic_id = r.clinic_id"
                " ORDER BY (rx.status = 'active') DESC, n.signed_at DESC, rx.created_at DESC LIMIT 200"
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


# ---- changes a pharmacist makes ------------------------------------------------------------------


class InvalidChange(ValueError):
    """Shown to the person as is."""


ADJUSTMENT_KINDS = ("count", "delivery", "write_off")


async def adjust_stock(
    pool: AsyncConnectionPool, auth: AuthContext, *, medicine_id: str, kind: str, qty: int, reason: str
) -> dict[str, Any]:
    """Set the count on hand, add a delivery or write packs off, at the pharmacist's own clinic.
    The database function checks the role, the clinic and the numbers, and logs the change."""
    if auth["role"] != "pharmacist":
        raise NotAllowed("only a pharmacist adjusts stock")
    if kind not in ADJUSTMENT_KINDS:
        raise InvalidChange("Choose count, delivery or write-off")
    if not reason.strip():
        raise InvalidChange("Add a reason for the change")
    async with scoped(pool, auth) as conn:
        try:
            row = await (
                await conn.execute(
                    "SELECT adjust_stock(%s, %s, %s, %s) AS qty", (medicine_id, kind, qty, reason.strip())
                )
            ).fetchone()
        except Exception as exc:  # the function's own messages are written for people
            message = str(getattr(getattr(exc, "diag", None), "message_primary", "") or "")
            if message in (
                "quantity out of range",
                "cannot write off more than is on hand",
                "unknown medicine",
                "a reason is required",
            ):
                raise InvalidChange(message[0].upper() + message[1:]) from exc
            if "only a clinic pharmacist" in message:
                raise NotAllowed(message) from exc
            raise
        await audit.write(
            conn,
            auth,
            action="update",
            resource="medicine_stock",
            record_id=medicine_id,
            patient_id=None,
            purpose=f"stock {kind}",
        )
    return {"medicine_id": medicine_id, "qty": cast(dict[str, Any], row)["qty"]}


async def stock_history(
    pool: AsyncConnectionPool, auth: AuthContext, *, medicine_id: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    if auth["role"] not in ("pharmacist", "compliance"):
        raise NotAllowed("stock history is for the pharmacy")
    async with scoped(pool, auth) as conn:
        rows = await (
            await conn.execute(
                "SELECT a.adjustment_id::text, a.medicine_id::text, m.name AS medicine, a.kind,"
                " a.qty_before, a.qty_after, a.reason, a.made_at"
                " FROM stock_adjustment a JOIN medicine m ON m.medicine_id = a.medicine_id"
                " WHERE %(m)s::uuid IS NULL OR a.medicine_id = %(m)s::uuid"
                " ORDER BY a.made_at DESC LIMIT %(limit)s",
                {"m": medicine_id, "limit": max(1, min(limit, 200))},
            )
        ).fetchall()
    return _rows(rows)


MEDICINE_FIELDS = ("name", "composition", "manufacturer", "pack_size", "price_inr", "therapeutic_class")


def _clean_medicine(fields: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in MEDICINE_FIELDS:
        if key not in fields:
            continue
        value = fields[key]
        if isinstance(value, str):
            value = value.strip()[:200] or None
        out[key] = value
    if "name" in out and not out["name"]:
        raise InvalidChange("A medicine needs a name")
    if "composition" in out and not out["composition"]:
        raise InvalidChange("Add the composition, e.g. Paracetamol (500mg)")
    if out.get("price_inr") is not None and not (0 <= float(out["price_inr"]) <= 1_000_000):
        raise InvalidChange("Price must be between 0 and 10 lakh")
    return out


async def add_medicine(
    pool: AsyncConnectionPool, auth: AuthContext, fields: dict[str, Any]
) -> dict[str, Any]:
    if auth["role"] != "pharmacist":
        raise NotAllowed("only a pharmacist adds medicines")
    data = _clean_medicine(fields)
    if not data.get("name") or not data.get("composition"):
        raise InvalidChange("A medicine needs a name and a composition")
    columns = [*data.keys(), "source"]
    async with scoped(pool, auth) as conn:
        row = cast(
            dict[str, Any],
            await (
                await conn.execute(
                    f"INSERT INTO medicine ({', '.join(columns)})"  # noqa: S608  columns from a fixed list
                    f" VALUES ({', '.join(['%s'] * len(columns))}) RETURNING medicine_id::text",
                    (*data.values(), "clinic"),
                )
            ).fetchone(),
        )
        await audit.write(
            conn,
            auth,
            action="write",
            resource="medicine",
            record_id=row["medicine_id"],
            patient_id=None,
            purpose="add to catalogue",
        )
    return {"medicine_id": row["medicine_id"], **data, "source": "clinic"}


async def update_medicine(
    pool: AsyncConnectionPool, auth: AuthContext, medicine_id: str, fields: dict[str, Any]
) -> dict[str, Any]:
    if auth["role"] != "pharmacist":
        raise NotAllowed("only a pharmacist edits medicines")
    data = _clean_medicine(fields)
    if not data:
        raise InvalidChange("Nothing to change")
    assignments = ", ".join(f"{key} = %s" for key in data)
    async with scoped(pool, auth) as conn:
        cursor = await conn.execute(
            f"UPDATE medicine SET {assignments} WHERE medicine_id = %s",  # noqa: S608  fixed column list
            (*data.values(), medicine_id),
        )
        if cursor.rowcount != 1:
            raise LookupError("no such medicine")
        await audit.write(
            conn,
            auth,
            action="update",
            resource="medicine",
            record_id=medicine_id,
            patient_id=None,
            purpose="correct catalogue entry",
        )
    return {"medicine_id": medicine_id, **data}
