"""incident_payments and incident_summaries (REL-35)

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-03

Hard-coded DDL, no imports from `app` (see 0001). Follows docs/architecture/data-model.md: the primary key on
`(incident_id, payment_id)` makes linking idempotent; summaries are append-only and the endpoint reads the latest.
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

UPGRADE = [
    """
    CREATE TABLE incident_payments (
        incident_id uuid NOT NULL REFERENCES incidents (id),
        payment_id uuid NOT NULL REFERENCES payments (id),
        linked_at timestamptz NOT NULL DEFAULT now(),
        first_event_id bigint NOT NULL,
        PRIMARY KEY (incident_id, payment_id)
    )
    """,
    "CREATE INDEX ix_incident_payments_payment_id ON incident_payments (payment_id)",
    """
    CREATE TABLE incident_summaries (
        id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        incident_id uuid NOT NULL REFERENCES incidents (id),
        source text NOT NULL,
        model text,
        text text NOT NULL,
        cited_event_ids bigint[] NOT NULL,
        cause text NOT NULL,
        fallback_reason text,
        generated_at timestamptz NOT NULL,
        trigger text NOT NULL,
        CONSTRAINT ck_incident_summaries_source CHECK (source IN ('model','rules')),
        CONSTRAINT ck_incident_summaries_model CHECK ((source = 'model') = (model IS NOT NULL)),
        CONSTRAINT ck_incident_summaries_cause CHECK (cause IN ('outage','timeouts','mixed','none')),
        CONSTRAINT ck_incident_summaries_trigger CHECK (trigger IN ('on_request','regenerate'))
    )
    """,
    "CREATE INDEX ix_incident_summaries_incident_id_generated_at"
    " ON incident_summaries (incident_id, generated_at DESC)",
]

DOWNGRADE = ["DROP TABLE incident_summaries", "DROP TABLE incident_payments"]


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(statement)
