# Table: `doc_chunk`

| Field | Value |
|---|---|
| Owner (role) | Platform tech lead |
| Schema version | 1 |
| Change rule | Additive column = minor version, with consumers notified in the PR. Type or meaning change = new version, migration and sign-off from every consumer below. |
| Freshness | indexed ≤ 60 s after upload (p95) |
| Sensitivity | **clinical** |
| Row-level security | read: allowed patients; insert: system worker only |
| Source | ingest pipeline over document; embeddings from a self-hosted model, so clinical text never leaves the boundary |

## Checks (each is a test or a database constraint)

- patient_id = parent document.patient_id (0 violations)
- embedding dimension 1024 when set
- (doc_id, page, ordinal) unique
- text 200–2,000 chars (≤ 1% outside)

## Consumers, and what breaks for each when the schema changes

- records retriever: breaks if patient_id missing or embedding dim changes
- eval harness: breaks if chunk ids change
