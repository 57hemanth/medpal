# Lessons learned

Real mistakes made while building MedPal, each with what went wrong, why, the fix, and **the test that now stops it coming back**. MedPal was built with an AI coding assistant, and every diff was reviewed. Several of these are places where a first attempt, mine or the assistant's, looked right and wasn't.

## Privacy and security

**1. Row-level security that protected nothing.**
- *What happened:* the app connected to Postgres as the Docker image's default user, which is a superuser. Superusers bypass RLS entirely, even with `FORCE ROW LEVEL SECURITY`, so every policy test would have passed while protecting nothing.
- *Fix:* a dedicated `medpal_app` role (NOSUPERUSER, NOBYPASSRLS) for the app; the owner role only for migrations.
- *Test:* `test_app_role_cannot_bypass_rls`.
- *Lesson:* check *who* you connect as before writing a single policy.

**2. Testing only one direction of de-identification.**
- *What happened:* the first name-detection probe reported 0 leaks in 80 English sentences. A Hinglish probe then showed spaCy's English model labelling romanised Hindi as people's names: "meri dadi ko das din se bukhar hai" (grandma has had a fever for ten days) became `<PERSON_1>`. That erases the clinical content before the model ever sees it.
- *Fix:* detect Hinglish and use an engine without the NER recogniser for it.
- *Test:* `test_clinical_text_is_unchanged`.
- *Lesson:* a scrubber needs tests for **over-scrubbing** as much as for leaks.

**3. Filtering at the wrong layer.**
- *What happened:* the first Hinglish fix removed spaCy's results *after* analysis. But Presidio de-duplicates nested results *inside* the engine, so a name-list match ("sharma") sitting inside a bogus spaCy span ("sharma ko") had already been thrown away. Every surname leaked, 10 out of 10.
- *Fix:* remove the recogniser from a second engine instead of filtering its output.
- *Test:* `test_names_do_not_leak`, Hinglish cases.

**4. A harmless label hiding an identifier.**
- *What happened:* spaCy labels digit runs as dates with 0.85 confidence. Dates are kept on purpose, so overlapping spans resolved by score alone let a "date" shadow an Indian mobile number or an ABHA ID (0.55–0.7), and the number leaked.
- *Fix:* resolve overlaps by **severity first** (block > tokenise > keep), then by score.
- *Test:* `test_indian_mobile_formats_are_tokenised`.

**5. Library defaults are not locale defaults.**
- *What happened:* Presidio's default English registry loads US and UK recognisers. The UK NHS-number recogniser claimed 10-digit Indian mobiles. Presidio's own India recognisers aren't loaded by default at all.
- *Fix:* remove the foreign recognisers; add the India ones explicitly.

**6. A word that is both a name and a number.**
- *What happened:* "Das" is a common surname and also Hindi for "ten" ("das din se" = for ten days). A names list containing it would have erased how long a symptom had lasted.
- *Fix:* removed from the list, with the reason written next to it.

**7. Grants that let a patient do more than intended.**
- *What happened:* the first draft gave the app full UPDATE on `consent`, so a patient could have *extended* a consent's expiry instead of only revoking it.
- *Fix:* column-level grants (`UPDATE (revoked_at)` only).
- *Test:* `test_patient_can_revoke_but_not_extend_consent`.

**8. Identity tables without protection.**
- *What happened:* `patient` and `app_user` hold names, phone numbers and dates of birth, but the first RLS draft protected only clinical tables.
- *Fix:* added policies: self, treating or consented scope, front desk demographics, compliance.
- *Test:* `test_desk_sees_demographics_patient_sees_only_self`.

**9. A lock that needed a dangerous permission.**
- *What happened:* `SELECT … FOR UPDATE` requires UPDATE privilege on the table. Granting it would have let the app change slot capacity.
- *Fix:* a transaction-scoped advisory lock per slot ([ADR-0005](adr/0005-booking-concurrency.md)).
- *Test:* `test_concurrent_bookings_never_exceed_capacity` (20 parallel attempts → exactly 1 booking).

## Correctness only real data reveals

**10. A query written against 54 rows.**
- *What happened:* the doctor shortlist was fine on a tiny dev dataset. On 480,000 slots it walked about 30,000 rows per request and counted bookings for each: 60 ms with 6,200 bookings, and growing.
- *Fix:* `LATERAL … LIMIT 1` per doctor stops at the first free slot. Now 4.5 ms, and the cost grows with how booked-up doctors are, not with the size of the calendar.
- *Test:* `tests/integration/test_shortlist_db.py`.

**11. Offering doctors in the wrong city.**
- *What happened:* with the full network loaded, a Pune patient was offered three Hyderabad doctors. The shortlist knew nothing about where the patient lives.
- *Fix:* patient city, language and preferred clinic, read *as the caller* under RLS.
- *Test:* `test_patient_city_filters_and_language_ranks_first`.

**12. Times in the wrong time zone.**
- *What happened:* appointment times came back in UTC. "02:30" was really 08:00 in India, so a patient would have arrived 5½ hours off.
- *Fix:* clinic-local timestamps plus a display string ("Mon 9 Nov, 08:00").
- *Test:* `test_booking_reply_uses_the_human_display_time`.

**13. A timestamp comparison that would have deleted a third of the data.**
- *What happened:* in the No-Shows dataset, `AppointmentDay` has no time component (always midnight). "Scheduled after the appointment" compared as timestamps flags 38,568 same-day bookings (35%); compared as dates, only 5 are real violations.
- *Fix:* profile the data before writing the rule.
- *Test:* `test_same_day_booking_is_kept_despite_later_timestamp`.

**14. Estimates are not measurements.**
- *What happened:* checkpoint storage was estimated at 1–4 GB/day. Measured: ~12.8 KB per triage run, so 0.35–0.9 GB/day. The slot table, estimated at 80 bytes/row, is 214 with indexes.
- *Lesson:* measure before you size.

## Frameworks and tooling

**15. Resumed nodes run twice.**
- *What happened:* in LangGraph, a node that calls `interrupt()` re-runs from its start when resumed.
- *Fix:* confirmed with a minimal repro before writing graph code; the node that pauses has no side effects, and booking lives in the next node.
- *Test:* `test_routine_intake_pauses_with_candidates_then_books_on_resume` (the shortlist tool runs exactly once).

**16. A client could pick any slot.**
- *What happened:* the resume payload originally trusted whatever `slot_id` the client sent.
- *Fix:* it's now validated against the slots actually offered.
- *Test:* `test_choice_outside_offered_slots_is_rejected_and_asked_again`.

**17. Tests that polluted the dev database.**
- *What happened:* integration fixtures wrote test doctors into the development database, and they showed up in a manual smoke test.
- *Fix:* a throwaway `medpal_test` database, dropped and rebuilt from migrations on every run.

**18. A test that couldn't fail.**
- *What happened:* the first "signed notes are immutable" test updated an empty table, and a row-level trigger never fires when there are no rows.
- *Fix:* insert a signed note first.
- *Lesson:* make a test fail at least once before you trust it.

**19. Asserts are not guards.**
- *What happened:* Python strips `assert` statements under `-O`.
- *Fix:* runtime checks on the booking path raise explicit errors.

**20. The CLI isn't your test runner.**
- *What happened:* `alembic` couldn't import the project, because the repo root wasn't on `sys.path`, yet the tests passed because pytest sets the path.
- *Fix:* `prepend_sys_path` in `alembic.ini`. Found by rendering migrations offline (`alembic upgrade head --sql`).

**21. Verify the probe before trusting its result.**
- *What happened:* two smoke-test scripts were themselves broken. zsh doesn't split `$var` into words, and `docker exec` without `-i` ignores a heredoc. They produced a 401 and an empty result that looked like application bugs.
- *Lesson:* read the output before believing it.

## What only a real model showed

Every suite above runs on a local fake model. These came from running the product against Gemini (`make live-check`, `make load-test`).

**22. A model call with no deadline.**
- *What happened:* under load, one request sat for eight minutes waiting on the provider; the Gemini client's default timeout is none, with six retries. A stuck provider could hold a patient's request indefinitely.
- *Fix:* every provider attempt has a hard deadline (`MEDPAL_CHAT_TIMEOUT_SECONDS`, default 30) enforced by the fallback chain, and SDK retries are kept low so the chain, not the SDK, decides what happens next. A timeout is a provider failure: next provider, then a safe "unavailable".
- *Test:* `test_a_hung_provider_times_out_and_the_next_one_answers`, `test_when_every_provider_hangs_the_caller_gets_model_unavailable_quickly`.

**23. A safety rule tested only on the phrasings it was written for.**
- *What happened:* "How much atorvastatin should I take for this LDL?" was answered from the record. The doctor-review rule was six keywords; on a fresh held-out set it caught 30% of advice questions.
- *Fix:* two layers. Broader rules, gated on an evaluation set (recall 100%, over-refusal ≤ 10%), and a `needs_doctor` flag in the model's answer schema that can only send a question *to* a doctor. Together they caught 10/10 held-out advice questions with no plain questions refused.
- *Test:* `make eval` (gate), `make live-check` (held-out, real model).

**24. Estimated tokens hide the real cost of thinking models.**
- *What happened:* structured calls were metered by estimating tokens from the output text. A thinking model spent about 90 output tokens to return a one-word label; the estimate said 1. The cost sheet would have been several times too low.
- *Fix:* structured calls ask LangChain for the raw provider message (`include_raw`) and meter its real usage, thinking included. The usage travels in a per-task context variable, so parallel supervisor branches can't swap numbers.
- *Test:* `test_structured_calls_meter_real_usage_including_thinking_tokens`.

**25. "Sugar" is not in the report.**
- *What happened:* "mera sugar test ka result kya tha?" found nothing. Full-text search ANDed every word of a conversational question, and reports say "glucose" and "HbA1c", not "sugar".
- *Fix:* an OR query of the meaningful words (English and Hinglish fillers dropped) plus a reviewed map of lay terms to report terms, sanitised to `[a-z0-9]` before it reaches `to_tsquery`.
- *Test:* `test_lay_and_hinglish_questions_reach_the_right_page`, `test_lexical_query_cannot_inject_tsquery_syntax`.

**26. A prompt instruction with no place to go.**
- *What happened:* the draft prompt said to write "[doctor to specify]" when the doctor names a drug class. The model put the placeholder in the *medicines list*, and the quick-draft endpoint rejected the whole note.
- *Fix:* the prompt says where the placeholder goes (the plan) and what the medicines list may hold (drug names as spoken). The endpoint now grounds medicines like the review graph does (keep what the transcript names, show the rest as rejected) instead of failing.
- *Test:* `test_draft_note_rejects_medicines_absent_from_the_transcript_and_reports_them`; `make live-check` scribe cases.

**27. Reasoning effort is a per-task setting.**
- *What happened:* low thinking halved routing latency with the same accuracy, so it was tried for answers too. It made no real difference to answer latency and lost a citation on one records answer.
- *Fix:* `MEDPAL_CHAT_SMALL_THINKING_LEVEL=low` for routing only; answers and drafts keep the default.
- *Lesson:* measure each tier separately; a setting that's right for labels can be wrong for answers.

**28. A screen can lie even when the API is right.**
- *What happened:* the sharing page showed a consent that a parent had granted *to* the patient as if the patient had shared it, with a revoke button that would fail. The API returned exactly what row-level security allowed; the page assumed every row was the viewer's own.
- *Fix:* the page tells "you shared" from "shared with you" by the record's owner and offers revoke only on your own; the API returns names where RLS allows.
- *Test:* `ConsentPage.test.tsx`. Found by taking screenshots of every role's pages, not by unit tests.

**29. The biggest model isn't the right default for every step.**
- *What happened:* records answers on the largest model missed the latency target under load (p95 14 s against 8 s). The same live check run on the faster model scored the same 40/40, at a p95 of 3.6 s and a quarter of the cost.
- *Fix:* `MEDPAL_RECORDS_MODEL_TIER`, chosen by measurement: answers on the small tier, note drafts on the large one.
- *Lesson:* pick a model per task, with a quality check and a load test side by side, not by size.

**30. "Tracing on every run" had a hole.**
- *What happened:* the quick-draft endpoint called the model outside any trace, so its cost never reached the cost sheet. Noticed only because the cost report refused to total a window with no scribe runs.
- *Fix:* the endpoint runs inside a trace like every other model call.
- *Test:* `test_quick_scribe_drafts_are_traced`.

**31. An assistant with no memory of its own conversation.**
- *What happened:* right after booking, "what is the doctor specialization?" was sent to the records search, which said it couldn't find it. Each message reached the supervisor alone, and "what is the…" looks like a report question.
- *Fix:* the chat sends its triage thread id with each message, and a `visit` specialist answers follow-ups from that run's saved state: no model and no search, only the caller's own thread. A follow-up that also describes a new symptom still starts a triage.
- *Test:* `test_a_follow_up_about_this_chats_booking_is_answered_from_it_not_from_records`, `test_follow_up_questions_are_answered_from_this_chats_booking_and_only_for_its_owner`, and the web test with the same conversation. Found by a person using the app, not by any suite.

**32. The privacy layer erased a suicide statement.**
- *What happened:* measuring the new model red-flag check on held-out phrasings, it missed "apni jaan lena chahta hoon" ("I want to take my own life"). The model wasn't at fault: the scrubber had sent it `<PERSON_1>`. With only one known Hindi word, the message wasn't treated as Hinglish, and spaCy read the whole sentence as a name.
- *Fix:* a NER "name" longer than four words is treated as a misread sentence (known names, the names list and "naam X" cues are separate recognisers and unaffected), and the Hinglish word list gained common verbs and pronouns. All 66 existing leak and over-scrub cases still pass.
- *Test:* `test_short_hinglish_safety_statements_survive_scrubbing`, `test_names_are_still_removed_next_to_hinglish_safety_words`.
- *Lesson:* when a model step misses, read what it was actually sent before touching the prompt.

**33. "Rules first" vs "model first" is a labelling question as much as an accuracy one.**
- *What happened:* for specialty matching, rules-first with the model when unsure scored 30/30 on the tuned set and 27/30 on unseen phrasings; model-first scored 24/30 and 29/30. Most of model-first's "misses" (finger-joint swelling → Rheumatology, vomiting since morning → General Medicine) are defensible; the rules' misses (a groin lump that bulges on coughing → Pulmonology) are not.
- *Decision:* rules first for now (best on the labels we have, no model latency when the rules are sure), with the comparison recorded for clinical review of the labels.

## Design choices worth copying

- **Domain names in code** (`triage`, `records`, `scribe`), not internal codes: opaque names make every new reader look something up.
- **Generate structured data with seeded code, not an LLM** ([ADR-0004](adr/0004-generated-directory-in-code.md)): reproducible, free, and it can't hallucinate a specialty.
- **Test what the code *must not* do** (leak, double-book, edit a signed note) as carefully as what it does.
