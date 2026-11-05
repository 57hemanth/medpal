"""Stock flags for medicines in a draft note, and grounding of medicines in the transcript.

Stock arrives as a nightly feed today and from an API later; the scribe only sees `StockSource`, so
switching adapters never touches the graph. A flag always carries `as_of`: a stale count is shown as
stale, never as a fact. The pharmacist and doctor decide what to dispense; software never substitutes.
"""

import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol, cast

from psycopg_pool import AsyncConnectionPool

from services.platform.auth import AuthContext
from services.platform.db import scoped

STALE_AFTER = timedelta(hours=48)
Status = Literal["in_stock", "out_of_stock", "stale", "not_in_formulary"]


@dataclass(frozen=True)
class Alternative:
    """Something the doctor may choose instead. Listed only; nothing is ever substituted automatically."""

    medicine: str
    kind: Literal["same_composition", "same_class", "other_clinic"]
    available: int
    clinic: str | None = None  # for "other_clinic"


@dataclass(frozen=True)
class StockFlag:
    medicine: str
    status: Status
    medicine_id: str | None = None
    qty: int | None = None  # available packs: the feed's count minus active reservations
    as_of: str | None = None
    alternatives: tuple[Alternative, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class StockSource(Protocol):
    async def formulary_names(self) -> list[str]: ...

    async def flags(
        self, auth: AuthContext, *, encounter_id: str, medicines: list[str]
    ) -> list[StockFlag]: ...


def ground_medicines(
    transcript: str, model_medicines: list[str], formulary: list[str]
) -> tuple[list[str], list[str]]:
    """(grounded, rejected). A medicine is kept only if the transcript names it.

    Formulary names found in the transcript are added by code, so stock flags work even without a
    model. Anything the model proposes that the doctor never said is rejected and shown as rejected:
    the model structures the note, it never prescribes.
    """
    lowered = transcript.lower()

    def said(name: str) -> bool:
        return re.search(rf"(?<![a-z]){re.escape(name.lower())}(?![a-z])", lowered) is not None

    grounded = [name for name in formulary if said(name)]
    rejected = []
    for proposed in model_medicines:
        if said(proposed):
            if proposed.lower() not in {g.lower() for g in grounded}:
                grounded.append(proposed)
        else:
            rejected.append(proposed)
    return grounded, rejected


class PostgresStockSource:
    """Reads the formulary and per-clinic stock that the nightly feed (or later the API) maintains."""

    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def formulary_names(self) -> list[str]:
        async with self._pool.connection() as conn:
            rows = await (await conn.execute("SELECT name FROM medicine ORDER BY name")).fetchall()
        return [cast(dict[str, Any], r)["name"] for r in rows]

    async def flags(self, auth: AuthContext, *, encounter_id: str, medicines: list[str]) -> list[StockFlag]:
        if not medicines:
            return []
        async with scoped(self._pool, auth) as conn:
            clinic = await (
                await conn.execute(
                    "SELECT s.clinic_id::text AS clinic_id FROM encounter e"
                    " JOIN appointment a ON a.appt_id = e.appt_id JOIN slot s ON s.slot_id = a.slot_id"
                    " WHERE e.encounter_id = %s",
                    (encounter_id,),
                )
            ).fetchone()
            if clinic is None:
                raise PermissionError("encounter is not visible")
            clinic_id = cast(dict[str, Any], clinic)["clinic_id"]
            out: list[StockFlag] = []
            now = datetime.now(UTC)
            for name in medicines:
                row = await (
                    await conn.execute(
                        "SELECT m.medicine_id::text AS medicine_id, m.name, m.composition,"
                        " m.therapeutic_class, ms.as_of, medicine_available(%s, m.medicine_id) AS available"
                        " FROM medicine m"
                        " LEFT JOIN medicine_stock ms ON ms.medicine_id = m.medicine_id AND ms.clinic_id = %s"
                        " WHERE lower(m.name) = lower(%s) OR lower(m.composition) LIKE lower(%s) || ' %%'"
                        " ORDER BY (lower(m.name) = lower(%s)) DESC LIMIT 1",
                        (clinic_id, clinic_id, name, name, name),
                    )
                ).fetchone()
                if row is None:
                    out.append(StockFlag(name, "not_in_formulary"))
                    continue
                r = cast(dict[str, Any], row)
                as_of = r["as_of"]
                if as_of is None or now - as_of > STALE_AFTER:
                    status: Status = "stale"
                else:
                    status = "in_stock" if r["available"] > 0 else "out_of_stock"
                alternatives = await _alternatives(conn, clinic_id, r) if status != "in_stock" else ()
                out.append(
                    StockFlag(
                        name,
                        status,
                        r["medicine_id"],
                        r["available"],
                        as_of.isoformat() if as_of is not None else None,
                        alternatives,
                    )
                )
        return out


async def _alternatives(conn: Any, clinic_id: str, medicine: dict[str, Any]) -> tuple[Alternative, ...]:
    """What the doctor could choose instead, most interchangeable first:

    1. the same composition under another name, in stock here (a generic equivalent);
    2. the same therapeutic class, in stock here (a different medicine: a clinical decision);
    3. the same medicine, in stock at another clinic in the same city.
    """
    found: list[Alternative] = []
    rows = await (
        await conn.execute(
            "SELECT m.name, m.composition = %(comp)s AS same_comp,"
            " medicine_available(%(clinic)s, m.medicine_id) AS avail"
            " FROM medicine m"
            " WHERE m.medicine_id <> %(id)s::uuid"
            " AND (m.composition = %(comp)s OR (%(cls)s::text IS NOT NULL AND m.therapeutic_class = %(cls)s))"
            " ORDER BY same_comp DESC, avail DESC, m.name LIMIT 6",
            {
                "comp": medicine["composition"],
                "cls": medicine["therapeutic_class"],
                "id": medicine["medicine_id"],
                "clinic": clinic_id,
            },
        )
    ).fetchall()
    for row in rows:
        r = cast(dict[str, Any], row)
        if r["avail"] > 0:
            kind: Literal["same_composition", "same_class"] = (
                "same_composition" if r["same_comp"] else "same_class"
            )
            found.append(Alternative(r["name"], kind, r["avail"]))
    elsewhere = await (
        await conn.execute(
            "SELECT c.name, medicine_available(c.clinic_id, %s) AS avail FROM clinic c"
            " WHERE c.clinic_id <> %s AND c.city = (SELECT city FROM clinic WHERE clinic_id = %s)"
            " AND medicine_available(c.clinic_id, %s) > 0"
            " ORDER BY avail DESC, c.name LIMIT 2",
            (medicine["medicine_id"], clinic_id, clinic_id, medicine["medicine_id"]),
        )
    ).fetchall()
    for row in elsewhere:
        r = cast(dict[str, Any], row)
        found.append(Alternative(medicine["name"], "other_clinic", r["avail"], r["name"]))
    return tuple(found[:5])
