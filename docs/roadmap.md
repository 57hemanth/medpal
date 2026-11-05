# Roadmap

What MedPal could do next, and what each extension would prove. Three are built; two are proposals, each written as one paragraph with the approach, the main risk and how it would be measured.

| Extension | State | What it proves |
|---|---|---|
| Real-time pharmacy feed | ✅ built | The adapter boundary holds: the nightly CSV and the live API sit behind one interface and share contract tests |
| MCP tool server | ✅ built | Scheduling and stock are a product other agents can use, under the same identity and audit rules |
| Supervisor with specialist graphs | ✅ built | Several agents can work on one request in parallel without losing safety, ownership or audit |
| Nursing-note shift summaries | proposal | Long-context summarisation where every line is cited |
| Claims and coding assist | proposal | Human-in-the-loop on a financial decision |

## Built

**Real-time pharmacy feed.** `services/scribe/stock_feeds.py` gives the nightly CSV and the pharmacy's API one `StockFeed` interface, proven by one contract test suite run against both. The worker syncs every 15 minutes. An older reading never overwrites a newer one, and every stock flag the doctor sees carries its reading time; anything older than 48 hours shows as *stale*.

**MCP tool server.** `/mcp` exposes `find_appointment_slots`, `book_appointment` and `check_medicine_stock` over the Model Context Protocol. Tools resolve identity exactly as the API does; no tool takes a patient id; booking is idempotent and audited.

**Supervisor with specialist graphs.** `POST /api/assistant` takes one message and runs triage, records and the scribe in parallel, each as its own durable thread, under one trace. The model may only label clauses; red-flag rules run first; the role decides which specialists may run. See [ADR-0012](adr/0012-supervisor-with-specialist-graphs.md).

## Proposals

**Nursing-note shift summaries.** Ward nurses write progress notes through a shift. A ward-round doctor needs the last 24 hours in two minutes. The proposal is a summary graph over one inpatient's notes for a time window. Notes are chunked by entry, every summary line must cite at least one note id, and a verifier node drops any line whose cited note doesn't support it, the same rule the records assistant already enforces. Critical items (new medication, a fall, abnormal vitals) are pulled first by rules and always included, not left to the model. The main risk is a fluent summary that quietly omits something important, so the evaluation is recall of a clinician-labelled set of must-mention events per shift, plus citation precision. Building it needs inpatient notes in the data model, which is outside the current outpatient scope.

**Claims and coding assist.** After a doctor signs a note, a coder assigns ICD-10 codes and assembles pre-authorisation packets for insurers. The proposal suggests codes from the signed note only, each with the sentence that supports it. A human coder accepts, changes or rejects every code, and nothing is submitted without that action, the same interrupt pattern the scribe uses. The packet is assembled from structured data (signed note, prescriptions, cited reports), never generated free text. The main risks are upcoding (a financial and legal exposure) and the model inventing a diagnosis the doctor didn't make, so the evaluation measures agreement with certified coders, and any code without a supporting sentence is rejected by code, not by prompt. Billing and insurance adjudication stay out of scope; this would only prepare work for a human.
