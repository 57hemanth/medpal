"""Slice 0 core schema: scheduling, identity, handoff tickets, append-only audit.

The subset of the corrected data model that W1 needs end to end.
Plan task T2.1 adds the clinical, records and pharmacy tables plus RLS in later revisions.

Corrections versus the original design's entity model, marked Δ:
  Δ slot.capacity is enforced by the booking transaction, not a unique slot_id constraint
  Δ appointment.idempotency_key is UNIQUE (retries never double-book)
  Δ doctor_clinic many-to-many (doctors work across clinics)
  Δ app_user is the identity behind consent grantees and audit actors
  Δ audit_event is append-only (trigger) and partitioned by month

Revision ID: 0001
Revises:
Create Date: 2026-11-02
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE SCHEMA IF NOT EXISTS langgraph")

    op.execute("""
    CREATE TABLE hospital (
        hospital_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        name        text NOT NULL,
        city        text NOT NULL CHECK (city IN ('Pune', 'Hyderabad'))
    );

    CREATE TABLE clinic (
        clinic_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        hospital_id uuid REFERENCES hospital,
        name        text NOT NULL,
        city        text NOT NULL CHECK (city IN ('Pune', 'Hyderabad')),
        district    text NOT NULL,
        opens_at    time NOT NULL,
        closes_at   time NOT NULL CHECK (closes_at > opens_at)
    );

    CREATE TABLE specialty (
        specialty_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        name         text NOT NULL UNIQUE
    );

    CREATE TABLE doctor (
        doctor_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        name         text NOT NULL,
        specialty_id uuid NOT NULL REFERENCES specialty,
        languages    text[] NOT NULL DEFAULT '{en}',
        years        smallint CHECK (years >= 0),
        synthetic    boolean NOT NULL DEFAULT true
    );

    CREATE TABLE doctor_clinic (
        doctor_id uuid NOT NULL REFERENCES doctor,
        clinic_id uuid NOT NULL REFERENCES clinic,
        PRIMARY KEY (doctor_id, clinic_id)
    );

    CREATE TABLE slot (
        slot_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        doctor_id uuid NOT NULL REFERENCES doctor,
        clinic_id uuid NOT NULL REFERENCES clinic,
        starts_at timestamptz NOT NULL,
        capacity  smallint NOT NULL DEFAULT 1 CHECK (capacity >= 1),
        synthetic boolean NOT NULL DEFAULT true,
        UNIQUE (doctor_id, starts_at)
    );
    CREATE INDEX slot_starts_at_idx ON slot (starts_at);

    CREATE TABLE patient (
        patient_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        abha_id    text UNIQUE,
        name       text NOT NULL,
        dob        date CHECK (dob <= current_date),
        phone      text,
        language   text NOT NULL DEFAULT 'en',
        synthetic  boolean NOT NULL DEFAULT true
    );

    CREATE TABLE app_user (
        user_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        role       text NOT NULL CHECK (role IN ('patient','caregiver','doctor','desk','pharmacist','compliance')),
        patient_id uuid REFERENCES patient,
        doctor_id  uuid REFERENCES doctor,
        CHECK (role <> 'patient' OR patient_id IS NOT NULL),
        CHECK (role <> 'doctor' OR doctor_id IS NOT NULL)
    );

    CREATE TABLE appointment (
        appt_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        patient_id      uuid NOT NULL REFERENCES patient,
        slot_id         uuid NOT NULL REFERENCES slot,
        status          text NOT NULL CHECK (status IN ('booked','cancelled','attended','no_show')),
        source          text NOT NULL CHECK (source IN ('assistant','desk','phone')),
        idempotency_key text NOT NULL UNIQUE,
        created_by      uuid NOT NULL REFERENCES app_user,
        created_at      timestamptz NOT NULL DEFAULT now()
    );
    CREATE UNIQUE INDEX appt_one_per_patient_slot ON appointment (slot_id, patient_id) WHERE status = 'booked';
    CREATE INDEX appt_slot_booked_idx ON appointment (slot_id) WHERE status = 'booked';

    CREATE TABLE handoff_ticket (
        ticket_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        kind        text NOT NULL CHECK (kind IN ('emergency','front_desk','records','review')),
        status      text NOT NULL DEFAULT 'open' CHECK (status IN ('open','in_progress','closed')),
        patient_id  uuid REFERENCES patient,
        reason      text NOT NULL,          -- rule ids / reason codes, never free model text
        thread_id   text,
        created_by  uuid NOT NULL REFERENCES app_user,
        created_at  timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX handoff_open_idx ON handoff_ticket (kind, created_at) WHERE status <> 'closed';
    """)

    op.execute("""
    CREATE TABLE audit_event (
        event_id   bigint GENERATED ALWAYS AS IDENTITY,
        at         timestamptz NOT NULL DEFAULT now(),
        actor_id   uuid NOT NULL,
        actor_role text NOT NULL,
        action     text NOT NULL,
        resource   text NOT NULL,
        record_id  text NOT NULL,
        patient_id uuid,
        purpose    text NOT NULL,
        trace_id   text,
        PRIMARY KEY (event_id, at)
    ) PARTITION BY RANGE (at);
    -- Monthly partitions are added by a maintenance job (plan T2.1); the default catches the rest.
    CREATE TABLE audit_event_default PARTITION OF audit_event DEFAULT;
    CREATE INDEX audit_record_idx ON audit_event (resource, record_id, at);
    CREATE INDEX audit_patient_idx ON audit_event (patient_id, at);

    CREATE FUNCTION audit_event_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION 'audit_event is append-only (% blocked)', TG_OP;
    END $$;
    CREATE TRIGGER audit_event_no_update BEFORE UPDATE OR DELETE ON audit_event
        FOR EACH ROW EXECUTE FUNCTION audit_event_append_only();
    """)


def downgrade() -> None:
    op.execute("""
    DROP TABLE IF EXISTS audit_event CASCADE;
    DROP FUNCTION IF EXISTS audit_event_append_only();
    DROP TABLE IF EXISTS handoff_ticket, appointment, app_user, patient, slot, doctor_clinic,
        doctor, specialty, clinic, hospital CASCADE;
    """)
