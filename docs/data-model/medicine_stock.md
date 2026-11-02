# Table: `medicine_stock`

| Field | Value |
|---|---|
| Owner (role) | Pharmacy lead |
| Schema version | 1 |
| Change rule | Additive column = minor version, with consumers notified in the PR. Type or meaning change = new version, migration and sign-off from every consumer below. |
| Freshness | ≤ 24 h (nightly CSV); > 48 h shown as 'unknown' |
| Sensitivity | **operational** |
| Row-level security | none; app may update qty/as_of only (column grant) |
| Source | A-Z Medicine Dataset of India (Kaggle) + generated stock levels (planned) |

## Checks (each is a test or a database constraint)

- qty ≥ 0
- as_of present on every row
- (clinic_id, medicine_id) unique

## Consumers, and what breaks for each when the schema changes

- stock flags on drafts (StockSource interface, CSV and API adapters)
