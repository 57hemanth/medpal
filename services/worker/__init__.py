"""Background worker: records ingest, pharmacy stock sync and appointment emails (arq on Redis).

    uv run arq services.worker.WorkerSettings

Only a document id is queued: the content stays in the object store and Postgres, inside the boundary.
A job id derived from the document id makes duplicate enqueues collapse into one job.
"""

from typing import Any

from arq import cron
from arq.connections import RedisSettings

from services.platform.config import get_settings
from services.platform.db import app_pool
from services.platform.tracing import PostgresSpanSink, trace_run
from services.records.service import ingest_record
from services.records.storage import build_object_store


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    pool = app_pool(settings)
    await pool.open()
    ctx["pool"] = pool
    ctx["store"] = build_object_store(settings)
    ctx["trace_sink"] = PostgresSpanSink(pool)


async def shutdown(ctx: dict[str, Any]) -> None:
    await ctx["pool"].close()


async def ingest_document(ctx: dict[str, Any], doc_id: str) -> str:
    settings = get_settings()
    sink = ctx.get("trace_sink")
    async with trace_run("ingest", doc_id, sink):
        return await ingest_record(
            ctx["pool"], ctx["store"], doc_id=doc_id, max_concurrency=settings.ingest_max_concurrency
        )


async def sync_pharmacy_stock(ctx: dict[str, Any]) -> dict[str, Any]:
    """Scheduled stock sync from whichever feed is configured (CSV today, the pharmacy API later)."""
    from pathlib import Path

    from services.scribe.stock_feeds import CsvStockFeed, HttpStockFeed, StockFeed, sync_stock

    settings = get_settings()
    feed: StockFeed
    if settings.pharmacy_feed == "csv" and settings.pharmacy_feed_path:
        feed = CsvStockFeed(Path(settings.pharmacy_feed_path))
    elif settings.pharmacy_feed == "api" and settings.pharmacy_api_url and settings.pharmacy_api_token:
        feed = HttpStockFeed(settings.pharmacy_api_url, settings.pharmacy_api_token)
    else:
        return {"skipped": "no pharmacy feed configured"}
    report = await sync_stock(ctx["pool"], feed)
    return {"updated": report.updated, "unknown": len(report.unknown)}


async def send_due_emails(ctx: dict[str, Any]) -> dict[str, Any]:
    """Appointment emails, when `MEDPAL_NOTIFY_DISPATCH=worker` (otherwise the API sends them)."""
    from services.notifications.dispatch import dispatch_due
    from services.notifications.email import build_email_sender

    settings = get_settings()
    if settings.notify_dispatch != "worker":
        return {"skipped": "emails are sent by the API (notify_dispatch != worker)"}
    report = await dispatch_due(ctx["pool"], build_email_sender(settings), settings)
    return {
        "sent": report.sent,
        "skipped": report.skipped,
        "retried": report.retried,
        "failed": report.failed,
    }


class WorkerSettings:
    functions = [ingest_document]
    cron_jobs = [
        cron(sync_pharmacy_stock, minute=set(range(0, 60, 15)), run_at_startup=True),
        cron(send_due_emails, second={0, 30}, unique=True),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_tries = 3
    job_timeout = 300
