# Table: `consent`

| Field | Value |
|---|---|
| Owner (role) | Compliance officer |
| Schema version | 1 |
| Change rule | Additive column = minor version, with consumers notified in the PR. Type or meaning change = new version, migration and sign-off from every consumer below. |
| Freshness | real-time; checked on every read |
| Sensitivity | **direct (linked)** |
| Row-level security | grantee, the granting patient, compliance; patient may only set revoked_at (column grant) |
| Source | created by patients at runtime; dev seed: Lata grants her daughter Asha read access for 180 days |

## Checks (each is a test or a database constraint)

- expires_at > granted_at
- scope subset of {records:read, appointments:read, appointments:write}
- granted_by is the patient's own user
- revoked_at set only, never cleared

## Consumers, and what breaks for each when the schema changes

- app_allowed_patients(): every clinical read breaks if semantics change
- caregiver UI
