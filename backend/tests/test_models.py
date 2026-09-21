from app.models import Base

EXPECTED_TABLES = {
    "conversations",
    "messages",
    "feedback",
    "eval_cases",
    "eval_runs",
    "ingest_jobs",
    "cost_ledger",
    "audit_logs",
    "doc_chunks",
}


def test_all_tables_present() -> None:
    tables = set(Base.metadata.tables)
    assert EXPECTED_TABLES <= tables


def test_message_columns() -> None:
    columns = set(Base.metadata.tables["messages"].columns.keys())
    assert {
        "id",
        "conversation_id",
        "role",
        "content",
        "trace_id",
        "cost_usd",
        "latency_ms",
        "prompt_version",
        "model_version",
        "created_at",
    } <= columns


def test_foreign_keys() -> None:
    messages = Base.metadata.tables["messages"]
    assert "conversations.id" in [fk.target_fullname for fk in messages.foreign_keys]
    feedback = Base.metadata.tables["feedback"]
    assert "messages.id" in [fk.target_fullname for fk in feedback.foreign_keys]
    runs = Base.metadata.tables["eval_runs"]
    assert "eval_cases.id" in [fk.target_fullname for fk in runs.foreign_keys]


def test_cost_ledger_composite_primary_key() -> None:
    pk = Base.metadata.tables["cost_ledger"].primary_key.columns.keys()
    assert set(pk) == {"user_id", "day", "model"}


def test_doc_chunk_columns() -> None:
    columns = set(Base.metadata.tables["doc_chunks"].columns.keys())
    assert {
        "id",
        "source_uri",
        "source_type",
        "section_anchor",
        "acl_tags",
        "embedding",
        "content",
        "content_hash",
        "chunk_index",
        "version",
        "ingested_at",
    } <= columns
