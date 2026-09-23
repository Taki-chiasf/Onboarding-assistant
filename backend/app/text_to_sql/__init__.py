"""Text-to-SQL: parser guard, scoped read-only execution, and the answer path."""

from app.text_to_sql.answer import NO_MATCHING_RECORDS, SqlAnswerer
from app.text_to_sql.builder import BuiltSql, SqlBuilder, extract_sql
from app.text_to_sql.executor import SqlExecutor, SqlResult
from app.text_to_sql.guard import SqlGuardError, validate_query

__all__ = [
    "BuiltSql",
    "NO_MATCHING_RECORDS",
    "SqlAnswerer",
    "SqlBuilder",
    "SqlExecutor",
    "SqlGuardError",
    "SqlResult",
    "extract_sql",
    "validate_query",
]
