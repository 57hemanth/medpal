# ADR-0014: Mobile number and one-time code as the sign-in for everyone

- **Status:** accepted (complements the OIDC option in [ADR-0003](0003-row-level-security.md); OIDC stays available)
- **Context:** The web app used a profile switcher instead of sign-in, so nothing identified the person using it. Sharing had nowhere to point: a patient couldn't say "give my son access", because the son had no identity until someone created one in the database. In Indian outpatient care the mobile number is the identifier people already give at every clinic, and many patients have no email.
- **Options:**
  1. *OIDC only.* Standard and strong, but every family member needs an account with an identity provider before a patient can share with them.
  2. *Email magic links.* Same gap: many patients and caregivers don't use email.
  3. **Mobile number + one-time code for patients, families and staff, with OIDC still available (`MEDPAL_AUTH_MODE=oidc`).**
- **Decision:** Option 3 (`services/platform/signin.py`, `services/api/routers/auth.py`, migration `0008_mobile_sign_in`):
  - A 6-digit code, stored only as an HMAC; valid for 5 minutes, used once, 5 wrong tries per code and 5 codes per number per hour.
  - A new number registers a patient record (name, optional date of birth and city) through a signed, short-lived registration token, so it can't be replayed for another number.
  - The session is an HMAC-signed HttpOnly, SameSite=Lax cookie (Secure in production), 12 hours. The browser code never sees it.
  - One person can hold several roles (Asha is a patient and her mother's caregiver). The roles come from the database at sign-in; switching re-issues the cookie only for a role the person actually has.
  - **Sharing by number:** a patient shares with a mobile number. If nobody has it yet, `invite_phone()` creates a caregiver account for it, and the consent exists before they ever sign in. Only a patient can share their own record; the consent keeps purpose, scope and expiry as before.
  - Codes are readable only in the system context: the app role can't list them.
  - Development returns the code in the response (no SMS gateway). Production refuses to start in `otp` mode with the log-only SMS sender or the default secret.
- **Consequences:**
  - *Easier:* anyone can be identified the way clinics already identify them; sharing works for people who have never used MedPal.
  - *Harder:* SMS delivery is a vendor dependency and a cost; a SIM swap is an account takeover, so staff accounts should move to OIDC with MFA before real deployment.
- **Revisit trigger:** an SMS provider is chosen; staff sign-in needs MFA; a number changes hands (recycled numbers).
- **Proof:** `tests/unit/test_signin.py` (numbers, signed tokens, identity order, production guards), `tests/integration/test_signin_db.py` (attempt cap, single use, rate limit, codes invisible to the app role, share-by-number and caregiver sign-in end to end), `web/src/app/App.test.tsx`, `web/src/features/consent/ConsentPage.test.tsx`.
- **Checked on:** 2026-11-03
