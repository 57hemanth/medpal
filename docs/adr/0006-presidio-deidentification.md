# ADR-0006: De-identify with Microsoft Presidio, extended for India, before any text leaves

- **Status:** accepted
- **Context:** Identified health data must stay inside the deployment boundary (India's DPDP Act constraints). Only de-identified text may reach an external LLM. Patients write in English and in Hinglish (romanised Hindi), often in lowercase, and use Indian identifiers: ABHA health IDs, +91 mobiles, PAN, voter IDs. Aadhaar numbers must not be stored at all.
- **Options:**
  1. *Regex only.* Catches formatted numbers, misses names.
  2. *Ask an LLM to redact.* Sends the identified text to the very model it is meant to protect.
  3. *Microsoft Presidio (spaCy NER + pattern recognisers), extended and tested for India.*
- **Decision:** Option 3 (`services/platform/phi/`):
  - Presidio's built-in India recognisers (Aadhaar, PAN, voter ID, passport, vehicle registration) are turned on. They aren't loaded by default for English.
  - **US/UK recognisers are removed:** the UK NHS-number recogniser was claiming 10-digit Indian mobile numbers.
  - Custom recognisers cover Indian mobiles, ABHA number and address, MRN, labelled date of birth, pincode (only with context, so lab values like "250000" survive), a common-Indian-names list, and **per-request known identities** (the caller and their consented patients).
  - **Overlaps resolve by severity before score** (block > tokenise > keep). spaCy labels digit runs as DATE_TIME with high confidence; without this rule a phone number would leak.
  - **Hinglish mode:** spaCy's English NER labels romanised Hindi as PERSON ("mein dard hai", "bukhar hai"), which would erase clinical meaning. Hinglish text uses a second engine without the NER recogniser; names come from the known identities, the names list and "naam X" cues.
  - Reversible token map (`<PERSON_1>`), kept inside the boundary. **Aadhaar is blocked, never tokenised**, because a reversible map would count as storing it.
  - A second, independent detection pass (`assert_clean`) fails closed.
- **Revisit trigger:** leaks show up in the egress replay test, or Marathi or Telugu support arrives (word lists and possibly a multilingual NER model).
- **Consequences:**
  - *Easier:* one place to reason about what can leave; tests cover both leaks and over-scrubbing.
  - *Harder:* the English spaCy model is about 400 MB. Name lists need maintenance. Tests must check both directions: the first version passed every leak test while erasing Hinglish clinical text.
- **Proof:** `tests/unit/test_phi_scrubber.py` (66 cases) covers identifier formats, Aadhaar blocking and checksum, names in English, lowercase and Hinglish, clinical text left unchanged, round trips, and fail-closed egress.
- **Versions:** presidio-analyzer 2.2.366 · spaCy 3.8 · en_core_web_lg 3.8.0 (pinned wheel).
- **Checked on:** 2026-11-02
