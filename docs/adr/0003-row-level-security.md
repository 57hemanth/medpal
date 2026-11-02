# ADR-0003: Enforce patient-data isolation with Postgres row-level security

- **Status:** accepted
- **Context:** A patient must only ever see their own records, plus records a family member has explicitly shared with them through consent that hasn't expired or been revoked. A doctor should see only the patients they treat. The front desk sees demographics but no clinical content. A single forgotten `WHERE patient_id = …` in application code, or a prompt-injected request, must not be enough to leak data.
- **Options:**
  1. *Filter in application code.* Simple, but every query has to remember, and one miss is a breach. Untestable as a guarantee.
  2. *Ask the LLM to stay in scope (prompt instructions).* Not a control at all: a prompt can be argued with.
  3. *Postgres row-level security (RLS),* with policies built on one function, `app_allowed_patients()`, and the caller's identity set on each transaction.
- **Decision:** Option 3, with four parts:
  - **One definition of scope:** `app_allowed_patients()` (`SECURITY DEFINER`) returns the patients the caller may read. Patient: self. Caregiver: patients who granted unexpired, unrevoked `records:read` consent. Doctor: patients with an appointment with them. System worker: all. Every clinical policy calls this one function.
  - **Identity per transaction:** `services.platform.db.scoped(pool, auth)` sets `app.user_id` and `app.role` with `set_config(..., true)` (local to the transaction), so a pooled connection never carries one caller's identity into the next request. No identity set means no rows.
  - **A non-superuser app role:** the API connects as `medpal_app` (NOSUPERUSER, NOBYPASSRLS). **Superusers bypass RLS entirely, even with `FORCE`**, so connecting as the container's default superuser would have made every policy decorative. Migrations and seeding use the owner role.
  - **Verbs and columns limited by grants:** a patient may set `consent.revoked_at` but cannot extend `expires_at`. The app cannot update `slot`. Signed notes and audit rows cannot be updated or deleted, even by the owner (triggers).
- **Revisit trigger:** policy cost shows up in query plans at scale (then denormalise or cache the allowed set per request), or a role needs a scope the function can't express.
- **Consequences:**
  - *Easier:* the guarantee holds whatever the application code does, and it can be tested directly.
  - *Harder:*
    - Two database roles to provision.
    - Every data path must go through `scoped()`; workers use `scoped_system()`.
    - Debugging needs care: a "missing row" may be RLS working as intended.
    - `SELECT … FOR UPDATE` needs UPDATE rights, which is why booking uses an advisory lock (ADR-0005).
- **Proof:** `tests/integration/test_rls.py` runs queries that **omit the application filter** or ask for another patient's id outright, for every role. On a test database, the same patient's query sees **1 patient with RLS on and 28 with it off**. `test_app_role_cannot_bypass_rls` fails if the app ever connects with bypass rights.
- **Checked on:** 2026-11-02
