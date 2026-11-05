"""Traces land in Postgres from real API runs; only compliance may read the metrics."""

import uuid

import httpx
import psycopg
import pytest

from services.api.main import create_app
from services.platform.tracing import RUN_SPAN

pytestmark = pytest.mark.integration


async def test_api_runs_are_traced_and_metrics_are_compliance_only(world, admin_url):
    compliance = str(uuid.uuid4())
    with psycopg.connect(admin_url) as conn, conn.transaction():
        conn.execute("INSERT INTO app_user (user_id, role) VALUES (%s, 'compliance')", (compliance,))
    patient = {"X-Dev-User-Id": world["user"], "X-Dev-Role": "patient", "X-Dev-Patient-Id": world["patient"]}
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://t") as client,
    ):
        r = await client.post("/triage", json={"text": "sudden crushing chest pain"}, headers=patient)
        thread = r.json()["thread_id"]
        assert (await client.get("/api/ops/metrics", headers=patient)).status_code == 403
        m = await client.get(
            "/api/ops/metrics", headers={"X-Dev-User-Id": compliance, "X-Dev-Role": "compliance"}
        )
    assert m.status_code == 200
    body = m.json()
    assert any(r["workflow"] == "triage" and r["runs"] >= 1 for r in body["runs"])
    assert "cost per consultation" in body["cost_formula"]
    with psycopg.connect(admin_url) as conn:
        names = {row[0] for row in conn.execute("SELECT name FROM trace_span WHERE trace_id = %s", (thread,))}
        stored = " ".join(
            str(v)
            for row in conn.execute("SELECT * FROM trace_span WHERE trace_id = %s", (thread,))
            for v in row
        )
    assert {RUN_SPAN, "intake", "red_flag_rules", "emergency_handoff"} <= names
    assert "chest" not in stored  # metadata only: the patient's words never reach the trace store
