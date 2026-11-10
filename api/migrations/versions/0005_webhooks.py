"""webhook_subscriptions, webhook_deliveries and webhook_consumer_state (REL-39)

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-05

Hard-coded DDL, no imports from `app` (see 0001). Follows docs/architecture/data-model.md and ADR-0015: the unique key
on `(subscription_id, event_id)` makes a duplicate stream entry produce one delivery; the partial index serves the
send loop's "due and pending" query.
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

TYPES = "'payment.received','payment.authorized','payment.captured','payment.declined','payment.failed','payment.final'"

UPGRADE = [
    f"""
    CREATE TABLE webhook_subscriptions (
        id uuid PRIMARY KEY,
        url text NOT NULL,
        event_types text[] NOT NULL,
        secret text NOT NULL,
        active boolean NOT NULL DEFAULT true,
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT ck_webhook_subscriptions_event_types
            CHECK (cardinality(event_types) >= 1 AND event_types <@ ARRAY[{TYPES}]::text[])
    )
    """,
    "CREATE INDEX ix_webhook_subscriptions_created_at ON webhook_subscriptions (created_at DESC)",
    f"""
    CREATE TABLE webhook_deliveries (
        id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        subscription_id uuid NOT NULL REFERENCES webhook_subscriptions (id),
        event_id bigint NOT NULL,
        event_type text NOT NULL,
        attempt smallint NOT NULL DEFAULT 0,
        status text NOT NULL DEFAULT 'pending',
        next_attempt_at timestamptz NOT NULL DEFAULT now(),
        last_status_code integer,
        last_error text,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT uq_webhook_deliveries_subscription_event UNIQUE (subscription_id, event_id),
        CONSTRAINT ck_webhook_deliveries_event_type CHECK (event_type IN ({TYPES})),
        CONSTRAINT ck_webhook_deliveries_status CHECK (status IN ('pending','delivered','failed')),
        CONSTRAINT ck_webhook_deliveries_attempt CHECK (attempt BETWEEN 0 AND 8)
    )
    """,
    "CREATE INDEX ix_webhook_deliveries_due ON webhook_deliveries (next_attempt_at) WHERE status = 'pending'",
    "CREATE INDEX ix_webhook_deliveries_created_at_id ON webhook_deliveries (created_at DESC, id DESC)",
    "CREATE INDEX ix_webhook_deliveries_status_updated_at ON webhook_deliveries (status, updated_at)",
    """
    CREATE TABLE webhook_consumer_state (
        id smallint PRIMARY KEY,
        last_event_id bigint NOT NULL,
        CONSTRAINT ck_webhook_consumer_state_single_row CHECK (id = 1)
    )
    """,
]

DOWNGRADE = ["DROP TABLE webhook_consumer_state", "DROP TABLE webhook_deliveries", "DROP TABLE webhook_subscriptions"]


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(statement)
