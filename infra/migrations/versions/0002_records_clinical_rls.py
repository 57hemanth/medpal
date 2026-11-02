"""Records, clinical and pharmacy tables; app-role grants; row-level security.

Completes the corrected data model and enforces the access matrix in
the database, so a forgotten WHERE clause in application code cannot leak another patient's data.

Δ versus the original design's entity model:
  Δ doc_chunk.patient_id denormalised (scope filter + RLS without a join)
  Δ consent carries purpose, granted_by, revoked_at (DPDP revocation)
  Δ note_version holds only SIGNED notes, immutable (trigger); drafts live in graph state
  Δ medicine (formulary) separated from medicine_stock (per clinic, with as_of)
  Δ specialty_crosswalk with reviewer mark
  Δ ingest_job for upload status

Security model:
  * The app connects as `medpal_app` (NOSUPERUSER, NOBYPASSRLS), created by infra/postgres/init in dev
    and by ops elsewhere. Superusers bypass RLS, so the owner role is for migrations only.
  * Each transaction sets app.user_id / app.role (services.platform.db.scoped). Unset → no rows.
  * app_allowed_patients() is the single definition of "whose clinical data may this caller see".

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-02
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

APP_ROLE = "medpal_app"


def upgrade() -> None:
    op.execute(f"""
    DO $$ BEGIN
      IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
        RAISE EXCEPTION 'role {APP_ROLE} is missing: create it first (dev: infra/postgres/init/01-app-role.sql)';
      END IF;
    END $$;
    """)

    # ---------------------------------------------------------------- tables
    op.execute("""
    CREATE TABLE consent (
        consent_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        patient_id      uuid NOT NULL REFERENCES patient,
        grantee_user_id uuid NOT NULL REFERENCES app_user,
        scope           text[] NOT NULL CHECK (scope <@ ARRAY['records:read','appointments:read','appointments:write']),
        purpose         text NOT NULL,
        granted_by      uuid NOT NULL REFERENCES app_user,
        granted_at      timestamptz NOT NULL DEFAULT now(),
        expires_at      timestamptz NOT NULL,
        revoked_at      timestamptz,
        CHECK (expires_at > granted_at)
    );
    CREATE INDEX consent_grantee_idx ON consent (grantee_user_id) WHERE revoked_at IS NULL;

    CREATE TABLE document (
        doc_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        patient_id  uuid NOT NULL REFERENCES patient,
        type        text NOT NULL CHECK (type IN ('lab_report','radiology','prescription','discharge','other')),
        uri         text NOT NULL,
        sha256      text NOT NULL,
        uploaded_by uuid NOT NULL REFERENCES app_user,
        uploaded_at timestamptz NOT NULL DEFAULT now(),
        phi_status  text NOT NULL DEFAULT 'pending' CHECK (phi_status IN ('pending','tagged','blocked')),
        synthetic   boolean NOT NULL DEFAULT true,
        UNIQUE (patient_id, sha256)
    );

    CREATE TABLE ingest_job (
        job_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        doc_id     uuid NOT NULL REFERENCES document ON DELETE CASCADE,
        status     text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','ready','failed','needs_review')),
        error      text,                       -- reason code only, never document text
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now()
    );

    CREATE TABLE doc_chunk (
        chunk_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        doc_id     uuid NOT NULL REFERENCES document ON DELETE CASCADE,
        patient_id uuid NOT NULL REFERENCES patient,
        page       int  NOT NULL CHECK (page >= 1),
        ordinal    int  NOT NULL CHECK (ordinal >= 0),
        section    text,
        text       text NOT NULL,
        tsv        tsvector GENERATED ALWAYS AS (to_tsvector('simple', text)) STORED,
        embedding  vector(1024),               -- filled by the in-boundary embedding model (T5.2)
        UNIQUE (doc_id, page, ordinal)
    );
    CREATE INDEX doc_chunk_patient_idx ON doc_chunk (patient_id);
    CREATE INDEX doc_chunk_tsv_idx ON doc_chunk USING gin (tsv);
    -- No ANN index: records retrieval is always scoped to one patient; exact scan is exact and fast (ADR-06).

    CREATE TABLE encounter (
        encounter_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        appt_id        uuid NOT NULL UNIQUE REFERENCES appointment,
        patient_id     uuid NOT NULL REFERENCES patient,
        doctor_id      uuid NOT NULL REFERENCES doctor,
        started_at     timestamptz NOT NULL DEFAULT now(),
        transcript_uri text
    );

    CREATE TABLE note_version (
        note_id      uuid NOT NULL,
        version      int  NOT NULL CHECK (version >= 1),
        encounter_id uuid NOT NULL REFERENCES encounter,
        patient_id   uuid NOT NULL REFERENCES patient,
        doctor_id    uuid NOT NULL REFERENCES doctor,
        soap_json    jsonb NOT NULL,           -- what the doctor signed
        draft_json   jsonb NOT NULL,           -- what the model proposed (edit distance metric)
        edit_history jsonb NOT NULL DEFAULT '[]',
        content_hash text NOT NULL,
        signed_by    uuid NOT NULL REFERENCES app_user,
        signed_at    timestamptz NOT NULL DEFAULT now(),
        trace_id     text,
        PRIMARY KEY (note_id, version)
    );

    CREATE TABLE medicine (
        medicine_id  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        name         text NOT NULL,
        composition  text NOT NULL,
        manufacturer text,
        pack_size    text,
        price_inr    numeric(10,2),
        source       text NOT NULL DEFAULT 'az-medicine-india'
    );
    CREATE INDEX medicine_composition_idx ON medicine (lower(composition));
    CREATE INDEX medicine_name_idx ON medicine (lower(name));

    CREATE TABLE medicine_stock (
        clinic_id   uuid NOT NULL REFERENCES clinic,
        medicine_id uuid NOT NULL REFERENCES medicine,
        qty         int  NOT NULL CHECK (qty >= 0),
        as_of       timestamptz NOT NULL,      -- shown on every stock flag; stale → "unknown"
        PRIMARY KEY (clinic_id, medicine_id)
    );

    CREATE TABLE prescription (
        rx_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        note_id       uuid NOT NULL,
        note_version  int  NOT NULL,
        patient_id    uuid NOT NULL REFERENCES patient,
        medicine_id   uuid REFERENCES medicine,  -- null when the doctor named something not in the formulary
        medicine_text text NOT NULL,
        dose          text NOT NULL,
        substitute_ok boolean NOT NULL DEFAULT false,  -- clinical decision: set by a named human only
        set_by        uuid NOT NULL REFERENCES app_user,
        FOREIGN KEY (note_id, note_version) REFERENCES note_version (note_id, version)
    );

    CREATE TABLE specialty_crosswalk (
        condition    text PRIMARY KEY,
        specialty_id uuid NOT NULL REFERENCES specialty,
        source       text NOT NULL,
        reviewed_by  text,                     -- reviewer mark (a role); NULL = not yet reviewed
        reviewed_at  timestamptz
    );
    """)

    # ------------------------------------------------- append-only signed notes
    op.execute("""
    CREATE FUNCTION note_version_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION 'note_version is immutable: an edit creates a new version (% blocked)', TG_OP;
    END $$;
    CREATE TRIGGER note_version_no_update BEFORE UPDATE OR DELETE ON note_version
        FOR EACH ROW EXECUTE FUNCTION note_version_immutable();
    """)

    # ------------------------------------------------ who may see whose data
    op.execute("""
    CREATE FUNCTION app_user_id() RETURNS uuid LANGUAGE sql STABLE AS $$
        SELECT NULLIF(current_setting('app.user_id', true), '')::uuid
    $$;
    CREATE FUNCTION app_role() RETURNS text LANGUAGE sql STABLE AS $$
        SELECT NULLIF(current_setting('app.role', true), '')
    $$;

    -- Patients whose clinical records the current caller may READ:
    --   patient    → self
    --   caregiver  → patients who granted records:read, not expired, not revoked
    --   doctor     → patients with an appointment with this doctor ("read if treating")
    --   system     → all (ingest worker; never an end user)
    --   desk / pharmacist / compliance → none here (they use narrower views)
    -- SECURITY DEFINER so it can read consent/app_user without recursing into their policies.
    CREATE FUNCTION app_allowed_patients() RETURNS SETOF uuid
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
        SELECT u.patient_id FROM app_user u
         WHERE u.user_id = app_user_id() AND app_role() = 'patient' AND u.patient_id IS NOT NULL
        UNION
        SELECT c.patient_id FROM consent c
         WHERE c.grantee_user_id = app_user_id() AND app_role() = 'caregiver'
           AND 'records:read' = ANY (c.scope) AND c.revoked_at IS NULL AND c.expires_at > now()
        UNION
        SELECT a.patient_id FROM appointment a
          JOIN slot s ON s.slot_id = a.slot_id
          JOIN app_user u ON u.doctor_id = s.doctor_id
         WHERE u.user_id = app_user_id() AND app_role() = 'doctor' AND a.status IN ('booked','attended')
        UNION
        SELECT p.patient_id FROM patient p WHERE app_role() = 'system'
    $$;
    REVOKE ALL ON FUNCTION app_allowed_patients() FROM PUBLIC;
    """)

    # --------------------------------------------------------------- policies
    op.execute("""
    ALTER TABLE document   ENABLE ROW LEVEL SECURITY;
    ALTER TABLE doc_chunk  ENABLE ROW LEVEL SECURITY;
    ALTER TABLE consent    ENABLE ROW LEVEL SECURITY;
    ALTER TABLE note_version ENABLE ROW LEVEL SECURITY;
    ALTER TABLE prescription ENABLE ROW LEVEL SECURITY;
    ALTER TABLE ingest_job ENABLE ROW LEVEL SECURITY;

    CREATE POLICY document_read ON document FOR SELECT
        USING (patient_id IN (SELECT app_allowed_patients()));
    CREATE POLICY document_upload ON document FOR INSERT
        WITH CHECK (uploaded_by = app_user_id() AND patient_id IN (SELECT app_allowed_patients())
                    AND app_role() IN ('patient','caregiver','system'));
    CREATE POLICY document_system ON document FOR UPDATE
        USING (app_role() = 'system') WITH CHECK (app_role() = 'system');

    CREATE POLICY chunk_read ON doc_chunk FOR SELECT
        USING (patient_id IN (SELECT app_allowed_patients()));
    CREATE POLICY chunk_write ON doc_chunk FOR INSERT
        WITH CHECK (app_role() = 'system');

    CREATE POLICY ingest_job_read ON ingest_job FOR SELECT
        USING (app_role() = 'system' OR doc_id IN (SELECT doc_id FROM document));  -- document RLS applies
    CREATE POLICY ingest_job_system ON ingest_job FOR ALL
        USING (app_role() = 'system') WITH CHECK (app_role() = 'system');
    CREATE POLICY ingest_job_create ON ingest_job FOR INSERT
        WITH CHECK (doc_id IN (SELECT doc_id FROM document));

    -- Consent: the patient grants and revokes; the grantee and compliance may read.
    CREATE POLICY consent_read ON consent FOR SELECT USING (
        grantee_user_id = app_user_id()
        OR patient_id IN (SELECT u.patient_id FROM app_user u WHERE u.user_id = app_user_id() AND app_role() = 'patient')
        OR app_role() = 'compliance');
    CREATE POLICY consent_grant ON consent FOR INSERT WITH CHECK (
        app_role() = 'patient' AND granted_by = app_user_id()
        AND patient_id IN (SELECT u.patient_id FROM app_user u WHERE u.user_id = app_user_id()));
    CREATE POLICY consent_revoke ON consent FOR UPDATE USING (
        app_role() = 'patient'
        AND patient_id IN (SELECT u.patient_id FROM app_user u WHERE u.user_id = app_user_id()))
        WITH CHECK (revoked_at IS NOT NULL);

    -- Identity and demographics (direct identifiers): self, treating/consented scope, desk, compliance.
    ALTER TABLE patient  ENABLE ROW LEVEL SECURITY;
    ALTER TABLE app_user ENABLE ROW LEVEL SECURITY;
    CREATE POLICY patient_read ON patient FOR SELECT USING (
        patient_id IN (SELECT app_allowed_patients()) OR app_role() IN ('desk','compliance'));
    CREATE POLICY app_user_read ON app_user FOR SELECT USING (
        user_id = app_user_id() OR app_role() IN ('desk','compliance','system'));

    -- Signed notes: readable by allowed patients' scope (incl. treating doctor) and compliance;
    -- written only by the doctor of the encounter.
    CREATE POLICY note_read ON note_version FOR SELECT USING (
        patient_id IN (SELECT app_allowed_patients()) OR app_role() = 'compliance');
    CREATE POLICY note_sign ON note_version FOR INSERT WITH CHECK (
        app_role() = 'doctor' AND signed_by = app_user_id()
        AND doctor_id IN (SELECT u.doctor_id FROM app_user u WHERE u.user_id = app_user_id()));

    -- Prescriptions: as notes, plus the pharmacist sees prescription lines.
    CREATE POLICY rx_read ON prescription FOR SELECT USING (
        patient_id IN (SELECT app_allowed_patients()) OR app_role() IN ('pharmacist','compliance'));
    CREATE POLICY rx_write ON prescription FOR INSERT WITH CHECK (app_role() = 'doctor' AND set_by = app_user_id());
    """)

    # ------------------------------------------------------------------ grants
    op.execute(f"""
    GRANT USAGE ON SCHEMA public TO {APP_ROLE};
    GRANT USAGE, CREATE ON SCHEMA langgraph TO {APP_ROLE};           -- checkpointer.setup() creates its tables
    GRANT ALL ON ALL TABLES IN SCHEMA langgraph TO {APP_ROLE};
    ALTER DEFAULT PRIVILEGES IN SCHEMA langgraph GRANT ALL ON TABLES TO {APP_ROLE};

    -- reference + scheduling data
    GRANT SELECT ON hospital, clinic, specialty, doctor, doctor_clinic, slot, patient, app_user,
                    medicine, medicine_stock, specialty_crosswalk TO {APP_ROLE};
    GRANT SELECT, INSERT, UPDATE ON appointment, handoff_ticket TO {APP_ROLE};
    GRANT UPDATE (qty, as_of) ON medicine_stock TO {APP_ROLE};

    -- records + clinical: RLS decides rows; grants decide verbs AND columns
    GRANT SELECT, INSERT ON document, ingest_job, consent TO {APP_ROLE};
    GRANT UPDATE (revoked_at) ON consent TO {APP_ROLE};             -- revoke only; never extend expiry
    GRANT UPDATE (phi_status) ON document TO {APP_ROLE};
    GRANT UPDATE (status, error, updated_at) ON ingest_job TO {APP_ROLE};
    GRANT SELECT, INSERT ON doc_chunk, encounter, note_version, prescription TO {APP_ROLE};

    -- policies call this; PUBLIC was revoked above, so grant it to the app role only
    GRANT EXECUTE ON FUNCTION app_allowed_patients() TO {APP_ROLE};

    -- audit: append and read only (trigger also blocks UPDATE/DELETE, even for the owner)
    GRANT SELECT, INSERT ON audit_event TO {APP_ROLE};
    """)


def downgrade() -> None:
    op.execute(f"""
    REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {APP_ROLE};
    REVOKE ALL ON ALL TABLES IN SCHEMA langgraph FROM {APP_ROLE};
    ALTER DEFAULT PRIVILEGES IN SCHEMA langgraph REVOKE ALL ON TABLES FROM {APP_ROLE};
    REVOKE ALL ON SCHEMA langgraph FROM {APP_ROLE};
    REVOKE ALL ON SCHEMA public FROM {APP_ROLE};
    DROP TABLE IF EXISTS prescription, medicine_stock, medicine, note_version, encounter, doc_chunk,
        ingest_job, document, consent, specialty_crosswalk CASCADE;
    DROP FUNCTION IF EXISTS app_allowed_patients(), app_user_id(), app_role(), note_version_immutable();
    """)
