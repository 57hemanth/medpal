# Table: `specialty`

| Field | Value |
|---|---|
| Owner (role) | Chief medical officer |
| Schema version | 1 |
| Change rule | Additive column = minor version, with consumers notified in the PR. Type or meaning change = new version, migration and sign-off from every consumer below. |
| Freshness | on change |
| Sensitivity | **operational** |
| Row-level security | none; read-only |
| Source | data/synthetic/reference.py |

## Checks (each is a test or a database constraint)

- exactly the 38 configured specialties (`data/synthetic/reference.py`)
- name unique

## Consumers, and what breaks for each when the schema changes

- specialty classifier output enum (planned): breaks if a name changes
- crosswalk
- eval sets
