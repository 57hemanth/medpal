# Table: `doctor`

| Field | Value |
|---|---|
| Owner (role) | Medical administration |
| Schema version | 1 |
| Change rule | Additive column = minor version, with consumers notified in the PR. Type or meaning change = new version, migration and sign-off from every consumer below. |
| Freshness | daily |
| Sensitivity | **operational (direct for real staff)** |
| Row-level security | none (directory is public to patients); app role read-only |
| Source | data/synthetic/generate.py, seed 20261102 (ADR-0004) |

## Checks (each is a test or a database constraint)

- ≥ 10 doctors per specialty
- languages include en, subset of {en, hi, mr, te, ur}
- years 1–40
- names unique
- synthetic = true for generated rows

## Consumers, and what breaks for each when the schema changes

- shortlist ranking by language
- doctor console login (app_user.doctor_id)
