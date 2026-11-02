# How MedPal works

This guide walks through the system from a request coming in to a row being written, and explains why each piece is there. Design decisions link to their [ADRs](adr/). Anything not yet built is marked **(planned)**.

## 1. The big picture

```
 Patient app / Front desk / Doctor console           (UI: planned)
                    │
                    ▼
 ┌──────────────── FastAPI (services/api) ─────────────────────────────────┐
 │  auth dependency → AuthContext {user_id, role, acting_for_patient_id}   │
 │  routers: /triage  (records, scribe, consent: planned)                  │
 └───────────────┬──────────────────────────────────────────────────────────┘
                 ▼
 ┌──────── LangGraph graphs (services/agent) ───────┐   ┌── platform (services/platform) ──┐
 │ triage: intake → red-flag gate → specialty →     │──►│ db pools + scoped() RLS sessions │
 │         shortlist → interrupt(patient picks) →   │   │ audit writer (append-only)       │
 │         book → notify                            │   │ phi/ Presidio de-identification  │
 └───────┬──────────────────────────────────────────┘   │ config, auth context             │
         │ checkpoints (langgraph schema)               └──────────────────────────────────┘
         ▼                                 ▲
 ┌──────────────────── PostgreSQL 17 + pgvector ────────────────────────────┐
 │ scheduling: clinic, doctor, slot, appointment, handoff_ticket           │
 │ records: document, doc_chunk (vector(1024) + tsvector), consent         │
 │ clinical: encounter, note_version (immutable), prescription             │
 │ audit_event (append-only, partitioned)  ·  row-level security on PHI    │
 └──────────────────────────────────────────────────────────────────────────┘
```

It's one deployable service with strict module boundaries ([ADR-0001](adr/0001-modular-monolith.md)). `import-linter` stops the workflow modules from importing each other, and stops the platform layer from depending on any workflow.

## 2. A triage request, step by step

`POST /triage {"text": "knee pain for a week"}` with the caller's identity.

1. **Identity.** `services/api/deps.py` builds an `AuthContext`. In development it trusts `X-Dev-*` headers, a mode that refuses to start when `MEDPAL_ENV=prod`; OIDC login is planned. From here on, **who** the caller is comes only from this context, never from request text or model output. That closes the "book for patient 123" prompt-injection route.
2. **A new run.** The router creates a `thread_id` and invokes the compiled graph with `{auth, intake_text}`. The API keeps no state; everything lives in the LangGraph checkpointer in Postgres ([ADR-0002](adr/0002-orchestration-langgraph.md)).
3. **Red-flag gate, before anything else.** `red_flag_rules` checks the text for emergency presentations, in English and Hinglish ("seene mein dard" = chest pain). On a match the run goes to `emergency_handoff`: it opens a ticket in the emergency queue, replies with fixed guidance (call 112), and ends. **No diagnosis, no AI, and it works even if every model is down.** *The current rule list is a deliberately over-inclusive placeholder; a versioned, clinician-signed rule engine is planned.*
4. **Specialty.** `match_specialty` picks one of 38 specialties. *Currently a stub that returns General Medicine; a small-model classifier with a confidence threshold (ask one clarifying question, then hand over to the front desk) is planned.*
5. **Shortlist** (plain SQL, no AI). `services/scheduling/service.py::shortlist` returns each doctor's earliest **free** slot, ranked by:
   - same city as the patient (a filter);
   - doctor speaks the patient's language;
   - the patient's preferred clinic;
   - soonest slot.

   The patient's preferences are read **as the caller** under row-level security, so the tool can't read anyone else's profile. The query uses `LATERAL … LIMIT 1` per doctor, so each doctor's index scan stops at the first free slot: **4.5 ms vs 60 ms** for the naive version on 480k slots with 6,200 bookings.
6. **Pause for the patient.** `present_options` calls `interrupt({"candidates": …})`. The run is checkpointed and the API returns `awaiting_choice` with three options, times shown in clinic local time ("Mon 9 Nov, 08:00").
7. **Resume.** `POST /triage/{thread_id}/resume {slot_id, idempotency_key}`. The router first checks the thread belongs to the caller: a thread id is not an authorisation. The graph accepts the choice only if it was one of the offered slots. Any replica can resume, because the state comes from Postgres.
8. **Book.** `reserve()` runs one transaction:
   - an advisory lock on the slot;
   - booked count < capacity?
   - insert the appointment with the client's idempotency key;
   - write the audit event.

   A retry with the same key returns the same booking. A full slot sends the graph back to the shortlist with that slot excluded, up to three times, then to the front desk ([ADR-0005](adr/0005-booking-concurrency.md)).
9. **Notify.** A fixed-template confirmation. *SMS delivery is planned; model text will never go into an SMS.*

**Why the booking step sits in its own node:** a node that calls `interrupt()` runs again from the top when it resumes. Anything with side effects in that node would happen twice, so booking lives in the next node.

## 3. Who can see what: row-level security

Patient data is isolated **by the database**, not by remembering a `WHERE` clause ([ADR-0003](adr/0003-row-level-security.md)).

| Caller | Clinical records visible |
|---|---|
| Patient | their own |
| Caregiver | patients who granted unexpired, unrevoked `records:read` consent |
| Doctor | patients with an appointment with them |
| Front desk | demographics only, no clinical content |
| Compliance | audit trail and signed notes |
| System worker | everything (ingest), and the only role that writes chunks |

How it works:
- `scoped(pool, auth)` opens a transaction and sets `app.user_id` / `app.role` locally to it. Every policy calls one function, `app_allowed_patients()`. With no identity set, no rows come back.
- The app connects as `medpal_app`, which is **not a superuser**. This matters because superusers bypass RLS entirely. Migrations and seeding use the owner role.
- Grants limit verbs and columns too:
  - a patient can revoke a consent but not extend it;
  - the app can't change slot capacity;
  - signed notes and audit rows can't be updated or deleted, even by the owner.

## 4. What may leave the boundary: de-identification

Identified data stays inside the deployment. Before any text goes to an external model, `services/platform/phi/` runs Microsoft Presidio, extended for India ([ADR-0006](adr/0006-presidio-deidentification.md)):

```
"meri maa Asha Verma ko seene mein dard hai, mobile 98765 43210"
        │ tokenise (known identities + India recognisers + Hinglish mode)
        ▼
"meri maa <PERSON_1> ko seene mein dard hai, mobile <IN_PHONE_1>"   ──► external model
        │ assert_clean (independent second pass, fails closed)
        ▼
model reply with tokens ──► reidentify (token map never leaves) ──► patient
```

- Names, phones, ABHA, PAN, MRN, a labelled date of birth and locations are **tokenised**; Aadhaar is **blocked**. Lab values, drug names and report dates are **kept**, because the model needs them.
- Tested in both directions: no leaks, and no over-scrubbing of clinical text, including Hinglish.

*The egress adapter that wires this in front of an LLM provider is planned. The de-identification layer and its tests are built.*

## 5. Audit

Every write that touches patient data (bookings, handoff tickets) writes an `audit_event` **in the same transaction**: actor, role, action, record, patient, purpose, trace id. The table is partitioned by month and append-only. "Who saw this record?" is a single query. *Read-audit on records Q&A arrives with that feature.*

## 6. Data

- **Generated network** ([ADR-0004](adr/0004-generated-directory-in-code.md)): 6 hospitals and 22 clinics in Pune and Hyderabad, 38 specialties, 500 doctors and 480,000 slots, produced by seeded code. `make seed` loads it with `COPY` in about 4 seconds.
- **Public datasets:** sources, licences and cleaning are in [`data/README.md`](../data/README.md).
- **Per-table reference:** [`docs/data-model/`](data-model/).

## 7. How it's tested

| Layer | What | Where |
|---|---|---|
| Unit | Graph paths with fake tools and the in-memory checkpointer; API contract; de-identification (66 cases) | `tests/unit/` |
| Data | Cleaning checks with drop reasons tallied; generated-layer rules | `data/transforms/tests/`, `data/synthetic/tests/` |
| Integration | Real Postgres: concurrency, idempotency, every RLS role, append-only audit and notes, resume on a fresh app instance, shortlist ranking | `tests/integration/` |

Integration tests rebuild a throwaway `medpal_test` database from migrations on every run. Fixtures are set up with the owner role; the code under test runs as the app role, so RLS is exercised for real.

## 8. Planned

- **Records Q&A:**
  - upload, then OCR fallback, de-identification, section chunking and self-hosted embeddings;
  - hybrid retrieval scoped by RLS;
  - answers with verified citations;
  - diagnosis and dose questions handed to a doctor.
- **Consultation scribe:** transcript → SOAP draft → medicines checked against the transcript and against stock → the doctor reviews and signs → an immutable version. Nothing is stored before the signature.
- **Real red-flag rule engine and specialty classifier,** with evaluation sets written before the code.
- **OIDC login (Keycloak), a consent API, self-hosted tracing (Langfuse), and a front-desk console** with booking overrides.
