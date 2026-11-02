"""Patient location preferences for the shortlist (task card T10).

Found on the full 480k-slot dataset: a Pune patient was offered three Hyderabad doctors, because the
shortlist knew nothing about where the patient is. Ranking per T10: specialty → same city →
doctor speaks the patient's language → preferred clinic → earliest slot.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-02
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE patient
        ADD COLUMN city text CHECK (city IN ('Pune', 'Hyderabad')),
        ADD COLUMN preferred_clinic_id uuid REFERENCES clinic;
    CREATE INDEX clinic_city_idx ON clinic (city);
    """)


def downgrade() -> None:
    op.execute("""
    DROP INDEX IF EXISTS clinic_city_idx;
    ALTER TABLE patient DROP COLUMN IF EXISTS preferred_clinic_id, DROP COLUMN IF EXISTS city;
    """)
