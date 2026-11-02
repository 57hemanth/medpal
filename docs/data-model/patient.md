# Table: `patient`

| Field | Value |
|---|---|
| Owner (role) | Records lead |
| Schema version | 2 (0003 added city, preferred_clinic_id) |
| Change rule | Additive column = minor version, with consumers notified in the PR. Type or meaning change = new version, migration and sign-off from every consumer below. |
| Freshness | real-time (registration) |
| Sensitivity | **direct** |
| Row-level security | self, consented caregiver, treating doctor, desk (demographics), compliance |
| Source | dev identities in infra/scripts/seed.py (synthetic); production: HIS FHIR Patient (read-only) |

## Checks (each is a test or a database constraint)

- patient_id unique
- abha_id unique when present
- dob <= today
- city in {Pune, Hyderabad} when present
- never stores an Aadhaar number (blocked at intake)

## Consumers, and what breaks for each when the schema changes

- triage shortlist preferences: breaks if city/language change type
- records scope: breaks if patient_id changes
- audit: patient_id on every event
