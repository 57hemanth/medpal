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
class StockFlag:
    medicine: str
    status: Status
    medicine_id: str | None = None
    qty: int | None = None
    as_of: str | None = None

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
                        "SELECT m.medicine_id::text AS medicine_id, ms.qty, ms.as_of FROM medicine m"
                        " LEFT JOIN medicine_stock ms ON ms.medicine_id = m.medicine_id AND ms.clinic_id = %s"
                        " WHERE lower(m.name) = lower(%s) OR lower(m.composition) LIKE lower(%s) || ' %%'"
                        " ORDER BY (lower(m.name) = lower(%s)) DESC LIMIT 1",
                        (clinic_id, name, name, name),
                    )
                ).fetchone()
                if row is None:
                    out.append(StockFlag(name, "not_in_formulary"))
                    continue
                r = cast(dict[str, Any], row)
                as_of = r["as_of"]
                if r["qty"] is None or as_of is None or now - as_of > STALE_AFTER:
                    status: Status = "stale"
                else:
                    status = "in_stock" if r["qty"] > 0 else "out_of_stock"
                out.append(
                    StockFlag(
                        name,
                        status,
                        r["medicine_id"],
                        r["qty"],
                        as_of.isoformat() if as_of is not None else None,
                    )
                )
        return out
