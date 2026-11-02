# Table: `slot`

| Field | Value |
|---|---|
| Owner (role) | Operations lead |
| Schema version | 1 |
| Change rule | Additive column = minor version, with consumers notified in the PR. Type or meaning change = new version, migration and sign-off from every consumer below. |
| Freshness | generated nightly for a rolling 60 working days |
| Sensitivity | **operational** |
| Row-level security | none; app role read-only (capacity cannot be changed by the app) |
| Source | data/synthetic/generate.py: arithmetic, no LLM |

## Checks (each is a test or a database constraint)

- (doctor_id, starts_at) unique
- starts_at inside clinic hours
- no Sunday slots
- capacity ≥ 1

## Consumers, and what breaks for each when the schema changes

- shortlist (LATERAL first-free query)
- booking capacity check
