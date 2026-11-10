"""The routed reason `adaptive` joins the payment_events reason CHECK (REL-44, ADR-0016)

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-06

Hard-coded DDL, no imports from `app` (see 0001). The CHECK is dropped and recreated with the same list plus
`adaptive`. The downgrade first rewrites any `adaptive` event to `initial` (the closest earlier reason), which needs
the append-only trigger switched off for that one statement (it allows no other UPDATE), and then restores the
previous list.
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

BASE_REASONS = (
    "'initial','failover','retry','static','insufficient_funds','do_not_honor','card_expired',"
    "'timeout','outage','capture_failed','stale_attempt','after_timeout'"
)


def _recreate(reasons: str) -> list[str]:
    return [
        "ALTER TABLE payment_events DROP CONSTRAINT ck_payment_events_reason",
        "ALTER TABLE payment_events ADD CONSTRAINT ck_payment_events_reason "
        f"CHECK (reason IS NULL OR reason IN ({reasons}))",
    ]


UPGRADE = _recreate(BASE_REASONS + ",'adaptive'")
DOWNGRADE = [
    "ALTER TABLE payment_events DISABLE TRIGGER payment_events_append_only",
    "UPDATE payment_events SET reason = 'initial' WHERE reason = 'adaptive'",
    "ALTER TABLE payment_events ENABLE TRIGGER payment_events_append_only",
    *_recreate(BASE_REASONS),
]


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(statement)
