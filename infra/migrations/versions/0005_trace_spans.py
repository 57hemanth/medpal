"""In-boundary tracing: one row per graph node, model call or tool call.

Metadata only. There is deliberately no column that could hold prompt, response or document text, so
traces can never become a second copy of patient data. Readable by compliance (and the system worker);
the app may only append.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-03
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

APP_ROLE = "medpal_app"


def upgrade() -> None:
    op.execute(f"""
    CREATE TABLE trace_span (
        span_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        trace_id     text NOT NULL,              -- the graph thread id: one trace per run
        workflow     text NOT NULL,              -- triage | records | scribe | ingest
        kind         text NOT NULL CHECK (kind IN ('node', 'model', 'tool')),
        name         text NOT NULL,              -- node name, model id or tool name
        started_at   timestamptz NOT NULL,
        duration_ms  double precision NOT NULL CHECK (duration_ms >= 0),
        status       text NOT NULL CHECK (status IN ('ok', 'error')),
        error_type   text,                       -- exception class name only, never its message
        tokens_in    integer,
        tokens_out   integer,
        tokens_estimated boolean NOT NULL DEFAULT false,
        cost         numeric(12, 6),             -- NULL when the model has no configured price
        price_list_date date
    );
    CREATE INDEX trace_span_trace_idx ON trace_span (trace_id);
    CREATE INDEX trace_span_workflow_time_idx ON trace_span (workflow, started_at);

    ALTER TABLE trace_span ENABLE ROW LEVEL SECURITY;
    CREATE POLICY trace_append ON trace_span FOR INSERT WITH CHECK (true);
    CREATE POLICY trace_read ON trace_span FOR SELECT USING (app_role() IN ('compliance', 'system'));
    GRANT SELECT, INSERT ON trace_span TO {APP_ROLE};
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS trace_span")
