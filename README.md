# MedPal

**An AI assistant for outpatient clinics that routes patients to the right doctor, answers questions about their own medical records with citations, and drafts consultation notes that doctors sign. Patient data stays private by design.**

Outpatient clinics run on phone calls and paperwork. Patients struggle to work out which specialist they need, front desks spend the day answering the same booking questions, patients can't easily understand their own lab reports, and doctors lose consultation time typing notes.

MedPal automates the routine parts and keeps humans in charge of every decision that matters:

- **Find the right doctor:** describe symptoms in plain English or Hinglish. MedPal checks for emergencies *first* and hands them to a human immediately, never diagnosing. Otherwise it offers the soonest slots near you, preferring doctors who speak your language.
- **Ask your records**: upload reports and ask questions. Every answer cites the document page, and it can only see your own records, or those a family member has explicitly shared with you.
- **Consultation scribe**: turns a consultation into a draft SOAP note. Nothing is saved until the doctor reviews and signs it, and the model never fills in a medicine the doctor didn't say.

## Built for healthcare, not just demoed for it

- **Privacy enforced by the database, not the prompt.** Postgres row-level security means a patient's query can only return their own data, even if application code forgets a filter. In testing, the same query sees 1 patient with the policy on and 28 with it off.
- **De-identification before anything leaves.** Microsoft Presidio, extended with India-specific recognisers (ABHA health IDs, Indian mobiles, PAN, voter ID, with Aadhaar blocked outright), strips identifiers before any text can reach an external AI model. It's tested against over-scrubbing too, so clinical meaning survives, including in Hinglish.
- **Humans sign off.** Emergencies go to staff, bookings need the patient's choice, and clinical notes need a doctor's signature. Signed notes and audit logs can't be edited, not even by a database admin.
- **Everything is audited.** Every write that touches patient data is logged with who, why and when, in the same transaction.
- **Built to India's DPDP Act constraints:** consent with scope and expiry, revocable at any time, and identified data that stays in-region.

**Stack:** Python 3.12 · FastAPI · LangGraph (human-in-the-loop with durable Postgres checkpoints) · PostgreSQL 17 + pgvector · Microsoft Presidio + spaCy · LangChain · React · Docker · uv

> All data in this repository is synthetic or public: 500 generated doctors across 22 fictional clinics in Pune and Hyderabad, 480,000 appointment slots, and openly licensed datasets. See [`data/README.md`](data/README.md).

## Why I built this

<!-- Write this in your own words: what drew you to the problem, and what you wanted to learn. -->

## Status

| Feature | State |
|---|---|
| Triage → structured safety screen → clarifying question → shortlist → patient picks a slot → booking (pause/resume across app instances) | ✅ |
| Emergency gate: red-flag rules, a seven-question safety screen, and a model second pass that can only add an emergency | ✅ evaluation-gated; 24/25 on unseen phrasings with the model; clinician sign-off still external |
| Records Q&A with verified citations; caregiver must pick one patient | ✅ |
| Queued records ingest with pages processed in parallel (LangGraph `Send`, bounded) | ✅ |
| Consultation scribe: doctor interrupt, edit history, redraft, stock-aware prescriptions, signing | ✅ |
| Pharmacy stock feeds (nightly CSV or real-time API) synced every 15 minutes | ✅ |
| MCP tool server: slots, booking, medicine stock | ✅ |
| One assistant: a supervisor runs triage, records and scribe in parallel from one message | ✅ |
| Model routing by tier with provider fallback; safe degradation when all fail | ✅ |
| Hybrid deployment: internal network, ingress, allowlisting egress proxy | ✅ proven live by `make boundary-check` |
| Tracing on every run, cost per run, ops metrics, load test at 1,400 req/h | ✅ |
| Evaluation sets with release gates, held-out generalisation set, calibrated LLM judge harness | ✅ judge needs clinician-reviewed labels |
| Row-level security for every role, consent with expiry and revocation | ✅ |
| Presidio de-identification (English, Hinglish, Indian identifiers) | ✅ |
| Append-only audit, immutable signed notes | ✅ |
| Web app: role-based dashboards for patients, caregivers, doctors, front desk and compliance; audit log and operations views | ✅ profile switcher until sign-in is added |
| Verified against a real model (Gemini): answers, refusals, routing, drafts, fallback, cost | ✅ `make live-check` |
| Local speech-to-text | 🟡 adapter and upload UI; local model provisioning required |

**Tests:** 259 unit · 64 data · 63 integration (real Postgres) · 10 frontend · 40 real-model checks · evaluation gates · lint, type checks and module-boundary contracts. See [implementation status](docs/implementation-status.md) for what has been verified against a live stack.

## Quick start

Prerequisites: Docker (running), [uv](https://docs.astral.sh/uv/), GNU make.

```bash
make install     # Python 3.12 dependencies via uv
make up          # Postgres (pgvector) on :5433, Redis on :6380
make migrate     # apply the schema
make seed        # RESETS dev data: 500 doctors, 480k slots, dev identities, sample lab reports
make web-build   # build the web app once (the API serves it)
make api         # app at http://localhost:8000, API docs at /docs
```

### The product

Open **http://localhost:8000**. There's no sign-in yet: the app opens on the patient profile, and the profile switcher at the bottom of the sidebar moves between the synthetic workspace profiles.

| Profile | What they get |
|---|---|
| **Patient** (Asha Verma) | Home with next appointment and recent reports (open any report in the viewer) · care assistant (symptoms and report questions in one message, English or Hinglish) · appointments · health records with cited answers · sharing & consent |
| **Caregiver** (Asha, for her mother Lata) | Lata's shared reports (view and ask about them), and the access granted to her |
| **Doctor** | Today's consultations · consultation scribe: transcript → SOAP draft with stock-checked prescriptions → edit or redraft → sign · patient records |
| **Front desk** | Overview with emergencies first · handoff queue · network appointments |
| **Compliance** | Operations: latency, error rate and model spend per workflow from in-boundary traces · append-only audit log |

### Try it

```bash
H=(-H 'content-type: application/json' \
   -H 'X-Dev-User-Id: 00000000-0000-0000-0000-0000000e0001' \
   -H 'X-Dev-Role: patient' \
   -H 'X-Dev-Patient-Id: 00000000-0000-0000-0000-0000000b0001')

curl -s localhost:8000/triage "${H[@]}" -d '{"text": "knee pain for a week"}'
# → status "awaiting_safety_check" with seven yes/no questions

curl -s localhost:8000/triage/<thread_id>/resume "${H[@]}" -d '{"safety_answers":
  {"chest_pain": false, "breathing": false, "unconscious": false, "stroke": false,
   "bleeding": false, "poisoning": false, "self_harm": false}}'
# → status "awaiting_choice" with three Pune doctors and times like "Mon 9 Nov, 09:00"

curl -s localhost:8000/triage/<thread_id>/resume "${H[@]}" \
  -d '{"slot_id": "<slot_id>", "idempotency_key": "demo-key-0001"}'
# → status "booked"

curl -s localhost:8000/triage "${H[@]}" -d '{"text": "seene mein dard hai"}'   # Hinglish: "chest pain"
# → status "emergency" with an emergency-desk ticket

curl -s localhost:8000/api/assistant "${H[@]}" \
  -d '{"message": "My knee has hurt for a week. Also, what was my LDL last time?"}'
# → triage and records run in parallel; one reply plus each specialist's result and thread id
```

### Using a real model (Gemini)

Copy `.env.example` to `.env` and fill in the Gemini block (provider, model ids, API key and prices); see [model setup](docs/adapters.md#hosted-models).
Text is de-identified before it leaves; without a key, a local placeholder model keeps every flow working. Then run `make live-check` to verify answers, routing, drafts, fallback and cost metering against the real model.

The dev identity above is **Asha Verma** (patient, Pune), who can also act as caregiver for her mother **Lata**. Other dev logins (front desk, doctor, compliance) are listed by `make seed`.

> Dev authentication trusts `X-Dev-*` headers and refuses to start when `MEDPAL_ENV=prod`. The web app switches between synthetic profiles; browser sign-in (OIDC) is the next step before any real deployment.

### Tests and checks

```bash
make test-unit   # no Docker needed
make test-data   # data cleaning and generation checks
make test-int    # real Postgres; builds a throwaway medpal_test database
make lint        # ruff, mypy, import-linter module boundaries
make web-build   # React type-check + production build
make web-test    # React unit tests
make eval        # evaluation sets; fails if a release gate is missed
make live-check  # real-model checks against the running API (needs a key in .env)
make judge       # LLM judge with calibration status
```

### Running like production

```bash
make worker          # queued records ingest + pharmacy stock sync (needs Redis)
make up-boundary     # internal network, nginx ingress, allowlisting egress proxy
make boundary-check  # proves the API has no route out except the allowlisted model hosts
make load-test       # 1,400 requests/hour, then a 3x burst; p95 per endpoint
make cost-report     # cost per run from real traces
```

Other agents can use MedPal's scheduling and stock tools over MCP at `http://localhost:8000/mcp`.

## How it works

Start with **[docs/architecture.md](docs/architecture.md)**, which follows a request from the API through the graph to the database. Then:

| Doc | What you'll learn |
|---|---|
| [docs/adr/](docs/adr/) | Thirteen design decisions and why: LangGraph, row-level security, booking concurrency, Presidio, the egress boundary, the safety screen, … |
| [docs/roadmap.md](docs/roadmap.md) | Extensions built and proposed, with what each proves |
| [docs/threat-model.md](docs/threat-model.md) | STRIDE and LLM-specific threats, each with its control and the test that proves it |
| [docs/privacy-and-compliance.md](docs/privacy-and-compliance.md) | Every privacy obligation mapped to its control and the test that proves it |
| [docs/data-model/](docs/data-model/) | One page per table: sensitivity, row-level security rule, checks, consumers |
| [docs/lessons-learned.md](docs/lessons-learned.md) | Real bugs caught while building it, and the tests that now guard against them |
| [data/README.md](data/README.md) | Datasets, licences, cleaning rules, the generated network, sizing |

### Layout

```
services/
  api/          FastAPI app, routers, auth dependency
  agent/        LangGraph graphs (triage/, scribe/, supervisor/)
  scheduling/   shortlist + booking transaction (advisory lock, capacity, idempotency)
  records/      report ingest, retrieval and cited Q&A
  scribe/       SOAP draft + doctor sign-off
  platform/     config, db pools + RLS sessions, identity, audit, phi/ (Presidio), egress/, tracing
  mcp_server/   MCP tools for other agents (slots, booking, stock)
  egress_proxy/ allowlisting CONNECT proxy for the deployment boundary
  worker/       arq worker: queued ingest, pharmacy stock sync
data/           transforms for public datasets, synthetic network generator
evals/          evaluation sets, gates, LLM-judge calibration
infra/          docker-compose (dev and boundary), nginx, Dockerfile, migrations, seed, load/cost/boundary scripts
tests/          unit (in-memory) and integration (real Postgres)
docs/           architecture, ADRs, privacy, data model, lessons learned
```

### Database roles

The API connects as `medpal_app`, which is **not** a superuser and has no `BYPASSRLS`. That's what makes row-level security real. Migrations and seeding run as the owner `medpal`. Locally, `infra/postgres/init/` creates the app role on a fresh volume (`make reset` recreates it).

## Roadmap

See [implementation status](docs/implementation-status.md) for a code-checked scope inventory and [adapter setup](docs/adapters.md) for persistent storage, OCR and speech configuration.

1. Clinician sign-off on the emergency rules, safety-screen wording and judge calibration labels.
2. Swap the deterministic local embedding adapter for a production self-hosted multilingual model.
3. Rate limiting, checkpoint retention and patient erasure.
4. SMS delivery with fixed templates; browser OIDC login.
