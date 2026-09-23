"""Text-to-SQL safety layer: parser guard and scoped read-only execution."""

from app.text_to_sql.executor import SqlExecutor, SqlResult
from app.text_to_sql.guard import SqlGuardError, validate_query

__all__ = ["SqlExecutor", "SqlGuardError", "SqlResult", "validate_query"]
