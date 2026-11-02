# Table: `appointment`

| Field | Value |
|---|---|
| Owner (role) | Front desk lead |
| Schema version | 1 |
| Change rule | Additive column = minor version, with consumers notified in the PR. Type or meaning change = new version, migration and sign-off from every consumer below. |
| Freshness | real-time |
| Sensitivity | **direct (linked)** |
| Row-level security | not yet; writes go only through `scheduling.reserve`, which audits every booking |
| Source | runtime bookings |

## Checks (each is a test or a database constraint)

- idempotency_key unique
- booked count per slot ≤ capacity (advisory lock + check)
- one booked row per (slot, patient)
- source in {assistant, desk, phone}

## Consumers, and what breaks for each when the schema changes

- shortlist availability
- doctor 'treating' scope in app_allowed_patients()
- no-show analytics
