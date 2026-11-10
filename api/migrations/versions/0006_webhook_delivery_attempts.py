"""webhook_delivery_attempts (REL-39 follow-up: every attempt is in the delivery log)

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-05

Hard-coded DDL, no imports from `app` (see 0001). One row per attempt of a delivery, written by the sender in the same
transaction that records the result; deleting a delivery (retention cleanup) deletes its attempts.
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

UPGRADE = [
    """
    CREATE TABLE webhook_delivery_attempts (
        id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        delivery_id bigint NOT NULL REFERENCES webhook_deliveries (id) ON DELETE CASCADE,
        attempt smallint NOT NULL,
        status_code integer,
        error text,
        duration_ms integer NOT NULL,
        attempted_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT ck_webhook_delivery_attempts_attempt CHECK (attempt BETWEEN 1 AND 8),
        CONSTRAINT ck_webhook_delivery_attempts_duration CHECK (duration_ms >= 0)
    )
    """,
    "CREATE INDEX ix_webhook_delivery_attempts_delivery_id ON webhook_delivery_attempts (delivery_id)",
]

DOWNGRADE = ["DROP TABLE webhook_delivery_attempts"]


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(statement)
