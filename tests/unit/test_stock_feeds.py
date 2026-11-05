"""Contract tests: the nightly CSV and the real-time API feeds must yield identical readings."""

import json
from datetime import UTC, datetime

import httpx
import pytest

from services.scribe.stock_feeds import CsvStockFeed, HttpStockFeed, StockReading

ROWS = [
    {"clinic": "Baner Clinic", "medicine": "Atorvastatin", "qty": 40, "as_of": "2026-11-03T06:00:00+05:30"},
    {"clinic": "Baner Clinic", "medicine": "Metformin", "qty": 0, "as_of": "2026-11-03T06:00:00+05:30"},
]
EXPECTED = [
    StockReading("Baner Clinic", "Atorvastatin", 40, datetime(2026, 11, 3, 0, 30, tzinfo=UTC)),
    StockReading("Baner Clinic", "Metformin", 0, datetime(2026, 11, 3, 0, 30, tzinfo=UTC)),
]


def csv_feed(tmp_path, rows=ROWS):
    path = tmp_path / "stock.csv"
    path.write_text(
        "clinic,medicine,qty,as_of\n"
        + "".join(f"{r['clinic']},{r['medicine']},{r['qty']},{r['as_of']}\n" for r in rows)
    )
    return CsvStockFeed(path)


def api_feed(rows=ROWS, *, fail_first=0):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        assert request.headers["Authorization"] == "Bearer token"
        if calls["n"] <= fail_first:
            raise httpx.ConnectError("pharmacy API unreachable")
        return httpx.Response(200, content=json.dumps(rows))

    return HttpStockFeed("https://pharmacy.test", "token", transport=httpx.MockTransport(handler)), calls


@pytest.mark.parametrize("kind", ["csv", "api"])
async def test_both_feeds_yield_identical_normalised_readings(kind, tmp_path):
    feed = csv_feed(tmp_path) if kind == "csv" else api_feed()[0]
    assert await feed.readings() == EXPECTED


@pytest.mark.parametrize("kind", ["csv", "api"])
@pytest.mark.parametrize(
    "bad",
    [{"qty": -1}, {"as_of": "2026-11-03T06:00:00"}, {"qty": "lots"}],  # negative, no timezone, not a number
)
async def test_both_feeds_reject_the_same_bad_data(kind, bad, tmp_path):
    rows = [{**ROWS[0], **bad}]
    feed = csv_feed(tmp_path, rows) if kind == "csv" else api_feed(rows)[0]
    with pytest.raises(ValueError):
        await feed.readings()


async def test_api_feed_retries_transient_network_errors():
    feed, calls = api_feed(fail_first=2)
    assert await feed.readings() == EXPECTED
    assert calls["n"] == 3
