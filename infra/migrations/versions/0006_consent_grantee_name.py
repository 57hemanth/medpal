"""A consent's grantee name, readable by the people the consent concerns, and nobody else.

Row-level security rightly hides other users' rows, so a patient who shared her records could not see
*who* she shared them with. This function returns the grantee's name only to the consent's patient, the
grantee, or compliance; for anyone else (or an unknown consent) it returns NULL. It takes a consent id,
not a user id, so it can't be used to look up arbitrary people.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-03
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

APP_ROLE = "medpal_app"


def upgrade() -> None:
    op.execute(f"""
    CREATE FUNCTION consent_grantee_name(p_consent uuid) RETURNS text
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
        SELECT gp.name
          FROM consent c
          JOIN app_user gu ON gu.user_id = c.grantee_user_id
          LEFT JOIN patient gp ON gp.patient_id = gu.patient_id
         WHERE c.consent_id = p_consent
           AND (
                c.patient_id = (SELECT u.patient_id FROM app_user u WHERE u.user_id = app_user_id())
             OR c.grantee_user_id = app_user_id()
             OR app_role() = 'compliance'
           )
    $$;
    REVOKE ALL ON FUNCTION consent_grantee_name(uuid) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION consent_grantee_name(uuid) TO {APP_ROLE};
    """)


def downgrade() -> None:
    op.execute("DROP FUNCTION consent_grantee_name(uuid)")
