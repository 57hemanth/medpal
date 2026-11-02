# ADR-0005: Book with an advisory lock, a capacity check and client idempotency keys

- **Status:** accepted
- **Context:** Two patients can pick the same slot at the same moment. Mobile networks retry requests, so a double tap must not create two bookings. A slot may hold more than one patient (`capacity`), so a simple unique constraint on `slot_id` is wrong.
- **Options:**
  1. *A unique constraint on `appointment.slot_id`.* Simple, but it breaks the moment capacity > 1.
  2. *`SELECT … FOR UPDATE` on the slot row.* The textbook answer, but Postgres requires **UPDATE privilege** for row locks. The app role deliberately can't update `slot`; it must not be able to change capacity (ADR-0003).
  3. *A transaction-scoped advisory lock per slot* (`pg_advisory_xact_lock(hashtextextended('slot:<id>', 0))`), then count bookings against capacity, then insert. A client-generated `idempotency_key` (UNIQUE) makes retries return the existing booking.
- **Decision:** Option 3, in `services/scheduling/service.py::reserve`, inside one transaction that also writes the audit event. A full slot returns `None`, and the triage graph re-offers other slots, excluding the full one, up to three times before handing over to the front desk.
- **Revisit trigger:** contention on popular slots shows up in latency at peak (unlikely: peak load is well under 1 request per second), or bookings move to an external system of record.
- **Consequences:**
  - *Easier:* no extra privileges for the app; correct for any capacity; retry-safe.
  - *Harder:* advisory locks are invisible to people reading the schema, hence this ADR and a comment at the call site.
- **Proof:**
  - `test_concurrent_bookings_never_exceed_capacity` (20 parallel attempts on a capacity-1 slot → exactly 1 booking);
  - `test_same_key_twice_is_one_booking`;
  - `test_full_slot_is_excluded_and_reoffered`.
- **Checked on:** 2026-11-02
