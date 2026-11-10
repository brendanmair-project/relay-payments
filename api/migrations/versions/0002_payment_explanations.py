"""payment_explanations (REL-25)

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-30

Hard-coded DDL, no imports from `app` (see 0001). Follows docs/architecture/data-model.md: the endpoint reads the
latest row per payment; the partial unique index keeps the automatic (final_failure) explanation to one per payment.
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

UPGRADE = [
    """
    CREATE TABLE payment_explanations (
        id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        payment_id uuid NOT NULL REFERENCES payments (id),
        source text NOT NULL,
        model text,
        text text NOT NULL,
        cited_event_seqs integer[] NOT NULL,
        trigger text NOT NULL,
        fallback_reason text,
        final_event_at timestamptz NOT NULL,
        generated_at timestamptz NOT NULL,
        CONSTRAINT ck_payment_explanations_source CHECK (source IN ('model','rules')),
        CONSTRAINT ck_payment_explanations_model CHECK ((source = 'model') = (model IS NOT NULL)),
        CONSTRAINT ck_payment_explanations_trigger CHECK (trigger IN ('final_failure','on_request','regenerate'))
    )
    """,
    "CREATE INDEX ix_payment_explanations_payment_id_generated_at"
    " ON payment_explanations (payment_id, generated_at DESC)",
    "CREATE UNIQUE INDEX uq_payment_explanations_final_failure ON payment_explanations (payment_id)"
    " WHERE trigger = 'final_failure'",
]

DOWNGRADE = ["DROP TABLE payment_explanations"]


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(statement)
