# Table: `clinical_note (note_version)`

| Field | Value |
|---|---|
| Owner (role) | Clinical lead |
| Schema version | 1 |
| Change rule | Additive column = minor version, with consumers notified in the PR. Type or meaning change = new version, migration and sign-off from every consumer below. |
| Freshness | on signature |
| Sensitivity | **clinical** |
| Row-level security | read: allowed patients + compliance; insert: the encounter's doctor only |
| Source | scribe graph after doctor sign-off (planned) |

## Checks (each is a test or a database constraint)

- immutable: UPDATE/DELETE blocked by trigger, even for the owner
- content_hash matches soap_json
- signed_by is the encounter's doctor
- draft_json kept for edit distance

## Consumers, and what breaks for each when the schema changes

- patient records
- pharmacy (via prescription)
- edit-distance metric
