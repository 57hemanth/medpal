# Table: `audit_event`

| Field | Value |
|---|---|
| Owner (role) | Compliance officer |
| Schema version | 1 |
| Change rule | Additive column = minor version, with consumers notified in the PR. Type or meaning change = new version, migration and sign-off from every consumer below. |
| Freshness | real-time, same transaction as the action |
| Sensitivity | **direct (linked)** |
| Row-level security | none needed for writes; reads by compliance (and a patient's own events, planned) |
| Source | every service, via services.platform.audit.write |

## Checks (each is a test or a database constraint)

- append-only (no UPDATE/DELETE grant + trigger)
- actor_id, actor_role, purpose not null
- every record read and write produces one row

## Consumers, and what breaks for each when the schema changes

- 'who saw this record?' query
- trace links
- incident review
