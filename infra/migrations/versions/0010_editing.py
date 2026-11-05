"""Changing things after the fact, each the way its kind of record allows.

* **Stock**: a pharmacist sets the count on hand, records a delivery or writes packs off, at their own clinic
  only, through `adjust_stock()`. Every change is a row in `stock_adjustment` (before, after, reason, who).
  The next feed reading still replaces the count: the feed stays the source of truth where there is one.
* **Medicines**: pharmacists add or correct catalogue entries (row-level security on `medicine`). Added
  entries are marked `source = 'clinic'`.
* **Patient records**: the patient (or the caregiver who uploaded it) renames, re-types or deletes an upload.
  Deleting removes its passages too (cascade), so it can no longer be searched or cited.
* **Prescriptions**: never edited. A doctor stops one with a reason (`stop_prescription()`): its pharmacy hold
  is released and the patient gets a fixed-wording message. Replacing is stopping plus a new prescription
  that names the one it replaces.
* **Signed notes**: never edited (0002's trigger). An amendment is a new version with a reason, signed by the
  same doctor; every version stays readable.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-04
"""

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

APP_ROLE = "medpal_app"


def upgrade() -> None:
    op.execute(f"""
    -- ---- stock -------------------------------------------------------------------------------------
    CREATE TABLE stock_adjustment (
        adjustment_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        clinic_id     uuid NOT NULL REFERENCES clinic,
        medicine_id   uuid NOT NULL REFERENCES medicine,
        kind          text NOT NULL CHECK (kind IN ('count', 'delivery', 'write_off')),
        qty_before    integer NOT NULL,
        qty_after     integer NOT NULL CHECK (qty_after >= 0),
        reason        text NOT NULL CHECK (length(reason) BETWEEN 1 AND 300),
        made_by       uuid NOT NULL REFERENCES app_user,
        made_at       timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX stock_adjustment_idx ON stock_adjustment (clinic_id, made_at DESC);
    ALTER TABLE stock_adjustment ENABLE ROW LEVEL SECURITY;
    ALTER TABLE stock_adjustment FORCE ROW LEVEL SECURITY;
    CREATE POLICY stock_adjustment_read ON stock_adjustment FOR SELECT USING (
        (app_role() = 'pharmacist' AND clinic_id = app_user_clinic()) OR app_role() = 'compliance');
    GRANT SELECT ON stock_adjustment TO {APP_ROLE};

    CREATE FUNCTION adjust_stock(p_medicine uuid, p_kind text, p_qty integer, p_reason text)
    RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
    DECLARE v_clinic uuid := app_user_clinic(); v_before integer; v_after integer;
    BEGIN
        IF app_role() IS DISTINCT FROM 'pharmacist' OR v_clinic IS NULL THEN
            RAISE EXCEPTION 'only a clinic pharmacist adjusts stock' USING ERRCODE = '42501';
        END IF;
        IF p_qty IS NULL OR p_qty < 0 OR p_qty > 100000 THEN
            RAISE EXCEPTION 'quantity out of range' USING ERRCODE = '22023';
        END IF;
        IF p_reason IS NULL OR length(trim(p_reason)) = 0 THEN
            RAISE EXCEPTION 'a reason is required' USING ERRCODE = '22023';
        END IF;
        PERFORM 1 FROM medicine WHERE medicine_id = p_medicine;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'unknown medicine' USING ERRCODE = '22023';
        END IF;
        -- Same lock as reservations at signing, so a count can't interleave with taking the last pack.
        PERFORM pg_advisory_xact_lock(hashtext(v_clinic::text || p_medicine::text));
        SELECT qty INTO v_before FROM medicine_stock
         WHERE clinic_id = v_clinic AND medicine_id = p_medicine FOR UPDATE;
        v_before := COALESCE(v_before, 0);
        v_after := CASE p_kind
            WHEN 'count' THEN p_qty
            WHEN 'delivery' THEN v_before + p_qty
            WHEN 'write_off' THEN v_before - p_qty
        END;
        IF v_after IS NULL THEN
            RAISE EXCEPTION 'unknown adjustment' USING ERRCODE = '22023';
        END IF;
        IF v_after < 0 THEN
            RAISE EXCEPTION 'cannot write off more than is on hand' USING ERRCODE = '22023';
        END IF;
        INSERT INTO medicine_stock (clinic_id, medicine_id, qty, as_of)
        VALUES (v_clinic, p_medicine, v_after, now())
        ON CONFLICT (clinic_id, medicine_id) DO UPDATE SET qty = EXCLUDED.qty, as_of = EXCLUDED.as_of;
        INSERT INTO stock_adjustment (clinic_id, medicine_id, kind, qty_before, qty_after, reason, made_by)
        VALUES (v_clinic, p_medicine, p_kind, v_before, v_after, left(trim(p_reason), 300), app_user_id());
        RETURN v_after;
    END $$;
    REVOKE ALL ON FUNCTION adjust_stock(uuid, text, integer, text) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION adjust_stock(uuid, text, integer, text) TO {APP_ROLE};

    -- ---- medicines catalogue -----------------------------------------------------------------------
    ALTER TABLE medicine ENABLE ROW LEVEL SECURITY;  -- not FORCE: the data loaders run as the owner
    CREATE POLICY medicine_read ON medicine FOR SELECT USING (true);
    CREATE POLICY medicine_add ON medicine FOR INSERT
        WITH CHECK (app_role() = 'pharmacist' AND source = 'clinic');
    CREATE POLICY medicine_edit ON medicine FOR UPDATE
        USING (app_role() = 'pharmacist') WITH CHECK (app_role() = 'pharmacist');
    GRANT INSERT (name, composition, manufacturer, pack_size, price_inr, therapeutic_class, source)
        ON medicine TO {APP_ROLE};
    GRANT UPDATE (name, composition, manufacturer, pack_size, price_inr, therapeutic_class)
        ON medicine TO {APP_ROLE};

    -- ---- patient records ---------------------------------------------------------------------------
    ALTER TABLE document ADD COLUMN title text CHECK (length(title) <= 120);
    CREATE POLICY document_owner_edit ON document FOR UPDATE
        USING (app_role() IN ('patient', 'caregiver') AND patient_id IN (SELECT app_allowed_patients())
               AND (app_role() = 'patient' OR uploaded_by = app_user_id()))
        WITH CHECK (app_role() IN ('patient', 'caregiver') AND patient_id IN (SELECT app_allowed_patients()));
    CREATE POLICY document_owner_delete ON document FOR DELETE
        USING (app_role() IN ('patient', 'caregiver') AND patient_id IN (SELECT app_allowed_patients())
               AND (app_role() = 'patient' OR uploaded_by = app_user_id()));
    GRANT UPDATE (title, type) ON document TO {APP_ROLE};
    GRANT DELETE ON document TO {APP_ROLE};

    -- ---- prescriptions -----------------------------------------------------------------------------
    ALTER TABLE prescription
        ADD COLUMN status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'stopped')),
        ADD COLUMN stopped_at timestamptz,
        ADD COLUMN stopped_by uuid REFERENCES app_user,
        ADD COLUMN stop_reason text CHECK (length(stop_reason) <= 300),
        ADD COLUMN replaces_rx_id uuid REFERENCES prescription,
        ADD COLUMN created_at timestamptz NOT NULL DEFAULT now();
    ALTER TABLE patient_notification DROP CONSTRAINT patient_notification_kind_check;
    ALTER TABLE patient_notification ADD CONSTRAINT patient_notification_kind_check
        CHECK (kind IN ('medicines_ready', 'prescription_changed'));

    -- The prescribing doctor stops it; the hold is released and the patient told, in one transaction.
    CREATE FUNCTION stop_prescription(p_rx uuid, p_reason text, p_message text) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
    DECLARE v prescription%ROWTYPE;
    BEGIN
        IF app_role() IS DISTINCT FROM 'doctor' OR p_reason IS NULL OR length(trim(p_reason)) = 0 THEN
            RETURN false;
        END IF;
        SELECT * INTO v FROM prescription
         WHERE rx_id = p_rx AND status = 'active'
           AND note_id IN (SELECT n.note_id FROM note_version n
                            JOIN app_user u ON u.doctor_id = n.doctor_id AND u.user_id = app_user_id())
         FOR UPDATE;
        IF NOT FOUND THEN
            RETURN false;
        END IF;
        UPDATE prescription
           SET status = 'stopped', stopped_at = now(), stopped_by = app_user_id(),
               stop_reason = left(trim(p_reason), 300)
         WHERE rx_id = p_rx;
        UPDATE medicine_reservation SET status = 'released', closed_at = now(), closed_by = app_user_id()
         WHERE rx_id = p_rx AND status = 'reserved';
        INSERT INTO patient_notification (patient_id, kind, body)
        VALUES (v.patient_id, 'prescription_changed', p_message);
        RETURN true;
    END $$;
    REVOKE ALL ON FUNCTION stop_prescription(uuid, text, text) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION stop_prescription(uuid, text, text) TO {APP_ROLE};
    """)


def downgrade() -> None:
    op.execute(f"""
    DROP FUNCTION IF EXISTS stop_prescription(uuid, text, text);
    DELETE FROM patient_notification WHERE kind = 'prescription_changed';
    ALTER TABLE patient_notification DROP CONSTRAINT patient_notification_kind_check;
    ALTER TABLE patient_notification ADD CONSTRAINT patient_notification_kind_check
        CHECK (kind IN ('medicines_ready'));
    ALTER TABLE prescription DROP COLUMN IF EXISTS created_at, DROP COLUMN IF EXISTS replaces_rx_id,
        DROP COLUMN IF EXISTS stop_reason, DROP COLUMN IF EXISTS stopped_by, DROP COLUMN IF EXISTS stopped_at,
        DROP COLUMN IF EXISTS status;
    REVOKE DELETE ON document FROM {APP_ROLE};
    REVOKE UPDATE (title, type) ON document FROM {APP_ROLE};
    DROP POLICY IF EXISTS document_owner_delete ON document;
    DROP POLICY IF EXISTS document_owner_edit ON document;
    ALTER TABLE document DROP COLUMN IF EXISTS title;
    REVOKE INSERT (name, composition, manufacturer, pack_size, price_inr, therapeutic_class, source)
        ON medicine FROM {APP_ROLE};
    REVOKE UPDATE (name, composition, manufacturer, pack_size, price_inr, therapeutic_class)
        ON medicine FROM {APP_ROLE};
    DROP POLICY IF EXISTS medicine_edit ON medicine;
    DROP POLICY IF EXISTS medicine_add ON medicine;
    DROP POLICY IF EXISTS medicine_read ON medicine;
    ALTER TABLE medicine DISABLE ROW LEVEL SECURITY;
    DROP FUNCTION IF EXISTS adjust_stock(uuid, text, integer, text);
    DROP TABLE IF EXISTS stock_adjustment;
    """)
