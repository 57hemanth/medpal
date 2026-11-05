"""Mobile-number sign-in, and sharing records by mobile number.

* `app_user.phone`: everyone signs in with a mobile number and a one-time code. Unique, E.164.
* `app_user.display_name`: a name for staff accounts (patients' names live on `patient`).
* `otp_challenge`: one-time codes, stored only as a keyed hash, with expiry and an attempt count.
  Readable and writable only in the system context the sign-in service uses: before sign-in there is
  no user to scope to.
* `app_user_for_phone()` / `invite_phone()`: a patient sharing records names a mobile number. If nobody
  has that number yet, an invited account is created so the access is waiting when they first sign in.
  Both return only an id, never a name.
* `consent_grantee_label()`: who a consent is for, as the people it concerns see it: the grantee's name
  if they have one, otherwise their number with the middle digits hidden.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-03
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

APP_ROLE = "medpal_app"


def upgrade() -> None:
    op.execute(f"""
    ALTER TABLE app_user ADD COLUMN phone text UNIQUE CHECK (phone ~ '^\\+[1-9][0-9]{{7,14}}$');
    ALTER TABLE app_user ADD COLUMN display_name text;

    CREATE TABLE otp_challenge (
        challenge_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        phone        text NOT NULL,
        code_hash    text NOT NULL,
        created_at   timestamptz NOT NULL DEFAULT now(),
        expires_at   timestamptz NOT NULL,
        attempts     integer NOT NULL DEFAULT 0,
        consumed_at  timestamptz
    );
    CREATE INDEX otp_phone_idx ON otp_challenge (phone, created_at DESC);
    ALTER TABLE otp_challenge ENABLE ROW LEVEL SECURITY;
    ALTER TABLE otp_challenge FORCE ROW LEVEL SECURITY;
    CREATE POLICY otp_system ON otp_challenge FOR ALL
        USING (app_role() = 'system') WITH CHECK (app_role() = 'system');
    GRANT SELECT, INSERT, UPDATE ON otp_challenge TO {APP_ROLE};

    -- Sign-in creates accounts for new patients (system context only).
    CREATE POLICY app_user_register ON app_user FOR INSERT WITH CHECK (app_role() = 'system');
    CREATE POLICY app_user_upgrade ON app_user FOR UPDATE
        USING (app_role() = 'system') WITH CHECK (app_role() = 'system');
    CREATE POLICY patient_register ON patient FOR INSERT WITH CHECK (app_role() = 'system');
    GRANT INSERT ON app_user, patient TO {APP_ROLE};
    GRANT UPDATE (role, patient_id) ON app_user TO {APP_ROLE};

    CREATE FUNCTION app_user_for_phone(p_phone text) RETURNS uuid
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
        SELECT user_id FROM app_user WHERE phone = p_phone
    $$;
    -- Only a patient sharing their own record may invite a number; the invited account can do nothing
    -- until it signs in, and then only what a consent grants it.
    CREATE FUNCTION invite_phone(p_phone text) RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
    DECLARE v_user uuid;
    BEGIN
        IF app_role() <> 'patient' THEN
            RAISE EXCEPTION 'only patients can invite someone to share records with';
        END IF;
        SELECT user_id INTO v_user FROM app_user WHERE phone = p_phone;
        IF v_user IS NULL THEN
            INSERT INTO app_user (role, phone) VALUES ('caregiver', p_phone) RETURNING user_id INTO v_user;
        END IF;
        RETURN v_user;
    END $$;
    CREATE FUNCTION consent_grantee_label(p_consent uuid) RETURNS text
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
        SELECT COALESCE(
            consent_grantee_name(p_consent),
            (SELECT left(gu.phone, 5) || ' ••••• ' || right(gu.phone, 3)
               FROM consent c JOIN app_user gu ON gu.user_id = c.grantee_user_id
              WHERE c.consent_id = p_consent
                AND (c.patient_id = (SELECT u.patient_id FROM app_user u WHERE u.user_id = app_user_id())
                     OR c.grantee_user_id = app_user_id() OR app_role() = 'compliance'))
        )
    $$;
    -- At sign-in: may this person act as a caregiver? Yes or no only; reveals no consent details.
    CREATE FUNCTION has_active_consent(p_user uuid) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
        SELECT EXISTS (SELECT 1 FROM consent
                        WHERE grantee_user_id = p_user AND revoked_at IS NULL AND expires_at > now())
    $$;
    REVOKE ALL ON FUNCTION has_active_consent(uuid) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION has_active_consent(uuid) TO {APP_ROLE};
    REVOKE ALL ON FUNCTION app_user_for_phone(text) FROM PUBLIC;
    REVOKE ALL ON FUNCTION invite_phone(text) FROM PUBLIC;
    REVOKE ALL ON FUNCTION consent_grantee_label(uuid) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION app_user_for_phone(text) TO {APP_ROLE};
    GRANT EXECUTE ON FUNCTION invite_phone(text) TO {APP_ROLE};
    GRANT EXECUTE ON FUNCTION consent_grantee_label(uuid) TO {APP_ROLE};
    """)


def downgrade() -> None:
    op.execute("""
    DROP FUNCTION IF EXISTS has_active_consent(uuid);
    DROP FUNCTION IF EXISTS consent_grantee_label(uuid);
    DROP FUNCTION IF EXISTS invite_phone(text);
    DROP FUNCTION IF EXISTS app_user_for_phone(text);
    REVOKE UPDATE (role, patient_id) ON app_user FROM medpal_app;
    REVOKE INSERT ON app_user, patient FROM medpal_app;
    DROP POLICY IF EXISTS patient_register ON patient;
    DROP POLICY IF EXISTS app_user_upgrade ON app_user;
    DROP POLICY IF EXISTS app_user_register ON app_user;
    DROP TABLE IF EXISTS otp_challenge;
    ALTER TABLE app_user DROP COLUMN IF EXISTS display_name;
    ALTER TABLE app_user DROP COLUMN IF EXISTS phone;
    """)
