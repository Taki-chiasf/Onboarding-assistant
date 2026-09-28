"""record per-case eval runs and nightly run summaries

Revision ID: 0006_nightly_eval_loop
Revises: 0005_feedback_eval_store
Create Date: 2026-09-28

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_nightly_eval_loop"
down_revision: str | None = "0005_feedback_eval_store"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("eval_runs", sa.Column("suite", sa.String(length=16), nullable=True))
    op.add_column("eval_runs", sa.Column("persona", sa.String(length=64), nullable=True))
    op.add_column("eval_runs", sa.Column("actual_intent", sa.String(length=32), nullable=True))
    op.add_column("eval_runs", sa.Column("router_confidence", sa.Float(), nullable=True))
    op.add_column(
        "eval_runs",
        sa.Column("retrieved_source_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("eval_runs", sa.Column("generated_sql", sa.Text(), nullable=True))
    op.add_column("eval_runs", sa.Column("judge_passed", sa.Boolean(), nullable=True))

    # A synthetic verdict grades an eval case rather than a chat message, so
    # the message link becomes optional and a case link is added.
    op.alter_column("feedback", "message_id", existing_type=sa.Uuid(), nullable=True)
    op.add_column("feedback", sa.Column("case_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_feedback_case_id_eval_cases"),
        "feedback",
        "eval_cases",
        ["case_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.create_table(
        "nightly_eval_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "run_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("strict", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("keyless", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("prompt_version", sa.String(length=255), nullable=True),
        sa.Column("model_version", sa.String(length=255), nullable=True),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("sections", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("regressions", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("streak", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_nightly_eval_runs")),
    )


def downgrade() -> None:
    op.drop_table("nightly_eval_runs")
    op.drop_constraint(op.f("fk_feedback_case_id_eval_cases"), "feedback", type_="foreignkey")
    op.drop_column("feedback", "case_id")
    op.alter_column("feedback", "message_id", existing_type=sa.Uuid(), nullable=False)
    for column in (
        "judge_passed",
        "generated_sql",
        "retrieved_source_ids",
        "router_confidence",
        "actual_intent",
        "persona",
        "suite",
    ):
        op.drop_column("eval_runs", column)
