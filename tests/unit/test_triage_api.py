"""Triage API contract with the in-memory graph: auth, thread ownership, run/resume."""

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver

from services.agent.triage.graph import build_triage_graph
from services.api.main import create_app
from tests.unit.test_triage_graph import FakeTriageTools, cand

PRIYA = {"X-Dev-User-Id": "u-priya", "X-Dev-Role": "patient", "X-Dev-Patient-Id": "p-priya"}
RAVI = {"X-Dev-User-Id": "u-ravi", "X-Dev-Role": "patient", "X-Dev-Patient-Id": "p-ravi"}


@pytest.fixture
async def client():
    graph = build_triage_graph(FakeTriageTools([cand("s1", "d1"), cand("s2", "d2")])).compile(
        checkpointer=InMemorySaver()
    )
    app = create_app(triage_graph=graph)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


async def test_requires_identity(client):
    r = await client.post("/triage", json={"text": "knee pain"})
    assert r.status_code == 401


async def test_book_flow(client):
    r = await client.post("/triage", json={"text": "knee pain for a week"}, headers=PRIYA)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "awaiting_choice"
    assert len(body["candidates"]) == 2

    r = await client.post(
        f"/triage/{body['thread_id']}/resume",
        json={"slot_id": "s1", "idempotency_key": "key-00000001"},
        headers=PRIYA,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "booked"

    # The run is finished; resuming again is a conflict, not a second booking.
    r = await client.post(
        f"/triage/{body['thread_id']}/resume",
        json={"slot_id": "s1", "idempotency_key": "key-00000001"},
        headers=PRIYA,
    )
    assert r.status_code == 409


async def test_cannot_resume_someone_elses_thread(client):
    r = await client.post("/triage", json={"text": "knee pain"}, headers=PRIYA)
    thread = r.json()["thread_id"]
    r = await client.post(
        f"/triage/{thread}/resume", json={"slot_id": "s1", "idempotency_key": "key-00000002"}, headers=RAVI
    )
    assert r.status_code == 403


async def test_unknown_thread(client):
    r = await client.post(
        "/triage/nope/resume", json={"slot_id": "s1", "idempotency_key": "key-00000003"}, headers=PRIYA
    )
    assert r.status_code == 404


async def test_emergency_response(client):
    r = await client.post("/triage", json={"text": "sudden chest pain"}, headers=PRIYA)
    assert r.json()["status"] == "emergency"
    assert r.json()["handoff_ticket_id"]


async def test_non_patient_cannot_start_triage_yet(client):
    desk = {"X-Dev-User-Id": "u-meena", "X-Dev-Role": "desk"}
    r = await client.post("/triage", json={"text": "knee pain"}, headers=desk)
    assert r.status_code == 403
