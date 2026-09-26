"""Read-only SQL gate.

Parses a candidate statement with sqlglot and rejects anything that is not a
single SELECT. The executor and the SELECT-only database role are the deeper
defense layers; this is the fast, parse-time first line of defense that also
catches payloads the role cannot, such as data-modifying CTEs.
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp

_FORBIDDEN: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.TruncateTable,
    exp.Copy,
    exp.Grant,
    exp.Revoke,
    exp.Set,
    exp.Command,
    exp.Use,
    exp.Lock,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
    exp.Into,
)

# The row-level-security policies read the caller's department and role from
# transaction-local settings. A SELECT that can also write those settings would
# be able to lift the very filter it runs under, so these functions are denied
# outright. The deep defense is the revoke on the read-only role; this is the
# parse-time layer that keeps the payload from ever reaching the database.
_FORBIDDEN_FUNCTIONS = frozenset({"set_config", "current_setting"})


class SqlGuardError(ValueError):
    """Raised when a statement fails the read-only safety gate."""


def _function_name(node: exp.Func) -> str:
    """Return the lowercased name of a function call node."""
    if isinstance(node, exp.Anonymous):
        return node.name.lower()
    return node.sql_name().lower()


def _references_forbidden_function(statement: exp.Expression) -> str | None:
    for node in statement.find_all(exp.Func):
        name = _function_name(node)
        if name in _FORBIDDEN_FUNCTIONS:
            return name
    return None



def validate_query(sql: str) -> str:
    """Return the statement unchanged if it is a single read-only SELECT.

    Raises `SqlGuardError` otherwise. The input is treated as untrusted, so the
    check runs on the parse tree rather than on raw text.
    """
    if not sql or not sql.strip():
        raise SqlGuardError("empty statement")

    statements = sqlglot.parse(sql, read="postgres")
    if len(statements) != 1:
        raise SqlGuardError("multiple statements are not allowed")

    statement = statements[0]
    if statement is None or not isinstance(statement, (exp.Select, exp.Union)):
        raise SqlGuardError("only SELECT statements are allowed")

    for forbidden in _FORBIDDEN:
        if next(statement.find_all(forbidden), None) is not None:
            raise SqlGuardError(f"{forbidden.__name__} is not allowed")

    forbidden_function = _references_forbidden_function(statement)
    if forbidden_function is not None:
        raise SqlGuardError(f"{forbidden_function} is not allowed")

    return sql
