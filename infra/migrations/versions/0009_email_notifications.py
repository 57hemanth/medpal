"""Appointment emails: confirmation, cancellation and reminders, through an outbox.

* `patient.email`, `email_verified_at`, `email_notifications`: a patient adds an address and confirms it
  by a link; only a confirmed address is ever sent appointment details. Changing the address clears the
  confirmation (a trigger, so no code path can forget). Only the system context may confirm.
* `notification_outbox`: one row per message to send. Rows are written by a trigger on `appointment`, so
  every booking path (assistant, front desk, tools) is covered: a confirmation now, reminders 24 h and
  2 h before. Cancelling withdraws reminders not yet sent and queues a cancellation notice. The worker
  claims due rows with SKIP LOCKED, sends, and records the outcome. Rows hold no message text before
  sending, only what to send; the wording is rendered from current data at send time.
* Rows are readable by the patient (and caregivers with appointment access), the front desk and
  compliance; only the system context writes them.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-03
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

APP_ROLE = "medpal_app"


def upgrade() -> None:
    op.execute(f"""
    ALTER TABLE patient ADD COLUMN email text CHECK (email ~* '^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$' AND length(email) <= 254);
    ALTER TABLE patient ADD COLUMN email_verified_at timestamptz;
    ALTER TABLE patient ADD COLUMN email_notifications boolean NOT NULL DEFAULT true;

    -- A patient edits their own contact settings; only the system context confirms an address.
    CREATE POLICY patient_contact_update ON patient FOR UPDATE
        USING ((app_role() = 'patient' AND patient_id IN (SELECT app_allowed_patients())) OR app_role() = 'system')
        WITH CHECK ((app_role() = 'patient' AND patient_id IN (SELECT app_allowed_patients())) OR app_role() = 'system');
    GRANT UPDATE (email, email_verified_at, email_notifications) ON patient TO {APP_ROLE};

    CREATE FUNCTION guard_email_verification() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.email IS DISTINCT FROM OLD.email THEN
            NEW.email_verified_at := NULL;  -- a new address is unconfirmed, whoever changed it
        ELSIF app_role() IS DISTINCT FROM 'system' THEN
            NEW.email_verified_at := OLD.email_verified_at;  -- only the confirmation link may set it
        END IF;
        RETURN NEW;
    END $$;
    CREATE TRIGGER patient_email_verification BEFORE UPDATE OF email, email_verified_at ON patient
        FOR EACH ROW EXECUTE FUNCTION guard_email_verification();

    CREATE TABLE notification_outbox (
        notification_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        patient_id      uuid NOT NULL REFERENCES patient,
        appt_id         uuid REFERENCES appointment,
        channel         text NOT NULL DEFAULT 'email' CHECK (channel IN ('email')),
        kind            text NOT NULL CHECK (kind IN ('appointment_booked','appointment_cancelled',
                                                      'appointment_reminder_24h','appointment_reminder_2h')),
        send_after      timestamptz NOT NULL,
        status          text NOT NULL DEFAULT 'queued'
                        CHECK (status IN ('queued','sending','sent','failed','cancelled','skipped')),
        attempts        integer NOT NULL DEFAULT 0,
        claimed_at      timestamptz,
        sent_at         timestamptz,
        recipient       text,          -- masked address, filled when sent
        subject         text,          -- filled when sent
        detail          text,          -- why skipped or failed; never message content
        created_at      timestamptz NOT NULL DEFAULT now(),
        UNIQUE (appt_id, kind)
    );
    CREATE INDEX outbox_due_idx ON notification_outbox (send_after) WHERE status IN ('queued','sending');
    CREATE INDEX outbox_patient_idx ON notification_outbox (patient_id, created_at DESC);
    ALTER TABLE notification_outbox ENABLE ROW LEVEL SECURITY;
    ALTER TABLE notification_outbox FORCE ROW LEVEL SECURITY;
    CREATE POLICY outbox_read ON notification_outbox FOR SELECT USING (
        app_role() IN ('desk','compliance','system')
        OR patient_id IN (SELECT app_allowed_appointment_patients('appointments:read')));
    CREATE POLICY outbox_system ON notification_outbox FOR ALL
        USING (app_role() = 'system') WITH CHECK (app_role() = 'system');
    GRANT SELECT, INSERT, UPDATE ON notification_outbox TO {APP_ROLE};

    -- Every booking path writes `appointment`, so the messages follow from the table, not from callers.
    CREATE FUNCTION enqueue_appointment_notifications() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
    DECLARE v_starts timestamptz;
    BEGIN
        SELECT s.starts_at INTO v_starts FROM slot s WHERE s.slot_id = NEW.slot_id;
        IF v_starts IS NULL OR v_starts <= now() THEN
            RETURN NEW;
        END IF;
        IF TG_OP = 'INSERT' AND NEW.status = 'booked' THEN
            INSERT INTO notification_outbox (patient_id, appt_id, kind, send_after)
            SELECT NEW.patient_id, NEW.appt_id, k.kind, k.at
              FROM (VALUES ('appointment_booked', now()),
                           ('appointment_reminder_24h', v_starts - interval '24 hours'),
                           ('appointment_reminder_2h', v_starts - interval '2 hours')) AS k(kind, at)
             WHERE k.kind = 'appointment_booked' OR k.at > now()
            ON CONFLICT (appt_id, kind) DO NOTHING;
        ELSIF TG_OP = 'UPDATE' AND OLD.status = 'booked' AND NEW.status <> 'booked' THEN
            UPDATE notification_outbox SET status = 'cancelled', detail = 'appointment ' || NEW.status
             WHERE appt_id = NEW.appt_id AND status = 'queued';
            IF NEW.status = 'cancelled' THEN
                INSERT INTO notification_outbox (patient_id, appt_id, kind, send_after)
                VALUES (NEW.patient_id, NEW.appt_id, 'appointment_cancelled', now())
                ON CONFLICT (appt_id, kind) DO NOTHING;
            END IF;
        END IF;
        RETURN NEW;
    END $$;
    REVOKE ALL ON FUNCTION enqueue_appointment_notifications() FROM PUBLIC;
    CREATE TRIGGER appointment_notifications AFTER INSERT OR UPDATE OF status ON appointment
        FOR EACH ROW EXECUTE FUNCTION enqueue_appointment_notifications();
    """)


def downgrade() -> None:
    op.execute(f"""
    DROP TRIGGER IF EXISTS appointment_notifications ON appointment;
    DROP FUNCTION IF EXISTS enqueue_appointment_notifications();
    DROP TABLE IF EXISTS notification_outbox;
    DROP TRIGGER IF EXISTS patient_email_verification ON patient;
    DROP FUNCTION IF EXISTS guard_email_verification();
    REVOKE UPDATE (email, email_verified_at, email_notifications) ON patient FROM {APP_ROLE};
    DROP POLICY IF EXISTS patient_contact_update ON patient;
    ALTER TABLE patient DROP COLUMN IF EXISTS email_notifications;
    ALTER TABLE patient DROP COLUMN IF EXISTS email_verified_at;
    ALTER TABLE patient DROP COLUMN IF EXISTS email;
    """)
