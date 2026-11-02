# MedPal

**An AI assistant for outpatient clinics that routes patients to the right doctor, answers questions about their own medical records with citations, and drafts consultation notes that doctors sign. Patient data stays private by design.**

Outpatient clinics run on phone calls and paperwork. Patients struggle to work out which specialist they need, front desks spend the day answering the same booking questions, patients can't easily understand their own lab reports, and doctors lose consultation time typing notes.

MedPal automates the routine parts and keeps humans in charge of every decision that matters:

- **Find the right doctor:** describe symptoms in plain English or Hinglish. MedPal checks for emergencies *first* and hands them to a human immediately, never diagnosing. Otherwise it offers the soonest slots near you, preferring doctors who speak your language.
- **Ask your records** *(in progress)*: upload reports and ask questions. Every answer will cite the document and page, and it can only see your own records, or those a family member has explicitly shared with you.
- **Consultation scribe** *(planned)*: turns a consultation into a draft note. Nothing is saved until the doctor reviews and signs it, and the model never fills in a medicine the doctor didn't say.

## Built for healthcare, not just demoed for it

- **Privacy enforced by the database, not the prompt.** Postgres row-level security means a patient's query can only return their own data, even if application code forgets a filter. In testing, the same query sees 1 patient with the policy on and 28 with it off.
- **De-identification before anything leaves.** Microsoft Presidio, extended with India-specific recognisers (ABHA health IDs, Indian mobiles, PAN, voter ID, with Aadhaar blocked outright), strips identifiers before any text can reach an external AI model. It's tested against over-scrubbing too, so clinical meaning survives, including in Hinglish.
- **Humans sign off.** Emergencies go to staff, bookings need the patient's choice, and clinical notes need a doctor's signature. Signed notes and audit logs can't be edited, not even by a database admin.
- **Everything is audited.** Every write that touches patient data is logged with who, why and when, in the same transaction.
- **Built to India's DPDP Act constraints:** consent with scope and expiry, revocable at any time, and identified data that stays in-region.

**Stack:** Python 3.12 · FastAPI · LangGraph (human-in-the-loop with durable Postgres checkpoints) · PostgreSQL 17 + pgvector · Microsoft Presidio + spaCy · Docker · uv

> All data in this repository is synthetic or public: 500 generated doctors across 22 fictional clinics in Pune and Hyderabad, 480,000 appointment slots, and openly licensed datasets. See [`data/README.md`](data/README.md).

## Why I built this

<!-- Write this in your own words: what drew you to the problem, and what you wanted to learn. -->

## Status

| Feature | State |
|---|---|
| Triage → shortlist → patient picks a slot → booking (pause/resume across app instances) | ✅ working |
| Emergency gate with human handoff | ✅ working (placeholder rule list; clinician-signed rule engine planned) |
| Specialty matching | 🟡 stub (classifier planned) |
| Row-level security for every role, consent with expiry and revocation | ✅ |
| Presidio de-identification (English, Hinglish, Indian identifiers) | ✅ |
| Append-only audit, immutable signed notes | ✅ |
| Records Q&A with citations | ⏳ planned |
| Consultation scribe with doctor sign-off | ⏳ planned |
| OIDC login, consent API, front-desk console, tracing | ⏳ planned |

**Tests:** 81 unit · 64 data · 27 integration (real Postgres) · lint, type checks and module-boundary contracts.

## Quick start

Prerequisites: Docker (running), [uv](https://docs.astral.sh/uv/), GNU make.

```bash
make install     # Python 3.12 dependencies via uv
make up          # Postgres (pgvector) on :5433, Redis on :6380
make migrate     # apply the schema
make seed        # RESETS dev data: loads 500 doctors, 480k slots and dev identities
make api         # http://localhost:8000/docs
```

### Try it

```bash
H=(-H 'content-type: application/json' \
   -H 'X-Dev-User-Id: 00000000-0000-0000-0000-0000000e0001' \
   -H 'X-Dev-Role: patient' \
   -H 'X-Dev-Patient-Id: 00000000-0000-0000-0000-0000000b0001')

curl -s localhost:8000/triage "${H[@]}" -d '{"text": "knee pain for a week"}'
# → status "awaiting_choice" with three Pune doctors and times like "Mon 9 Nov, 09:00"

curl -s localhost:8000/triage/<thread_id>/resume "${H[@]}" \
  -d '{"slot_id": "<slot_id>", "idempotency_key": "demo-key-0001"}'
# → status "booked"

curl -s localhost:8000/triage "${H[@]}" -d '{"text": "seene mein dard hai"}'   # Hinglish: "chest pain"
# → status "emergency" with an emergency-desk ticket
```

The dev identity above is **Asha Verma** (patient, Pune), who can also act as caregiver for her mother **Lata**. Other dev logins (front desk, doctor, compliance) are listed by `make seed`.

> Dev authentication trusts `X-Dev-*` headers and refuses to start when `MEDPAL_ENV=prod`. OIDC login is planned.

### Tests and checks

```bash
make test-unit   # no Docker needed
make test-data   # data cleaning and generation checks
make test-int    # real Postgres; builds a throwaway medpal_test database
make lint        # ruff, mypy, import-linter module boundaries
```

## How it works

Start with **[docs/architecture.md](docs/architecture.md)**, which follows a request from the API through the graph to the database. Then:

| Doc | What you'll learn |
|---|---|
| [docs/adr/](docs/adr/) | Seven design decisions and why: LangGraph, row-level security, booking concurrency, Presidio, … |
| [docs/privacy-and-compliance.md](docs/privacy-and-compliance.md) | Every privacy obligation mapped to its control and the test that proves it |
| [docs/data-model/](docs/data-model/) | One page per table: sensitivity, row-level security rule, checks, consumers |
| [docs/lessons-learned.md](docs/lessons-learned.md) | Real bugs caught while building it, and the tests that now guard against them |
| [data/README.md](data/README.md) | Datasets, licences, cleaning rules, the generated network, sizing |

### Layout

```
services/
  api/          FastAPI app, routers, auth dependency
  agent/        LangGraph graphs (triage/ …)
  scheduling/   shortlist + booking transaction (advisory lock, capacity, idempotency)
  records/      report ingest + retrieval (planned)
  scribe/       speech-to-text + audio retention (planned)
  platform/     config, db pools + RLS sessions, auth context, audit, phi/ (Presidio)
data/           transforms for public datasets, synthetic network generator
infra/          docker-compose, Dockerfile, Alembic migrations, seed script
tests/          unit (in-memory) and integration (real Postgres)
docs/           architecture, ADRs, privacy, data model, lessons learned
```

### Database roles

The API connects as `medpal_app`, which is **not** a superuser and has no `BYPASSRLS`. That's what makes row-level security real. Migrations and seeding run as the owner `medpal`. Locally, `infra/postgres/init/` creates the app role on a fresh volume (`make reset` recreates it).

## Roadmap

1. Clinician-signed red-flag rule engine and a specialty classifier, with evaluation sets written before the code.
2. Records Q&A: ingest, self-hosted embeddings, retrieval scoped by row-level security, verified citations.
3. Consultation scribe with doctor sign-off and stock-aware prescriptions.
4. OIDC login, consent API, front-desk console, self-hosted tracing.
