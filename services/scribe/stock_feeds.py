"""Pharmacy stock feeds: today's nightly CSV and the real-time pharmacy API, behind one interface.

The scribe never knows which feed is live: both produce the same normalised readings, proven by one
contract test suite. `sync_stock` applies readings to `medicine_stock` (quantity and as_of only; it never
creates medicines), and the scribe shows `as_of` on every flag so a stale count is never shown as fact.

    feed = HttpStockFeed("https://pharmacy.internal/api", token)   # or CsvStockFeed(path)
    report = await sync_stock(pool, feed)
"""

import csv
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

import httpx
from psycopg_pool import AsyncConnectionPool
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential


@dataclass(frozen=True)
class StockReading:
    clinic: str  # clinic name as the pharmacy system knows it
    medicine: str  # generic name
    qty: int
    as_of: datetime


class StockFeed(Protocol):
    async def readings(self) -> list[StockReading]: ...


def _reading(clinic: str, medicine: str, qty: object, as_of: str) -> StockReading:
    quantity = int(str(qty))
    if quantity < 0:
        raise ValueError("negative stock")
    stamp = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("as_of must carry a timezone")
    return StockReading(clinic.strip(), medicine.strip(), quantity, stamp)


class CsvStockFeed:
    """Nightly file: columns clinic, medicine, qty, as_of (ISO 8601 with timezone)."""

    def __init__(self, path: Path) -> None:
        self._path = path

    async def readings(self) -> list[StockReading]:
        with self._path.open(newline="", encoding="utf-8") as f:
            return [_reading(r["clinic"], r["medicine"], r["qty"], r["as_of"]) for r in csv.DictReader(f)]


class HttpStockFeed:
    """Real-time pharmacy API: GET {base}/stock returns [{clinic, medicine, qty, as_of}, ...]."""

    def __init__(
        self, base_url: str, token: str, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url, headers={"Authorization": f"Bearer {token}"}, timeout=10, transport=transport
        )

    @retry(
        retry=retry_if_exception_type(httpx.TransportError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.2, max=2),
        reraise=True,
    )
    async def readings(self) -> list[StockReading]:
        response = await self._client.get("/stock")
        response.raise_for_status()
        rows: list[dict[str, Any]] = response.json()
        return [_reading(r["clinic"], r["medicine"], r["qty"], r["as_of"]) for r in rows]

    async def aclose(self) -> None:
        await self._client.aclose()


@dataclass
class SyncReport:
    updated: int = 0
    unknown: list[str] = field(default_factory=list)  # clinic/medicine pairs not in the formulary


async def sync_stock(pool: AsyncConnectionPool, feed: StockFeed) -> SyncReport:
    """Apply a feed to medicine_stock. Older readings never overwrite newer ones."""
    report = SyncReport()
    readings = await feed.readings()
    async with pool.connection() as conn, conn.transaction():
        for r in readings:
            cur = await conn.execute(
                "UPDATE medicine_stock ms SET qty = %s, as_of = %s FROM medicine m, clinic c"
                " WHERE ms.medicine_id = m.medicine_id AND ms.clinic_id = c.clinic_id"
                " AND lower(m.name) = lower(%s) AND lower(c.name) = lower(%s) AND ms.as_of <= %s",
                (r.qty, r.as_of, r.medicine, r.clinic, r.as_of),
            )
            if cur.rowcount:
                report.updated += cur.rowcount
            else:
                report.unknown.append(f"{r.clinic}/{r.medicine}")
    return report
