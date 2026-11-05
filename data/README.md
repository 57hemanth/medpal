# Data

All data in this repository is **synthetic or public**. Raw downloads live in `data/raw/` and generated outputs in `data/synthetic/output/`; both are gitignored and reproducible.

```bash
make generate   # generated network: clinics, doctors, 480k slots (seeded, ~2 s)
make data       # clean the public datasets you have downloaded into data/raw/
make seed       # RESET the dev database and load everything (+ dev identities)
```

## Sources and licences

Every source's licence is recorded **before** any row is used.

| # | Source | Where | Licence | Rows (raw → clean) | Status |
|---|---|---|---|---|---|
| 1 | Medical Appointment No Shows (Joni Hoppen / Aquarela) | OpenML [43439](https://www.openml.org/d/43439), mirror of Kaggle `joniarroba/noshowappointments` | **CC BY-NC-SA 4.0** | 110,527 → 110,516 | ✅ cleaned |
| 2 | Medical Transcriptions | Kaggle `tboyle10/medicaltranscriptions` | check on download | ~5,000 | ⏳ |
| 3 | Disease Symptom Prediction | Kaggle `itachi9604/disease-symptom-description-dataset` | check on download | ~4,900 | ⏳ |
| 4 | A-Z Medicine Dataset of India | Kaggle `shudhanshusingh/az-medicine-dataset-of-india` | check on download | 250,000+ | ⏳ |
| 5 | Healthcare Dataset (synthetic) | Kaggle `prasad22/healthcare-dataset` | check on download | ~55,000 | ⏳ |
| 6 | Generated network | `data/synthetic/generate.py` (seed 20261102) | this repo's licence | 500 doctors, 480,000 slots | ✅ |

**CC BY-NC-SA 4.0 (No-Shows):** non-commercial, attribution, share-alike. The raw file is **not redistributed** here; the transform downloads nothing and runs on your local copy. A real deployment would use its own scheduling history.

**Getting the Kaggle datasets:** create an API token at kaggle.com → Settings → API and save it as `~/.kaggle/kaggle.json` (mode 600). Or download the zips by hand into `data/raw/<source>/`. Then run `make data`.

## Cleaning: No-Shows (`data/transforms/no_shows.py`)

Every input row is accounted for: either kept, or dropped with a reason.

| Problem in the raw data | What we do | Result |
|---|---|---|
| Negative ages | drop, tallied | 1 |
| Ages above 110 | drop (threshold documented in code) | 5 |
| Scheduled after the appointment | drop, comparing **dates**: `AppointmentDay` has no time, so a timestamp comparison would wrongly flag 38,568 same-day bookings (35%) | 5 |
| Target `No-show` reads backwards ("No" = attended) | renamed and flipped to `attended` | — |
| Source patient ids | pseudonymised (`patient_key`, sha256, truncated) | — |
| Brazilian neighbourhoods | stable mapping onto the 22 fictional clinics | 81 → 22 |

Row accounting: 110,527 = 110,516 kept + 11 dropped ✓. Attended rate after cleaning: 79.8%. Tests: `data/transforms/tests/test_no_shows.py`, including a full-dataset count check that runs when the raw file is present.

## The generated network (`data/synthetic/`)

| What | Value |
|---|---|
| Hospitals / clinics | 6 / 22 (11 in Pune, 11 in Hyderabad; fictional names on real localities) |
| Specialties | 38 outpatient specialties (a modelling choice) |
| Doctors | 500, at least 10 per specialty; 49.8% female; unique names; languages follow the city |
| Slots | 480,000 = 500 doctors × 60 working days × 16 fifteen-minute slots; no Sundays; always inside clinic hours |
| Formulary | 25 common generics stocked at every clinic; about 15% of clinic/medicine pairs out of stock so the scribe's stock flags are exercised; `as_of` is stamped at seed time like a nightly feed |

Why code and not an LLM: see [ADR-0004](../docs/adr/0004-generated-directory-in-code.md). Every run writes `generated_manifest.json` (seed, version, counts, bias audit). Tests: `data/synthetic/tests/test_generate.py`.

## Sizing (measured on the local stack)

| Store | Measured | Projection | Note |
|---|---|---|---|
| Slot calendar | 214 B/row including indexes → **98 MB** for 480k rows | ~98 MB per 60 working days | UUID keys and two indexes; a naive 80 B/row estimate is 2.6× low |
| Triage checkpoints | **~12.8 KB payload per run** (~33 KB with indexes), ~8.6 rows/run | ~0.35–0.9 GB/day at ~27k runs/day | needs a retention job; scribe runs will be larger (transcripts) |
| Vector index | — | 60k chunks × 1,024 × 4 B ≈ 246 MB (fp32) | measure when records ingest lands |
| Consultation audio | — | ~1 MB/min; deleted within 24 h | lifecycle rule |
