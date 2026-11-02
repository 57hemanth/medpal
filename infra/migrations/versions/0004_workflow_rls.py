"""RLS for workflows exposed after triage.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-02
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

APP_ROLE = "medpal_app"


def upgrade() -> None:
    op.execute("""
    -- Appointment access uses appointment-specific consent scopes. Records access alone is not enough.
    CREATE FUNCTION app_allowed_appointment_patients(scope_name text) RETURNS SETOF uuid
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
        SELECT u.patient_id FROM app_user u
         WHERE u.user_id = app_user_id() AND app_role() = 'patient' AND u.patient_id IS NOT NULL
        UNION
        SELECT c.patient_id FROM consent c
         WHERE c.grantee_user_id = app_user_id() AND app_role() = 'caregiver'
           AND scope_name = ANY (c.scope) AND c.revoked_at IS NULL AND c.expires_at > now()
        UNION
        SELECT a.patient_id FROM appointment a
          JOIN slot s ON s.slot_id = a.slot_id
          JOIN app_user u ON u.doctor_id = s.doctor_id
         WHERE u.user_id = app_user_id() AND app_role() = 'doctor' AND a.status IN ('booked','attended')
        UNION
        SELECT p.patient_id FROM patient p WHERE app_role() = 'system'
    $$;
    REVOKE ALL ON FUNCTION app_allowed_appointment_patients(text) FROM PUBLIC;

    ALTER TABLE appointment ENABLE ROW LEVEL SECURITY;
    ALTER TABLE handoff_ticket ENABLE ROW LEVEL SECURITY;
    ALTER TABLE encounter ENABLE ROW LEVEL SECURITY;
    ALTER TABLE audit_event ENABLE ROW LEVEL SECURITY;

    CREATE POLICY appointment_read ON appointment FOR SELECT USING (
        patient_id IN (SELECT app_allowed_appointment_patients('appointments:read'))
        OR app_role() IN ('desk','compliance'));
    CREATE POLICY appointment_insert ON appointment FOR INSERT WITH CHECK (
        created_by = app_user_id() AND (
            patient_id IN (SELECT app_allowed_appointment_patients('appointments:write'))
            OR app_role() = 'desk'));
    CREATE POLICY appointment_status_update ON appointment FOR UPDATE USING (
        app_role() = 'desk'
        OR patient_id IN (SELECT app_allowed_appointment_patients('appointments:write')))
        WITH CHECK (
            app_role() = 'desk'
            OR patient_id IN (SELECT app_allowed_appointment_patients('appointments:write')));

    CREATE POLICY handoff_read ON handoff_ticket FOR SELECT USING (
        app_role() IN ('desk','compliance')
        OR created_by = app_user_id()
        OR patient_id IN (SELECT app_allowed_appointment_patients('appointments:read')));
    CREATE POLICY handoff_create ON handoff_ticket FOR INSERT WITH CHECK (
        created_by = app_user_id()
        AND (patient_id IS NULL
             OR patient_id IN (SELECT app_allowed_appointment_patients('appointments:write'))));
    CREATE POLICY handoff_update ON handoff_ticket FOR UPDATE USING (app_role() IN ('desk','compliance'))
        WITH CHECK (app_role() IN ('desk','compliance'));

    CREATE POLICY encounter_read ON encounter FOR SELECT USING (
        patient_id IN (SELECT app_allowed_patients())
        OR doctor_id IN (SELECT u.doctor_id FROM app_user u WHERE u.user_id = app_user_id() AND app_role() = 'doctor')
        OR app_role() = 'compliance');
    CREATE POLICY encounter_create ON encounter FOR INSERT WITH CHECK (
        app_role() = 'doctor'
        AND doctor_id IN (SELECT u.doctor_id FROM app_user u WHERE u.user_id = app_user_id()));

    CREATE POLICY audit_read ON audit_event FOR SELECT USING (
        app_role() = 'compliance'
        OR patient_id IN (SELECT app_allowed_appointment_patients('appointments:read')));
    CREATE POLICY audit_append ON audit_event FOR INSERT WITH CHECK (
        actor_id = app_user_id() AND actor_role = app_role());

    GRANT EXECUTE ON FUNCTION app_allowed_appointment_patients(text) TO medpal_app;
    """)


def downgrade() -> None:
    op.execute(f"""
    REVOKE EXECUTE ON FUNCTION app_allowed_appointment_patients(text) FROM {APP_ROLE};
    DROP POLICY IF EXISTS audit_append ON audit_event;
    DROP POLICY IF EXISTS audit_read ON audit_event;
    DROP POLICY IF EXISTS encounter_create ON encounter;
    DROP POLICY IF EXISTS encounter_read ON encounter;
    DROP POLICY IF EXISTS handoff_update ON handoff_ticket;
    DROP POLICY IF EXISTS handoff_create ON handoff_ticket;
    DROP POLICY IF EXISTS handoff_read ON handoff_ticket;
    DROP POLICY IF EXISTS appointment_status_update ON appointment;
    DROP POLICY IF EXISTS appointment_insert ON appointment;
    DROP POLICY IF EXISTS appointment_read ON appointment;
    ALTER TABLE audit_event DISABLE ROW LEVEL SECURITY;
    ALTER TABLE encounter DISABLE ROW LEVEL SECURITY;
    ALTER TABLE handoff_ticket DISABLE ROW LEVEL SECURITY;
    ALTER TABLE appointment DISABLE ROW LEVEL SECURITY;
    DROP FUNCTION IF EXISTS app_allowed_appointment_patients(text);
    """)
