# ADR-0013: One bounded, prefetched model step inside triage

- **Status:** accepted (revisits the open trigger in [ADR-0010](0010-structured-safety-screen.md))
- **Context:** Free-text rules don't generalise. On phrasings they were never tuned on, the red-flag rules caught 5 of 25 emergencies and the specialty rules got 7 of 30 right (asking a question for most of the rest, and confidently wrong twice). The structured safety questions protect recall whatever the wording, but a patient can answer "no" and still describe an emergency in their own words. Every model call also slows the provider for everyone under load: adding one call per triage start pushed triage p95 from 25 ms to 11 s.
- **Options:**
  1. *Model call on triage start, red flags and specialty separately.* Best accuracy, but the first answer waits for the model, and two calls per run double the load.
  2. *One combined call after the safety questions, under a short deadline.* Fast first answer, but the call usually takes about as long as the deadline: half the checks were skipped and unseen-emergency recall fell to 16/25.
  3. **One combined call, started in the background at triage start and collected after the safety questions, under a deadline that counts only the time still to wait.**
- **Decision:** Option 3 (`services/agent/triage/assessor.py`, the `model_check` node):
  - Rules first. A rule hit goes straight to the emergency desk; the model is never asked and can never clear it.
  - The model's red-flag output may only **add** an emergency. Its specialty guess is used only when the specialty rules are unsure, only from the 38 specialties MedPal books into, and only at confidence ≥ 0.6; otherwise the patient gets one clarifying question. Its alternative specialty is shown, never booked.
  - The call starts while the patient reads the seven safety questions. If the result isn't ready within `MEDPAL_TRIAGE_MODEL_DEADLINE_SECONDS` (4) of them answering, triage continues on rules and the patient's explicit answers, the fully tested behaviour.
  - A resume on another app instance has no prefetch and makes the call live under the same deadline. New text after a clarification gets a fresh check.
  - The background call's spans are captured and replayed into the run that uses the result, so it is metered once, by its consumer.
  - With no real model configured (development and every test suite), the step is absent and triage is rules-only.
- **Measured (Gemini, 3 November 2026):**

  | | Rules only | Rules + model |
  |---|---|---|
  | Unseen emergencies caught | 5/25 | **24/25** (the miss, a pregnancy with severe pain, is outside the seven categories) |
  | Unseen specialty phrasings right | 7/30 | **27/30** (2 wrong, both from confident rules; 1 asks a question) |
  | Triage start p95 under load | 25 ms | 156 ms |
  | Step after the safety questions, p95 under load | 24 ms | 69 ms (2 of 59 checks hit the deadline) |

  Model-first specialty (model decides, rules as fallback) scored 29/30 on the unseen set but 24/30 against our tuned labels, where most "misses" are defensible alternatives. Rules-first stays until a clinician reviews the labels ([lessons learned](../lessons-learned.md) #33).
- **Revisit trigger:** clinical review of the specialty labels; an obstetric emergency category; provider throughput that lets the deadline drop.
- **Consequences:**
  - *Easier:* recall on unseen wording without making patients wait; a provider outage degrades to the tested rules path.
  - *Harder:* the prefetch is per-process memory (bounded, with a time limit); the live check and load test must model reading time to measure what patients experience.
- **Proof:** `tests/unit/test_triage_assessor.py` (when it runs, what it may and may not do, deadline, prefetch reuse and metering), `make eval` (rules-only figures), `make live-check` (rules + model on the held-out sets), `make load-test`.
- **Checked on:** 2026-11-03 (LangGraph 1.2.19)
