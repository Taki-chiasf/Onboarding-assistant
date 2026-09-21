"""documents chunk table with vector, full-text, and trigram indexes

Revision ID: 0002_doc_chunks
Revises: 0001_baseline
Create Date: 2026-09-21

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0002_doc_chunks"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "doc_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_uri", sa.String(length=1024), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("section_anchor", sa.String(length=1024), nullable=False),
        sa.Column("acl_tags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("embedding", Vector(1024), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_doc_chunks")),
    )
    op.create_unique_constraint(
        op.f("uq_doc_chunks_source_uri_chunk_index"),
        "doc_chunks",
        ["source_uri", "chunk_index"],
    )
    op.execute(
        "ALTER TABLE doc_chunks ADD COLUMN search_vector tsvector "
        "GENERATED ALWAYS AS (to_tsvector('english', content)) STORED"
    )
    op.execute(
        "CREATE INDEX ix_doc_chunks_embedding_hnsw ON doc_chunks "
        "USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute("CREATE INDEX ix_doc_chunks_search_vector ON doc_chunks USING GIN (search_vector)")
    op.execute(
        "CREATE INDEX ix_doc_chunks_content_trgm ON doc_chunks "
        "USING GIN (content gin_trgm_ops)"
    )


def downgrade() -> None:
    op.drop_table("doc_chunks")
