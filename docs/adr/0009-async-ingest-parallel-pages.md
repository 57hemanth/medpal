# ADR-0009: Records ingest on a queue, pages processed in parallel

- **Status:** accepted
- **Context:** About 6,600 reports a day, many of them scanned (OCR is slow), at a morning peak. Upload must not hold an HTTP request open while every page is processed. But an Aadhaar number must be blocked **before** anything is stored, so some extraction has to happen during the upload itself.
- **Options:**
  1. *Everything inline in the upload request.* Simple, but slow uploads and timeouts on scans.
  2. *Queue everything and scan for blocked identifiers later.* Fast uploads, but blocked identifiers would be stored first, which breaks the privacy rule.
  3. **Validate and scan inline, then queue the indexing** (chunk, embed, write) by document id, with pages processed in parallel.
- **Decision:** Option 3:
  - Upload validates, scans for blocked identifiers, stores the object and enqueues **only the document id** (arq on Redis; no content in the queue).
  - The worker runs `services/records/ingest_graph.py`, a LangGraph that fans out one `Send` per page (text layer, else local OCR → chunk → embed) under `max_concurrency`, then writes every chunk in one transaction.
  - Job ids derive from document ids, so duplicate enqueues collapse.
  - `MEDPAL_INGEST_MODE=inline` keeps local development and tests simple.
- **Revisit trigger:** OCR cost dominates (cache page text encrypted in the object store at upload), or a per-patient document volume makes per-document jobs too coarse.
- **Consequences:**
  - *Easier:* uploads return quickly; pages scale with workers; a crash is simply retried (content-addressed, idempotent writes).
  - *Harder:* scanned PDFs are OCR'd twice, once for the privacy scan and once for indexing. Accepted: privacy before efficiency.
- **Proof:** `tests/integration/test_ingest_queue.py` covers 5 pages under concurrency 2 written in page order, and confirms queue mode enqueues only the id while the worker completes the job.
- **Checked on:** 2026-11-03
