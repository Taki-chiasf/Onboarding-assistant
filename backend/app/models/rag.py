import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Integer, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

EMBEDDING_DIM = 1024


class DocChunk(Base):
    __tablename__ = "doc_chunks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    source_uri: Mapped[str] = mapped_column(String(1024), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    section_anchor: Mapped[str] = mapped_column(String(1024), nullable=False)
    acl_tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
