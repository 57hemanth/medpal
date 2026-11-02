# ADR-0002: Orchestrate workflows as LangGraph graphs with a Postgres checkpointer

- **Status:** accepted
- **Context:** Some runs must pause for a person, sometimes for minutes or hours: the patient picks a slot, or the doctor signs a note. A paused run must resume on **any** API replica with exactly the same state. Runs loop (clarify a symptom, re-offer a slot that filled up, redraft a rejected note) and must be replayable for audit. The API itself should be stateless behind a load balancer.
- **Options:**
  1. *A linear chain of LLM calls.* Cheapest to write, but there's no durable pause, loops are awkward and there's no replay. It can't wait for a doctor's signature at all.
  2. *A hand-written state machine over Postgres.* Full control, but checkpointing, interrupts and history would have to be rebuilt by hand.
  3. *LangGraph `StateGraph` + `langgraph-checkpoint-postgres` + `interrupt()` / `Command(resume=…)`.* Durable pauses, any-replica resume and per-step history out of the box.
- **Decision:** Option 3. The records ingest pipeline will stay a plain worker pipeline: it has no branching and no human step, so a graph adds nothing there. Checkpoint tables live in their own `langgraph` schema.
- **Revisit trigger:** a LangGraph release changes interrupt or checkpointer behaviour we rely on, or checkpoint storage can't be held down by a retention job.
- **Consequences:**
  - *Easier:* human-in-the-loop steps, a stateless API, replay.
  - *Harder:*
    - **A node that calls `interrupt()` re-runs from its start when resumed**, so such nodes must be side-effect free. Booking happens in the *next* node. This was verified with a minimal repro against the pinned version before any graph code was written.
    - State must stay lean (ids, not documents). A triage run measured **~12.8 KB of checkpoint payload** (~8.6 rows), so a retention job is needed at scale.
    - Framework upgrades need a changelog review.
- **Proof:**
  - `tests/unit/test_triage_graph.py` checks that the shortlist runs exactly once across pause and resume;
  - `tests/integration/test_triage_e2e.py::test_book_across_two_app_instances` pauses a run on one app instance and resumes it on another.
- **Versions pinned** (`uv.lock` is the source of truth): langgraph 1.2.19 · langgraph-checkpoint 4.3.1 · langgraph-checkpoint-postgres 3.2.0 · fastapi 0.162.0 · psycopg 3.3.6 · pydantic 2.14.2.
- **Checked on:** 2026-11-02
