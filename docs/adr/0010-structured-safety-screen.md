# ADR-0010: A structured safety screen, not free-text rules, is the emergency gate

- **Status:** accepted
- **Context:** Missing an emergency is the worst failure this system can have. The first rule set matched exact phrases. An evaluation set of realistic phrasings measured its recall at **35%**. After two rounds of pattern work, recall on the tuned set reached 100%, but on a **fresh held-out set it was 16–20%**. Free-text rules don't generalise to how people describe emergencies ("can't get enough air", "he won't wake up", "vomit looks like coffee grounds").
- **Options:**
  1. *Keep improving patterns.* Each round overfits what it has seen. Recall on unseen text stays low.
  2. *A model classifier only.* Better generalisation, but not provable, and unavailable when the provider is down.
  3. **A structured screen plus rules:** free-text rules as a fast path; then every routine triage asks seven explicit yes/no red-flag questions (chest pain, breathing, unconscious or fits, stroke signs, heavy bleeding, poisoning, self-harm). Any "yes" goes to the emergency path. A model second pass that may only *add* flags can be layered on later.
- **Decision:** Option 3 (`SAFETY_SCREEN` in `services/agent/triage/rules.py`; the `safety_screen` node in the triage graph; the `SafetyCheck` component in the web app):
  - Every question must be answered explicitly. There's no "no to all" shortcut, and malformed or incomplete answers are asked again.
  - The held-out set is scored on every evaluation run as a **generalisation figure**, never tuned against and never a gate.
- **Revisit trigger:** clinical review of the question wording; a model second pass with measured recall on the held-out set.
- **Consequences:**
  - *Easier:* recall no longer depends on phrasing; it works with the model down.
  - *Harder:* one extra step for every patient; question wording needs clinical sign-off; it relies on the patient's answers.
- **Proof:** `make eval` gives recall 100% / over-triage 2% on the tuned set and reports held-out recall. `tests/unit/test_triage_graph.py` covers any yes → emergency, incomplete answers asked again, and an emergency stated during clarification still escalating.
- **Checked on:** 2026-11-03
