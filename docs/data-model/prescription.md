# Table: `prescription`

| Field | Value |
|---|---|
| Owner (role) | Clinical lead |
| Schema version | 1 |
| Change rule | Additive column = minor version, with consumers notified in the PR. Type or meaning change = new version, migration and sign-off from every consumer below. |
| Freshness | on signature |
| Sensitivity | **clinical** |
| Row-level security | read: allowed patients, pharmacist, compliance; insert: doctor |
| Source | scribe graph after sign-off |

## Checks (each is a test or a database constraint)

- references a signed note_version
- substitute_ok set only by a named human (set_by)
- medicine_text always kept, medicine_id when matched

## Consumers, and what breaks for each when the schema changes

- pharmacy reservation task
- patient notification
