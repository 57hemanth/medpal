# Threat model

STRIDE plus the threats specific to LLM systems. Each row names the control **and the test that proves it**; a control without a proof is listed as a gap. Status: ✅ proven by a test · 🟡 built, proof pending · ⏳ planned.

## Patient data

| Flow | Threat | STRIDE | Control | Proof | Status |
|---|---|---|---|---|---|
| Records Q&A | A patient reads another patient's records | Information disclosure | Postgres RLS via one scope function; explicit target-patient filter; the app role can't bypass RLS | `test_rls.py`, `test_app_role_cannot_bypass_rls` | ✅ |
| Records Q&A | Instructions hidden in an uploaded PDF make the assistant reveal others' data | Information disclosure (prompt injection) | Retrieval scoped in SQL, so the injected page is never retrieved for anyone else; citations verified against retrieved chunks | `test_records_redteam.py` | ✅ |
| Records Q&A | A caregiver for two people gets their reports mixed | Information disclosure | A caregiver must name one patient; retrieval filters to that patient | `test_caregiver_with_two_consents_must_choose_one_patient` | ✅ |
| Records Q&A | A model invents citations or facts | Tampering (integrity) | Citation ids must be in the retrieved set; otherwise "insufficient evidence" | `test_records_qa_rejects_unretrieved_citations`, red-team obeying model | ✅ |
| Egress | Identified text reaches a vendor's logs | Information disclosure | Presidio scrubber with a fail-closed second pass; internal network; allowlisting egress proxy (ADR-0008) | `test_phi_scrubber.py`, `test_egress_proxy.py`, `make boundary-check` | ✅ |
| Egress | Embeddings or traces become a hidden way out | Information disclosure | Embeddings computed in-boundary; traces are metadata only, stored in-boundary (ADR-0011) | `test_spans_never_contain_prompt_or_response_text` | ✅ |
| Uploads | An Aadhaar number is stored | Information disclosure (legal) | Blocked at upload before storage (Verhoeff-validated) | `upload containing an Aadhaar number is rejected` (live smoke), `test_valid_aadhaar_is_blocked_not_tokenised` | ✅ |
| Data at rest | A database dump walks out | Information disclosure | Least-privilege app role; no shared admin account in the app; encryption at rest is a deployment duty | access-review checklist | ⏳ |

## Identity and authorisation

| Flow | Threat | STRIDE | Control | Proof | Status |
|---|---|---|---|---|---|
| All APIs | Someone poses as a patient or caregiver | Spoofing | OIDC bearer tokens verified against the issuer's keys; dev headers refused in production | config validator; OIDC tests | ✅ |
| Triage/booking | A model or tool argument names another patient | Elevation of privilege | Identity comes from the auth context only; no tool takes a patient id | `test_tools_are_listed_with_safety_hints` (no `patient_id` input) | ✅ |
| Triage/scribe | Resuming someone else's paused run | Elevation of privilege | Thread-ownership check on every resume | `test_cannot_resume_someone_elses_thread` | ✅ |
| Scribe | A doctor starts or signs a consultation that isn't theirs | Elevation of privilege | Encounter creation limited to the appointment's doctor; signing limited to the encounter's doctor | `test_only_the_appointments_doctor_can_start…` | ✅ |
| Consent | A patient extends a consent, or grants one on someone else's record | Tampering | Column grant (revoke only); insert policy | `test_patient_can_revoke_but_not_extend_consent` | ✅ |
| Assistant | A model routing step rewrites a request, adds instructions or names another patient | Elevation of privilege / tampering | The model returns only clause numbers and labels; specialists get the person's own words; role decides which specialists may run | `test_specialists_get_the_patients_own_words_never_model_text`, `test_model_plan_is_used_but_cannot_exceed_the_role_or_invent_clauses` | ✅ |
| Assistant | Routing delays or drops an emergency | Safety | Red-flag rules run on the whole message before any model; an emergency goes to triage alone | `test_patient_emergency_goes_to_triage_alone_before_any_model` | ✅ |
| MCP tools | An agent calls tools without an identity | Spoofing | Same identity resolver as the API; headers alone are never trusted as identity | `test_unauthenticated_calls_are_refused` | ✅ |

## Integrity and accountability

| Flow | Threat | STRIDE | Control | Proof | Status |
|---|---|---|---|---|---|
| Signed notes | A note is edited after signing | Tampering | Immutable versions (trigger, even for the owner); a second signature is refused | `test_signed_notes_are_immutable_even_for_the_owner`, `AlreadySigned` | ✅ |
| Signed notes | A doctor denies having signed | Repudiation | The signature is an authenticated action; content hash; audit row with actor | `test_signing_writes_note_and_prescriptions_once` | ✅ |
| Audit | An admin alters the audit trail | Tampering / repudiation | No UPDATE/DELETE grant; trigger blocks the owner too | `test_audit_event_is_append_only` | ✅ |
| Scribe | The model invents a medicine | Tampering (clinical) | Medicines kept only if named in the transcript; rejected ones are shown; the doctor signs | `test_model_medicine_absent_from_transcript_is_rejected_and_shown` | ✅ |

## Availability and safety

| Flow | Threat | STRIDE | Control | Proof | Status |
|---|---|---|---|---|---|
| Triage | An emergency is missed | Safety | Rules first; a structured safety screen independent of wording (ADR-0010); a model second pass that may only add (ADR-0013) | `make eval` (recall 100% gate), safety-screen tests, `make live-check` (24/25 unseen) | ✅ |
| Triage | The privacy layer erases the words that matter | Safety | Over-scrub guards: implausibly long NER names dropped; Hinglish detection | `test_short_hinglish_safety_statements_survive_scrubbing` | ✅ |
| Booking | Scripted bookings hoard slots | Denial of service | Idempotency keys; advisory lock plus capacity; patient-only booking | `test_concurrent_bookings_never_exceed_capacity` | ✅ (rate limiting ⏳) |
| Models | Provider outage or malformed output | Denial of service | Fallback chain; `ModelUnavailable` degrades to a human path; triage emergencies need no model | `test_fallback_*`, `test_records_qa_degrades_safely…` | ✅ |
| Models | A provider accepts the call and never answers | Denial of service | Hard deadline per provider attempt; low SDK retries; timeout falls through to the next provider, then a safe "unavailable" | `test_a_hung_provider_times_out_and_the_next_one_answers` | ✅ |
| Records Q&A | The assistant gives medicine or dose advice from a report | Safety | Doctor-review rules (gated by `make eval`) plus a model `needs_doctor` flag that can only escalate | `make eval`, `make live-check` held-out set (10/10) | ✅ |
| Peak load | The morning rush exceeds latency targets | Denial of service | Stateless API; checkpoints in Postgres; queue for ingest | `make load-test` (p95 per endpoint) | 🟡 passes with the fake model; re-run with a real model |

## Known gaps

- **Rate limiting** per patient and per address: not built.
- **Encryption at rest** and backups: deployment responsibilities, not yet automated.
- **A doctor's appointment list** includes their patients' appointments with other doctors (row-level security grants by patient, not by appointment). Minor; to tighten.
- **Clinical sign-off** on the red-flag rules, safety-screen wording and specialty list.
