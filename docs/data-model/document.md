# Table: `document`

| Field | Value |
|---|---|
| Owner (role) | Records lead |
| Schema version | 1 |
| Change rule | Additive column = minor version, with consumers notified in the PR. Type or meaning change = new version, migration and sign-off from every consumer below. |
| Freshness | row within 1 s of upload; content via ingest_job |
| Sensitivity | **clinical** |
| Row-level security | read: allowed patients; insert: patient/caregiver for allowed patient, uploaded_by = caller |
| Source | patient uploads; generated report PDFs (synthetic, planned) |

## Checks (each is a test or a database constraint)

- (patient_id, sha256) unique
- uri resolves in object store
- phi_status in {pending, tagged, blocked}

## Consumers, and what breaks for each when the schema changes

- records ingest worker
- citations (doc_id, page)
