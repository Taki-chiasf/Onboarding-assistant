"""encrypt conversation history at rest

Adds the wrapped per-conversation data key. Conversation titles and message
bodies are sealed by the application layer under that key; rows written before
a key was configured stay readable as plaintext until the backfill CLI wraps
them. Dropping the column on downgrade discards the wrapped keys, which makes
any sealed history unrecoverable, so downgrade is a data-loss operation.

Revision ID: 0007_history_encryption
Revises: 0006_nightly_eval_loop
Create Date: 2026-09-29

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_history_encryption"
down_revision: str | None = "0006_nightly_eval_loop"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("key_wrapped", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("conversations", "key_wrapped")
