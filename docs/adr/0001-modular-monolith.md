# ADR-0001: One deployable service with strict module boundaries

- **Status:** accepted
- **Context:** MedPal has several areas (triage, scheduling, records, scribe, platform services) that could become separate services one day. Today one small team builds them, and they share one database.
- **Options:**
  1. *Microservices from day one.* Independent scaling and deploys, but network calls, service-to-service auth, distributed tracing and several CI pipelines, all before there is a single user.
  2. *A modular monolith.* One FastAPI app plus one worker. Areas are Python packages with their own routers and database objects, and the boundaries are enforced by tooling.
  3. *A single package with no boundaries.* Fastest at first, but it can't be split later.
- **Decision:** Option 2. The boundaries are checked by `import-linter` contracts in `pyproject.toml`:
  - `services.scheduling`, `services.records` and `services.scribe` may not import each other;
  - `services.platform` (config, db, auth, audit, PHI) may not depend on any workflow or on the API.

  Each area owns its tables. The LangGraph checkpointer lives in its own `langgraph` schema.
- **Revisit trigger:** one area needs to scale differently (for example, speech-to-text on GPUs), gets its own team, or needs its own release cadence.
- **Consequences:**
  - *Easier:* one deploy, one transaction where needed (booking plus audit), simple local setup (`make up`).
  - *Harder:* one failure domain for the API, and it takes discipline to stop modules reaching into each other's tables. Only imports are checked automatically, not SQL.
- **Proof:** `make lint` runs `lint-imports` (2 contracts kept).
- **Checked on:** 2026-11-02
