# Data model

One page per table: owner role, schema version and change rule, freshness, sensitivity class, row-level security rule, checks, the consumers that break when it changes, and the data source. Together they are the contract between the database and the code that reads it.

Sensitivity classes: **direct** (never leaves the boundary; tokenised on egress) · **quasi** (generalised only) · **clinical** (de-identified only) · **operational** (may leave).

| Table | Owner (role) | Sensitivity | Freshness |
|---|---|---|---|
| [`patient`](patient.md) | Records lead | direct | real-time (registration) |
| [`consent`](consent.md) | Compliance officer | direct (linked) | real-time; checked on every read |
| [`document`](document.md) | Records lead | clinical | row within 1 s of upload; content via ingest_job |
| [`doc_chunk`](doc_chunk.md) | Platform tech lead | clinical | indexed ≤ 60 s after upload (p95) |
| [`clinic`](clinic.md) | Operations lead | operational | daily |
| [`doctor`](doctor.md) | Medical administration | operational (direct for real staff) | daily |
| [`specialty`](specialty.md) | Chief medical officer | operational | on change |
| [`slot`](slot.md) | Operations lead | operational | generated nightly for a rolling 60 working days |
| [`appointment`](appointment.md) | Front desk lead | direct (linked) | real-time |
| [`encounter`](encounter.md) | Clinical lead | clinical | real-time |
| [`clinical_note (note_version)`](note_version.md) | Clinical lead | clinical | on signature |
| [`medicine_stock`](medicine_stock.md) | Pharmacy lead | operational | ≤ 24 h (nightly CSV); > 48 h shown as 'unknown' |
| [`prescription`](prescription.md) | Clinical lead | clinical | on signature |
| [`audit_event`](audit_event.md) | Compliance officer | direct (linked) | real-time, same transaction as the action |

Migrations: `infra/migrations/versions/`. Row-level security is explained in [ADR-0003](../adr/0003-row-level-security.md).
