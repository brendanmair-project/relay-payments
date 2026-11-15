"""payment_explanations: how each explanation was produced (REL-63)

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-10

Hard-coded DDL, no imports from `app` (see 0001). Five nullable columns, so rows stored before this migration stay
valid and read as unknown: the model that was asked (even when the rules text is shown), the cause each side named,
the wall time of the model call and the structured inputs the prompt was built from (never the description).
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

UPGRADE = [
    "ALTER TABLE payment_explanations"
    " ADD COLUMN attempted_model text,"
    " ADD COLUMN model_cause text,"
    " ADD COLUMN rules_cause text,"
    " ADD COLUMN generation_ms integer,"
    " ADD COLUMN inputs jsonb",
    "ALTER TABLE payment_explanations ADD CONSTRAINT ck_payment_explanations_generation_ms"
    " CHECK (generation_ms IS NULL OR generation_ms >= 0)",
    "ALTER TABLE payment_explanations ADD CONSTRAINT ck_payment_explanations_attempted_model"
    " CHECK (model IS NULL OR attempted_model = model)",
]

DOWNGRADE = [
    "ALTER TABLE payment_explanations DROP CONSTRAINT ck_payment_explanations_attempted_model",
    "ALTER TABLE payment_explanations DROP CONSTRAINT ck_payment_explanations_generation_ms",
    "ALTER TABLE payment_explanations"
    " DROP COLUMN inputs, DROP COLUMN generation_ms, DROP COLUMN rules_cause,"
    " DROP COLUMN model_cause, DROP COLUMN attempted_model",
]


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(statement)
