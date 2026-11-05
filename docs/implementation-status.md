# Implementation status

Reviewed against the code on 2 November 2026. The README roadmap, architecture and privacy
matrix describe a mixture of completed controls and future scope; the entire plan is **not**
implemented. This inventory separates those states. No separate implementation plan file was
found in this repository.

| Area | Implemented | Remaining |
|---|---|---|
| Test access | Login page offers seeded patient, caregiver, doctor, desk and compliance identities; identity changes clear query caches | Browser OIDC intentionally deferred; test identities are not production authentication |
| Triage and booking | Durable graph, draft emergency gate, deterministic specialty matching, clarification, shortlist, explicit slot choice, idempotent booking, handoff tickets | Clinician sign-off, model classifier, expanded evaluations, SMS delivery |
| Records | Patient upload, persisted job state, page-aware chunks, RLS-scoped hybrid retrieval, citation-id verification and read audit | Durable background worker; semantic model quality and adversarial document evaluations |
| Storage | Persistent private filesystem development store; encrypted S3-compatible adapter; memory store for tests | Real deployment bucket, credentials, region and connectivity verification |
| Extraction | Text and PDF extraction; local English/Hindi OCR fallback; blocked-identifier checks before storage | Representative scan-quality evaluation; OCR binaries required on host (included in app image) |
| Embeddings | In-boundary deterministic 1,024-dimensional adapter | Production self-hosted multilingual semantic model and reindexing strategy |
| Scribe | Draft from transcript, medicine evidence checks, immutable doctor-signing API; UI shows draft | UI editing/signing and encounter creation/listing; stock-aware prescription workflow |
| Speech | Doctor-only WAV transcription API and upload UI, offline faster-whisper adapter, in-memory audio | Model provisioning and evaluation on real representative synthetic audio |
| Consent | Grant/list/revoke APIs, expiry/revocation enforced by RLS; list/revoke UI | Grant form, guardian/minor policy and workflow |
| Operations | Appointment list/cancel APIs, front-desk handoff list/status APIs and queue UI | Booking overrides, richer appointment UI, compliance audit console |
| Privacy/security | Non-superuser RLS, de-identification egress, append-only audit, immutable notes, dev-auth production guard | Full operational security/deployment validation; no production-readiness claim |
| Observability | Audit trail and health endpoint | Self-hosted tracing and privacy-safe operational instrumentation |
| Retention/erasure | Audio is never persisted in the current transcription path | Checkpoint expiry, patient erasure, object cleanup/lifecycle, audited recording deletion if recording persistence is added |

Validation for this change: 112 unit tests, 64 data tests, 38 real-Postgres integration tests,
1 frontend unit test, lint/format, mypy, module-boundary checks and frontend production build.
The OCR runtime image was built and the actual OCR helper passed an offline image-only synthetic
PDF smoke test, including temporary-directory cleanup. The full application image build was
stopped during the existing spaCy model download; that complete image remains unverified.
The new Postgres test uploads a two-page PDF, recreates storage, ingests it, retries the upload
and verifies that exactly two correctly numbered page chunks remain. S3 and speech unit tests
use doubles; they do not claim a live bucket or model has been tested. Browser acceptance
testing is intentionally left to the project owner.

Runtime instructions: [adapter setup](adapters.md). Architecture: [request flow](architecture.md).
