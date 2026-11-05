# Privacy and compliance

MedPal handles health data, so privacy is designed in, not added on. This page maps each obligation to the control that meets it and the test that proves it. **A control without a test doesn't count as done.**

**Status:** ✅ built and tested · 🟡 partly built · ⏳ planned

> **Legal note.** Rows that mention India's Digital Personal Data Protection (DPDP) Act 2023 and its Rules paraphrase them at a high level. Exact obligations, such as breach-notice timelines or log-retention periods, should be confirmed with counsel before any real deployment. This is an engineering project, not legal advice.

## 1. Data residency and what may leave

| Obligation | Control | Proof | Status |
|---|---|---|---|
| Identified health data stays inside the deployment boundary | Identified data is stored and processed in-boundary; only de-identified text may leave | Egress adapter tests | ✅ |
| Only de-identified text reaches an external LLM | Microsoft Presidio with India recognisers; reversible token map kept in-boundary ([ADR-0006](adr/0006-presidio-deidentification.md)) | `tests/unit/test_phi_scrubber.py` (66 cases) | ✅ |
| Fail closed if anything slips through | Independent second pass `assert_clean()` raises `EgressBlocked` | `test_assert_clean_blocks_a_leftover_identifier` | ✅ |
| Indian identifiers are recognised | Presidio built-ins (Aadhaar, PAN, voter ID, passport, vehicle) plus custom (mobile, ABHA number and address, MRN, labelled DOB, pincode with context) | Parametrised identifier tests | ✅ |
| Names are caught in lowercase and Hinglish text | Per-request known identities, a common-names list, "naam X" cues; spaCy NER switched off for Hinglish | `test_names_do_not_leak` (40 cases) | ✅ |
| Scrubbing doesn't destroy clinical meaning | Over-scrub guards; dates and lab values kept; overlaps resolved by severity | `test_clinical_text_is_unchanged` | ✅ |
| Embeddings don't become a hidden way out | In-boundary embedding adapter ([ADR-0007](adr/0007-exact-vector-search-per-patient.md)) | `test_local_embedding_shape_is_fixed_for_pgvector_schema` | 🟡 deterministic adapter; production model planned |
| Traces and logs don't leak data | Self-hosted tracing; no request bodies in logs | — | ⏳ |
| Consultation audio (a voice is identifying) stays in-boundary | Local faster-whisper adapter; audio held in memory, never stored or sent to chat providers | `test_local_speech_uses_in_memory_audio`, `test_speech_rejects_invalid_audio_and_unconfigured_model` | 🟡 model provisioning and real audio evaluation external |

## 2. Identifiers with special restrictions

| Obligation | Control | Proof | Status |
|---|---|---|---|
| Aadhaar numbers must not be stored | Detected (Verhoeff checksum) and **blocked**, not tokenised, because a reversible map would be storage | `test_valid_aadhaar_is_blocked_not_tokenised`, `test_upload_blocks_aadhaar_before_storage` | ✅ |
| ABHA (national health ID) handled as a direct identifier | `patient.abha_id`; tokenised on egress | Identifier tests | ✅ |

## 3. Consent and purpose

| Obligation | Control | Proof | Status |
|---|---|---|---|
| Consent is specific, time-bound and revocable | `consent` row with grantee, scope, purpose, expiry and `revoked_at`; a column grant lets the patient revoke but never extend | `test_caregiver_needs_valid_unrevoked_consent`, `test_consent_service_grants_lists_and_revokes` | ✅ |
| Consent is checked on every read, by the database | Row-level security through one scope function ([ADR-0003](adr/0003-row-level-security.md)) | `tests/integration/test_rls.py`: queries omit the app filter | ✅ |
| Only the patient can grant consent on their own record | Insert policy on `consent` | `test_patient_cannot_grant_consent_on_someone_elses_record` | ✅ |
| Purpose recorded for every access | `audit_event.purpose` is NOT NULL | Schema | ✅ |
| Guardian consent for minors and dependants | — | — | ⏳ needs legal input |

## 4. Access control and audit

| Obligation | Control | Proof | Status |
|---|---|---|---|
| The application cannot bypass row-level security | App connects as `medpal_app` (NOSUPERUSER, NOBYPASSRLS); the owner role is used only for migrations | `test_app_role_cannot_bypass_rls` | ✅ |
| Least privilege per role | Access matrix as RLS policies plus verb and column grants | Per-role RLS tests (patient, caregiver, doctor, desk, compliance, system) | ✅ |
| No identity leaks between requests on pooled connections | Identity set with transaction-local scope | `test_context_does_not_leak_across_pooled_connections` | ✅ |
| Identities come from authentication, never from model output | `AuthContext` injected into graph state; OIDC claims or dev headers are the only identity source | OIDC claim tests, triage API tests | 🟡 OIDC verifier built; production IdP config external |
| A user can't act on someone else's run | Thread-ownership check on resume | `test_cannot_resume_someone_elses_thread` | ✅ |
| Dev authentication can never run in production | Settings validator refuses `auth_mode=dev` when `env=prod` | Config validator | ✅ |
| Every write is audited | `audit.write` in the same transaction as the write | `test_booking_writes_audit_event` | ✅ |
| Every read of a record is audited | One audit row per cited document read | `test_records_qa_requires_verified_citations_and_audits_reads` | ✅ |
| The audit trail can't be altered | No UPDATE/DELETE grant, plus a trigger that blocks the owner too | `test_audit_event_is_append_only` | ✅ |

## 5. Human oversight

| Obligation | Control | Proof | Status |
|---|---|---|---|
| The assistant never diagnoses | A draft red-flag gate runs before matching; diagnosis and dose questions hand off | Triage and records Q&A tests | 🟡 rules need clinician sign-off |
| Emergencies reach a human | An emergency handoff ticket, with fixed guidance to the patient | `test_emergency_creates_ticket` | ✅ |
| The patient chooses the slot | Booking only after the patient picks, validated against the slots offered | `test_choice_outside_offered_slots_is_rejected_and_asked_again` | ✅ |
| Nothing auto-signs a clinical note | Signed notes are immutable (trigger, even for the owner); only the encounter's doctor may insert | `test_doctor_signs_note_atomically_with_audit` | ✅ |
| Software never substitutes medicines | `prescription.substitute_ok` set only by a named human | Schema | 🟡 |

## 6. Retention

| Obligation | Control | Status |
|---|---|---|
| Consultation audio is not retained | Current transcription uses in-memory audio only; no persisted audio to expire. Any future recording store needs an audited deletion job and lifecycle policy | ✅ current non-retention; recording retention workflow not built |
| Checkpoints (they contain PHI) are not kept indefinitely | Retention job; state kept lean (~12.8 KB per triage run, measured) | ⏳ |
| Erasure on request | Cascading delete of a patient's documents, with an audit event | ⏳ |

## 7. Security hygiene

| Obligation | Control | Status |
|---|---|---|
| No secrets in the repository | `.env` gitignored; only `.env.example` committed | ✅ |
| AI coding assistants never see identified data | Development uses only the synthetic generated layer | ✅ |
| Prompt injection can't cross patient scope | Retrieval scope enforced by SQL RLS and tested with real Postgres; dedicated adversarial document evaluations still pending | 🟡 |
