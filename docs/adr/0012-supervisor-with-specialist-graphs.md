# ADR-0012: A supervisor that delegates to specialist graphs, not one agent with every tool

- **Status:** accepted
- **Context:** People don't separate their needs by product area. A patient writes "my knee has hurt for a week, and what was my LDL last time?"; a doctor pastes a transcript and asks for the patient's last HbA1c. One assistant entry point has to reach triage, records and the scribe, which already exist as separate graphs with their own pauses, safety rules, ownership checks and audit. Combining them must not weaken any of those.
- **Options:**
  1. *One agent with every tool.* Simple to start, but the tool list grows, prompts carry every rule, and a model choosing tools becomes the safety boundary.
  2. *Specialists as nested subgraphs.* One run, but a pause in any specialist pauses the whole run, and resuming needs the supervisor to understand every specialist's interrupt.
  3. **A supervisor that plans, then fans out with `Send` to specialists running as their own durable threads.** Each keeps its endpoint, pause/resume, ownership check and audit; the supervisor returns their results and thread ids.
- **Decision:** Option 3 (`services/agent/supervisor/`, `POST /api/assistant`):
  - **Safety before routing:** red-flag rules check the whole message first. A patient emergency goes to triage alone, and no model sees the text.
  - **The model only labels clauses.** The message is split into numbered clauses and a small-tier model returns (clause number, specialist) pairs. Specialists always receive the person's own words, so the model can't rewrite a request, inject instructions or name another patient. If the model fails or returns nothing, keyword rules route instead.
  - **Role, not the model, decides what may run:** patients get triage and records; caregivers get records for a patient they name; doctors get records and the scribe for their own consultation.
  - **Parallel, bounded:** one `Send` per specialist, with `max_concurrency` 3. One specialist failing returns a safe message for that part only.
  - **Audit and trace:** each delegation writes an audit row (`action = delegate`, `resource = assistant.<specialist>`, `record_id` = the specialist's thread id, `trace_id` = the supervisor's trace). Supervisor and specialist nodes land in one trace.
- **Revisit trigger:** a specialist that must run *after* another one's result (sequential hand-offs), or more than about six specialists (consider hierarchical supervisors).
- **Consequences:**
  - *Easier:* new specialists plug in behind one protocol; every existing safety property still holds because nothing bypasses the specialists' own code.
  - *Harder:* a reply can contain several paused threads, so the client has to continue each on its own endpoint; clause splitting is heuristic.
- **Proof:** `tests/unit/test_supervisor.py` covers parallel execution (a barrier that only passes if branches run at once), emergency short-circuit before the model, role limits, model output limited to labels, planner fallback, failure isolation, audit linkage and one trace. `tests/integration/test_assistant_db.py` covers real graphs, resuming a delegated triage thread, audit rows and child spans under the supervisor's trace.
- **Checked on:** 2026-11-03 (LangGraph 1.2.19)
