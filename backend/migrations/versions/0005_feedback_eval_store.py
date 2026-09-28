"""link eval cases to the feedback that filed them

Revision ID: 0005_feedback_eval_store
Revises: 0004_message_detail
Create Date: 2026-09-28

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_feedback_eval_store"
down_revision: str | None = "0004_message_detail"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("eval_cases", sa.Column("source", sa.String(length=16), nullable=True))
    op.add_column("eval_cases", sa.Column("source_message_id", sa.Uuid(), nullable=True))
    op.add_column(
        "eval_cases",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_foreign_key(
        op.f("fk_eval_cases_source_message_id_messages"),
        "eval_cases",
        "messages",
        ["source_message_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_eval_cases_source_message_id_messages"), "eval_cases", type_="foreignkey"
    )
    op.drop_column("eval_cases", "created_at")
    op.drop_column("eval_cases", "source_message_id")
    op.drop_column("eval_cases", "source")
