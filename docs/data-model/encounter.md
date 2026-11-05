# Table: `encounter`

| Field | Value |
|---|---|
| Owner (role) | Clinical lead |
| Schema version | 1 |
| Change rule | Additive column = minor version, with consumers notified in the PR. Type or meaning change = new version, migration and sign-off from every consumer below. |
| Freshness | real-time |
| Sensitivity | **clinical** |
| Row-level security | direct RLS for allowed patients and the encounter doctor (migration 0004) |
| Source | created when a consultation starts |

## Checks (each is a test or a database constraint)

- appt_id unique
- patient_id and doctor_id match the appointment

## Consumers, and what breaks for each when the schema changes

- scribe graph
- signed notes
