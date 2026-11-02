# Table: `clinic`

| Field | Value |
|---|---|
| Owner (role) | Operations lead |
| Schema version | 1 |
| Change rule | Additive column = minor version, with consumers notified in the PR. Type or meaning change = new version, migration and sign-off from every consumer below. |
| Freshness | daily |
| Sensitivity | **operational** |
| Row-level security | none (reference data); app role read-only |
| Source | data/synthetic/reference.py (fictional names on real localities) |

## Checks (each is a test or a database constraint)

- closes_at > opens_at
- city in {Pune, Hyderabad}
- every clinic has ≥ 1 doctor and slots on every working day

## Consumers, and what breaks for each when the schema changes

- shortlist city filter
- slot generation
- stock per clinic
