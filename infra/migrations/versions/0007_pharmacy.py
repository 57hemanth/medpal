"""Pharmacy: reservations made at signing, dispensing, patient notifications, and kept transcripts.

* `medicine.therapeutic_class`: lets the doctor see alternatives in the same class when a medicine is out of
  stock (the doctor decides; nothing is substituted automatically).
* `app_user.clinic_id`: the clinic a pharmacist works at; they see reservations only there.
* `encounter.transcript`: the consultation transcript is kept with its signed note.
* `medicine_reservation`: one pack reserved per prescription line at the consultation's clinic, made by a
  trigger in the same transaction as the signature, released or dispensed by the clinic's pharmacist.
* `patient_notification`: fixed-template messages to a patient ("your medicines are ready"), never model text.
* `dispense_reservation()`: the only write path for dispensing. Stock counts get row-level security: only
  the feed sync (system role) and dispensing may change them.
* `medicine_available()`: count minus active reservations, as a number only, so a doctor sees correct
  availability without seeing other patients' reservations.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-03
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

APP_ROLE = "medpal_app"


def upgrade() -> None:
    op.execute(f"""
    ALTER TABLE medicine ADD COLUMN therapeutic_class text;
    ALTER TABLE app_user ADD COLUMN clinic_id uuid REFERENCES clinic;
    ALTER TABLE encounter ADD COLUMN transcript text;
    GRANT UPDATE (transcript) ON encounter TO {APP_ROLE};
    CREATE POLICY encounter_transcript ON encounter FOR UPDATE
        USING (app_role() = 'doctor' AND doctor_id IN (SELECT u.doctor_id FROM app_user u WHERE u.user_id = app_user_id()))
        WITH CHECK (app_role() = 'doctor' AND doctor_id IN (SELECT u.doctor_id FROM app_user u WHERE u.user_id = app_user_id()));

    CREATE FUNCTION app_user_clinic() RETURNS uuid
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
        SELECT clinic_id FROM app_user WHERE user_id = app_user_id()
    $$;
    REVOKE ALL ON FUNCTION app_user_clinic() FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION app_user_clinic() TO {APP_ROLE};

    CREATE TABLE medicine_reservation (
        reservation_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        rx_id          uuid NOT NULL UNIQUE REFERENCES prescription ON DELETE CASCADE,
        patient_id     uuid NOT NULL REFERENCES patient,
        clinic_id      uuid NOT NULL REFERENCES clinic,
        medicine_id    uuid NOT NULL REFERENCES medicine,
        doctor_id      uuid REFERENCES doctor,  -- who prescribed it, for the pharmacist handing it over
        status         text NOT NULL DEFAULT 'reserved' CHECK (status IN ('reserved', 'dispensed', 'released')),
        reserved_at    timestamptz NOT NULL DEFAULT now(),
        closed_at      timestamptz,
        closed_by      uuid REFERENCES app_user
    );
    CREATE INDEX reservation_active_idx ON medicine_reservation (clinic_id, medicine_id) WHERE status = 'reserved';
    ALTER TABLE medicine_reservation ENABLE ROW LEVEL SECURITY;
    ALTER TABLE medicine_reservation FORCE ROW LEVEL SECURITY;
    CREATE POLICY reservation_read ON medicine_reservation FOR SELECT USING (
        patient_id IN (SELECT app_allowed_patients())
        OR (app_role() = 'pharmacist' AND clinic_id = app_user_clinic())
        OR app_role() = 'compliance'
    );
    CREATE POLICY reservation_close ON medicine_reservation FOR UPDATE
        USING (app_role() = 'pharmacist' AND clinic_id = app_user_clinic())
        WITH CHECK (app_role() = 'pharmacist' AND clinic_id = app_user_clinic());
    GRANT SELECT ON medicine_reservation TO {APP_ROLE};
    GRANT UPDATE (status, closed_at, closed_by) ON medicine_reservation TO {APP_ROLE};

    -- Available packs: the count from the feed minus active reservations. A number only.
    CREATE FUNCTION medicine_available(p_clinic uuid, p_medicine uuid) RETURNS integer
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
        SELECT GREATEST(
            COALESCE((SELECT qty FROM medicine_stock WHERE clinic_id = p_clinic AND medicine_id = p_medicine), 0)
            - (SELECT count(*) FROM medicine_reservation
                WHERE clinic_id = p_clinic AND medicine_id = p_medicine AND status = 'reserved')::int,
            0)
    $$;
    CREATE FUNCTION medicine_reserved(p_clinic uuid, p_medicine uuid) RETURNS integer
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
        SELECT count(*)::int FROM medicine_reservation
         WHERE clinic_id = p_clinic AND medicine_id = p_medicine AND status = 'reserved'
    $$;
    -- Demand for restocking: prescription lines written at a clinic in a window, and how many of them
    -- could not be held (unmet). Counts only, no patient data.
    CREATE FUNCTION medicine_demand(p_clinic uuid, p_medicine uuid, p_days integer, p_unmet boolean)
    RETURNS integer LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
        SELECT count(*)::int
          FROM prescription rx
          JOIN note_version n ON n.note_id = rx.note_id AND n.version = rx.note_version
          JOIN encounter e ON e.encounter_id = n.encounter_id
          JOIN appointment a ON a.appt_id = e.appt_id
          JOIN slot s ON s.slot_id = a.slot_id
         WHERE s.clinic_id = p_clinic AND rx.medicine_id = p_medicine
           AND n.signed_at > now() - make_interval(days => p_days)
           AND (NOT p_unmet OR NOT EXISTS (SELECT 1 FROM medicine_reservation r WHERE r.rx_id = rx.rx_id))
    $$;
    REVOKE ALL ON FUNCTION medicine_demand(uuid, uuid, integer, boolean) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION medicine_demand(uuid, uuid, integer, boolean) TO {APP_ROLE};
    REVOKE ALL ON FUNCTION medicine_available(uuid, uuid) FROM PUBLIC;
    REVOKE ALL ON FUNCTION medicine_reserved(uuid, uuid) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION medicine_available(uuid, uuid) TO {APP_ROLE};
    GRANT EXECUTE ON FUNCTION medicine_reserved(uuid, uuid) TO {APP_ROLE};

    -- Reserve at signing: same transaction as the prescription, so a signed medicine is held or visibly not.
    CREATE FUNCTION reserve_on_prescription() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
    DECLARE v_clinic uuid; v_doctor uuid;
    BEGIN
        IF NEW.medicine_id IS NULL THEN
            RETURN NEW;  -- not in the formulary: nothing to hold
        END IF;
        SELECT s.clinic_id, n.doctor_id INTO v_clinic, v_doctor
          FROM note_version n
          JOIN encounter e ON e.encounter_id = n.encounter_id
          JOIN appointment a ON a.appt_id = e.appt_id
          JOIN slot s ON s.slot_id = a.slot_id
         WHERE n.note_id = NEW.note_id AND n.version = NEW.note_version;
        -- Serialise reservations of one medicine at one clinic, so two signatures can't take the last pack.
        PERFORM pg_advisory_xact_lock(hashtext(v_clinic::text || NEW.medicine_id::text));
        IF v_clinic IS NOT NULL AND medicine_available(v_clinic, NEW.medicine_id) > 0 THEN
            INSERT INTO medicine_reservation (rx_id, patient_id, clinic_id, medicine_id, doctor_id)
            VALUES (NEW.rx_id, NEW.patient_id, v_clinic, NEW.medicine_id, v_doctor);
        END IF;
        RETURN NEW;
    END $$;
    CREATE TRIGGER prescription_reserve AFTER INSERT ON prescription
        FOR EACH ROW EXECUTE FUNCTION reserve_on_prescription();

    -- A pharmacist sees the patients collecting at their clinic (name only through this policy).
    CREATE POLICY patient_read_pharmacy ON patient FOR SELECT USING (
        app_role() = 'pharmacist'
        AND patient_id IN (SELECT r.patient_id FROM medicine_reservation r WHERE r.clinic_id = app_user_clinic())
    );
    -- ...and the prescriptions being collected there, not every prescription in the network.
    DROP POLICY rx_read ON prescription;
    CREATE POLICY rx_read ON prescription FOR SELECT USING (
        patient_id IN (SELECT app_allowed_patients())
        OR app_role() = 'compliance'
        OR (app_role() = 'pharmacist'
            AND rx_id IN (SELECT r.rx_id FROM medicine_reservation r WHERE r.clinic_id = app_user_clinic()))
    );

    CREATE TABLE patient_notification (
        notification_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        patient_id      uuid NOT NULL REFERENCES patient,
        kind            text NOT NULL CHECK (kind IN ('medicines_ready')),
        body            text NOT NULL,
        created_at      timestamptz NOT NULL DEFAULT now(),
        read_at         timestamptz
    );
    ALTER TABLE patient_notification ENABLE ROW LEVEL SECURITY;
    ALTER TABLE patient_notification FORCE ROW LEVEL SECURITY;
    CREATE POLICY notification_read ON patient_notification FOR SELECT
        USING (patient_id IN (SELECT app_allowed_patients()));
    CREATE POLICY notification_mark_read ON patient_notification FOR UPDATE
        USING (patient_id IN (SELECT app_allowed_patients()))
        WITH CHECK (patient_id IN (SELECT app_allowed_patients()));
    GRANT SELECT ON patient_notification TO {APP_ROLE};  -- sent only by dispense_reservation()
    GRANT UPDATE (read_at) ON patient_notification TO {APP_ROLE};

    -- Stock counts are written by the feed sync only (the worker, as the system role) and by dispensing.
    -- 0002 granted the column update for the feed; without row-level security any request could use it.
    ALTER TABLE medicine_stock ENABLE ROW LEVEL SECURITY;
    CREATE POLICY stock_read ON medicine_stock FOR SELECT USING (true);
    CREATE POLICY stock_feed ON medicine_stock FOR UPDATE
        USING (app_role() = 'system') WITH CHECK (app_role() = 'system');

    -- Dispensing is one checked step: the clinic's pharmacist marks it dispensed, one pack comes off the
    -- local count (until the next feed reading replaces it), and the patient gets a fixed-template message.
    -- The app role gets no direct write on medicine_stock.
    CREATE FUNCTION dispense_reservation(p_reservation uuid, p_message text) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
    DECLARE r medicine_reservation%ROWTYPE;
    BEGIN
        IF app_role() <> 'pharmacist' THEN
            RETURN false;
        END IF;
        SELECT * INTO r FROM medicine_reservation
         WHERE reservation_id = p_reservation AND clinic_id = app_user_clinic() AND status = 'reserved'
         FOR UPDATE;
        IF NOT FOUND THEN
            RETURN false;
        END IF;
        UPDATE medicine_reservation
           SET status = 'dispensed', closed_at = now(), closed_by = app_user_id()
         WHERE reservation_id = p_reservation;
        UPDATE medicine_stock SET qty = GREATEST(qty - 1, 0)
         WHERE clinic_id = r.clinic_id AND medicine_id = r.medicine_id;
        INSERT INTO patient_notification (patient_id, kind, body) VALUES (r.patient_id, 'medicines_ready', p_message);
        RETURN true;
    END $$;
    REVOKE ALL ON FUNCTION dispense_reservation(uuid, text) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION dispense_reservation(uuid, text) TO {APP_ROLE};
    """)


def downgrade() -> None:
    op.execute("""
    DROP POLICY IF EXISTS stock_feed ON medicine_stock;
    DROP POLICY IF EXISTS stock_read ON medicine_stock;
    ALTER TABLE medicine_stock DISABLE ROW LEVEL SECURITY;
    DROP FUNCTION dispense_reservation(uuid, text);
    DROP TABLE patient_notification;
    DROP POLICY rx_read ON prescription;
    CREATE POLICY rx_read ON prescription FOR SELECT USING (
        patient_id IN (SELECT app_allowed_patients()) OR app_role() = ANY (ARRAY['pharmacist', 'compliance']));
    DROP POLICY patient_read_pharmacy ON patient;
    DROP TRIGGER prescription_reserve ON prescription;
    DROP FUNCTION reserve_on_prescription();
    DROP FUNCTION IF EXISTS medicine_demand(uuid, uuid, integer, boolean);
    DROP FUNCTION medicine_reserved(uuid, uuid);
    DROP FUNCTION medicine_available(uuid, uuid);
    DROP TABLE medicine_reservation;
    DROP FUNCTION app_user_clinic();
    DROP POLICY encounter_transcript ON encounter;
    ALTER TABLE encounter DROP COLUMN transcript;
    ALTER TABLE app_user DROP COLUMN clinic_id;
    ALTER TABLE medicine DROP COLUMN therapeutic_class;
    """)
