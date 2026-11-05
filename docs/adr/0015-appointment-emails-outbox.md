# ADR-0015: Appointment emails through an outbox written by the database

- **Status:** accepted
- **Context:** Patients need a confirmation when they book, reminders before the visit, and a notice when a visit is cancelled. Bookings happen in several places (the assistant, the front desk, the tool server), and a reminder must never go out for a visit that has been cancelled. Email is the first channel; SMS will follow through the same path.
- **Options:**
  1. *Send from each booking path.* Every caller has to remember; a missed one means silent gaps, and sending inside a request ties the patient's wait to a mail server.
  2. *A scheduled job that scans appointments for "due" reminders.* Simple, but which messages went, and why one didn't, is never recorded.
  3. **A trigger on `appointment` writes outbox rows (confirmation now, reminders 24 h and 2 h before, a cancellation notice); a dispatcher sends due rows and records each outcome.**
- **Decision:** Option 3 (migration `0009_email_notifications`, `services/notifications/`):
  - The trigger covers every booking path. Cancelling withdraws reminders not yet sent. The dispatcher also re-reads the appointment just before sending, so a cancellation that lands late still stops a reminder.
  - Rows are claimed with `FOR UPDATE SKIP LOCKED`: any number of API processes or workers can send without duplicates. Mail is sent outside the claiming transaction. A row left in `sending` by a crash is reclaimed after 10 minutes, so delivery is at least once.
  - Failures retry with backoff (2, 4, 8, 16 minutes), then are recorded as failed with the error.
  - **Only a confirmed address is emailed.** Confirming is a signed link valid for 24 hours, tied to that address. A trigger clears the confirmation whenever the address changes, and only the system context can set it, so a typo never sends appointment details to a stranger.
  - **Fixed wording, nothing clinical:** first name, doctor, clinic, time, and a link to manage the appointment. No symptoms or results, and no specialty (it can reveal a condition). The wording is rendered at send time; the outbox stores only what to send, then the masked recipient and subject once sent.
  - The patient can turn appointment emails off. Front desk and compliance see every message and why any didn't go; patients see their own.
  - Senders: `log` (development, records the subject only), `smtp` (Mailpit locally, any provider in production). Production refuses to start with `log` while sending is on.
  - Who sends: the API in-process (`MEDPAL_NOTIFY_DISPATCH=inline`, the default) or the arq worker (`worker`).
- **Consequences:**
  - *Easier:* every booking path gets emails without changes; each message has an auditable outcome; SMS is a new channel value and sender, not a new design.
  - *Harder:* appointment details (name, doctor, clinic, time) leave the boundary through the email provider. The provider needs a data processing agreement, Indian data residency where possible (for example Amazon SES in ap-south-1), and a place on the egress allowlist.
- **Revisit trigger:** SMS reminders (DLT-registered templates); a patient's preferred language; reschedule as a single message rather than cancel and book.
- **Proof:** `tests/integration/test_notifications_db.py` (what is queued, what is sent, late cancellation, unconfirmed and opted-out addresses, self-confirmation refused, old links, retries, two dispatchers at once, row-level access), `tests/unit/test_email_templates.py` (wording, clinic time, HTML escaping, production guard), `web/src/features/messages/SettingsPage.test.tsx`. Verified live on 2026-11-04: a booking and its cancellation produced both emails in Mailpit and withdrew both reminders.
- **Checked on:** 2026-11-04
