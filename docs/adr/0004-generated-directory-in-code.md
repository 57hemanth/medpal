# ADR-0004: Generate the doctor directory and slot calendar with seeded code, not an LLM

- **Status:** accepted
- **Context:** Public datasets have no doctor directory and no appointment calendar for an Indian clinic network, so both must be generated. An LLM is the obvious tool for "write 500 realistic doctors", but every field in a directory is structured: name, gender, specialty, clinic, languages, years in practice.
- **Options:**
  1. *LLM-written directory.* Realistic text, but it costs per run, isn't byte-reproducible, can invent things (a specialty that doesn't exist, implausible years), and still needs every row validated.
  2. *Seeded code* drawing on culturally coherent name pools and city-specific language rules. Free, byte-for-byte reproducible from a seed, and correct by construction.
  3. *Hybrid:* code for structure, an LLM for free-text bios. Nothing in scope needs bios.
- **Decision:** Option 2 (`data/synthetic/generate.py`):
  - every row is validated with pydantic and **rejected, never repaired**;
  - the output is audited for duplicates and bias: specialty split, clinic coverage, gender overall and per specialty, language mix;
  - seed, version and output are recorded together in `generated_manifest.json`;
  - every row is tagged `synthetic = true`.

  A calendar is arithmetic, so slots are generated the same way. An LLM stays reserved for free-text artefacts (sample lab reports, dictations), where text is the point.
- **Revisit trigger:** narrative profiles are needed, or a real directory becomes available and replaces the generated one.
- **Consequences:**
  - *Easier:* reproducible tests, no API cost, no hallucinated specialties, works offline.
  - *Harder:* realism depends on hand-curated name pools, which deserve review by people from each region. The 38-specialty list and its demand weights are a modelling choice.
- **Result (seed 20261102):**
  - 500 doctors, 0 rejected; 480,000 slots;
  - every specialty ≥ 10 doctors (min 10, max 31); every clinic 25–31 doctors;
  - 49.8% female overall (18–82% by specialty); no repeated names;
  - languages: en 100%, hi 75%, te 45%, mr 44%, ur 13%.
- **Proof:** `data/synthetic/tests/test_generate.py` (determinism, specialty floor, clinic coverage, no Sunday slots, slots inside clinic hours, a slot on every working day for every clinic).
- **Checked on:** 2026-11-02
