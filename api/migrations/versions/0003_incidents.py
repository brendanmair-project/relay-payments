"""incidents and incident_detector_state (REL-34)

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-02

Hard-coded DDL, no imports from `app` (see 0001). Follows docs/architecture/data-model.md: the partial unique index
allows at most one open incident per processor, whoever opened it (ADR-0014).
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

UPGRADE = [
    """
    CREATE TABLE incidents (
        id uuid PRIMARY KEY,
        processor char(1),
        source text NOT NULL,
        status text NOT NULL,
        title text NOT NULL,
        opened_at timestamptz NOT NULL,
        opened_by_event_id bigint,
        recovered_at timestamptz,
        triaged_at timestamptz,
        resolved_at timestamptz,
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT ck_incidents_processor CHECK (processor IN ('A','B')),
        CONSTRAINT ck_incidents_source CHECK (source IN ('rule','manual')),
        CONSTRAINT ck_incidents_status CHECK (status IN ('detected','triaged','resolved'))
    )
    """,
    "CREATE INDEX ix_incidents_opened_at ON incidents (opened_at DESC)",
    "CREATE UNIQUE INDEX uq_incidents_open_per_processor ON incidents (processor)"
    " WHERE status <> 'resolved' AND processor IS NOT NULL",
    """
    CREATE TABLE incident_detector_state (
        processor char(1) PRIMARY KEY,
        last_event_id bigint NOT NULL,
        CONSTRAINT ck_incident_detector_state_processor CHECK (processor IN ('A','B'))
    )
    """,
]

DOWNGRADE = ["DROP TABLE incident_detector_state", "DROP TABLE incidents"]


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(statement)
