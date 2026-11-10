"""payments, payment_events and idempotency_keys (REL-15)

Revision ID: 0001
Revises:
Create Date: 2026-10-26

The DDL is written out in full on purpose: a migration must keep working when the application models change,
so it imports nothing from `app`. It follows docs/architecture/data-model.md.
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

UPGRADE = [
    """
    CREATE TABLE payments (
        id uuid PRIMARY KEY,
        amount_minor bigint NOT NULL,
        currency char(3) NOT NULL,
        description varchar(200),
        reference varchar(64),
        status text NOT NULL,
        processor char(1),
        attempt_no smallint NOT NULL DEFAULT 0,
        is_final boolean NOT NULL DEFAULT false,
        correlation_id varchar(64) NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        status_changed_at timestamptz NOT NULL DEFAULT now(),
        last_driven_at timestamptz,
        final_at timestamptz,
        CONSTRAINT ck_payments_amount_range CHECK (amount_minor BETWEEN 1 AND 1000000000000),
        CONSTRAINT ck_payments_currency CHECK (currency IN ('USD','EUR','GBP','JPY')),
        CONSTRAINT ck_payments_reference CHECK (reference ~ '^[A-Za-z0-9._-]{1,64}$'),
        CONSTRAINT ck_payments_status
            CHECK (status IN ('received','routed','authorized','captured','declined','failed')),
        CONSTRAINT ck_payments_processor CHECK (processor IN ('A','B')),
        CONSTRAINT ck_payments_attempt_no CHECK (attempt_no BETWEEN 0 AND 2),
        CONSTRAINT ck_payments_received_attempt_zero CHECK ((attempt_no = 0) = (status = 'received')),
        CONSTRAINT ck_payments_final_status CHECK (NOT is_final OR status IN ('captured','declined','failed')),
        CONSTRAINT ck_payments_final_at CHECK ((final_at IS NULL) = (NOT is_final)),
        CONSTRAINT ck_payments_processor_attempt CHECK ((processor IS NULL) = (attempt_no = 0))
    )
    """,
    "CREATE INDEX ix_payments_status_processor_created_at ON payments (status, processor, created_at)",
    "CREATE INDEX ix_payments_status_status_changed_at ON payments (status, status_changed_at)",
    "CREATE INDEX ix_payments_created_at_id ON payments (created_at DESC, id DESC)",
    """
    CREATE TABLE payment_events (
        id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        payment_id uuid NOT NULL REFERENCES payments (id),
        seq integer NOT NULL,
        attempt_no smallint NOT NULL,
        type text NOT NULL,
        from_status text,
        to_status text,
        processor char(1),
        reason text,
        data jsonb NOT NULL DEFAULT '{}'::jsonb,
        correlation_id varchar(64) NOT NULL,
        occurred_at timestamptz NOT NULL DEFAULT now(),
        published_at timestamptz,
        CONSTRAINT uq_payment_events_payment_id_seq UNIQUE (payment_id, seq),
        CONSTRAINT ck_payment_events_attempt_no CHECK (attempt_no BETWEEN 0 AND 2),
        CONSTRAINT ck_payment_events_type CHECK (type IN (
            'payment.received','payment.routed','attempt.authorize_result','payment.authorized',
            'attempt.capture_result','payment.captured','payment.declined','payment.failed',
            'payment.retry_scheduled','payment.final','attempt.late_result','payment.redriven',
            'payment.explained')),
        CONSTRAINT ck_payment_events_from_needs_to CHECK (to_status IS NOT NULL OR from_status IS NULL),
        CONSTRAINT ck_payment_events_processor CHECK (processor IN ('A','B')),
        CONSTRAINT ck_payment_events_processor_required CHECK (
            type NOT IN ('payment.routed','payment.failed','attempt.authorize_result',
                         'attempt.capture_result','attempt.late_result')
            OR processor IS NOT NULL),
        CONSTRAINT ck_payment_events_reason CHECK (reason IS NULL OR reason IN (
            'initial','failover','retry','static','insufficient_funds','do_not_honor','card_expired',
            'timeout','outage','capture_failed','stale_attempt','after_timeout'))
    )
    """,
    "CREATE INDEX ix_payment_events_type_processor_occurred_at ON payment_events (type, processor, occurred_at)",
    "CREATE INDEX ix_payment_events_unpublished ON payment_events (id) WHERE published_at IS NULL",
    # Append-only (ADR-0003): no DELETE; the only UPDATE is setting published_at from null to a time.
    # TRUNCATE does not fire row triggers, which is how the demo reset empties the table (data-model.md).
    """
    CREATE FUNCTION payment_events_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'payment_events is append-only: DELETE is not allowed'
                USING ERRCODE = 'restrict_violation';
        END IF;
        IF OLD.published_at IS NOT NULL
           OR NEW.published_at IS NULL
           OR (to_jsonb(NEW) - 'published_at') IS DISTINCT FROM (to_jsonb(OLD) - 'published_at') THEN
            RAISE EXCEPTION 'payment_events is append-only: only published_at may be set, once'
                USING ERRCODE = 'restrict_violation';
        END IF;
        RETURN NEW;
    END
    $$
    """,
    """
    CREATE TRIGGER payment_events_append_only BEFORE UPDATE OR DELETE ON payment_events
        FOR EACH ROW EXECUTE FUNCTION payment_events_append_only()
    """,
    """
    CREATE TABLE idempotency_keys (
        key varchar(255) PRIMARY KEY,
        request_hash char(64) NOT NULL,
        state text NOT NULL,
        lease_token uuid NOT NULL,
        lease_expires_at timestamptz NOT NULL,
        payment_id uuid REFERENCES payments (id),
        response_status smallint,
        response_body jsonb,
        created_at timestamptz NOT NULL DEFAULT now(),
        expires_at timestamptz NOT NULL,
        CONSTRAINT ck_idempotency_keys_state CHECK (state IN ('in_progress','completed')),
        CONSTRAINT ck_idempotency_keys_response_body CHECK ((state = 'completed') = (response_body IS NOT NULL))
    )
    """,
    "CREATE INDEX ix_idempotency_keys_expires_at ON idempotency_keys (expires_at)",
]

DOWNGRADE = [
    "DROP TABLE idempotency_keys",
    "DROP TRIGGER payment_events_append_only ON payment_events",
    "DROP FUNCTION payment_events_append_only()",
    "DROP TABLE payment_events",
    "DROP TABLE payments",
]


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(statement)
