import pytest

from app.text_to_sql.guard import SqlGuardError, validate_query


def test_accepts_single_select() -> None:
    sql = "SELECT id, name FROM org_members WHERE dept = 'Engineering'"
    assert validate_query(sql) == sql


def test_accepts_select_with_read_only_cte() -> None:
    sql = "WITH top AS (SELECT * FROM okrs ORDER BY progress DESC) SELECT * FROM top"
    assert validate_query(sql) == sql


def test_accepts_union_of_selects() -> None:
    sql = "SELECT name FROM projects UNION SELECT name FROM projects"
    assert validate_query(sql) == sql


@pytest.mark.parametrize("sql", ["", "   ", "\n\t"])
def test_rejects_empty(sql: str) -> None:
    with pytest.raises(SqlGuardError):
        validate_query(sql)


def test_rejects_comment_only() -> None:
    with pytest.raises(SqlGuardError):
        validate_query("-- just a comment")


def test_rejects_multiple_statements() -> None:
    with pytest.raises(SqlGuardError, match="multiple"):
        validate_query("SELECT * FROM org_members; DROP TABLE org_members")


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO org_members (name) VALUES ('x')",
        "UPDATE org_members SET name = 'x'",
        "DELETE FROM org_members",
        "CREATE TABLE x (a int)",
        "DROP TABLE org_members",
        "TRUNCATE TABLE org_members",
        "COPY org_members FROM '/tmp/x'",
        "GRANT SELECT ON org_members TO app_readonly",
        "SET app.principal_dept = 'Finance'",
        "SET ROLE app_readonly",
        "BEGIN",
        "SHOW work_mem",
        "VALUES (1)",
        "EXPLAIN SELECT * FROM org_members",
    ],
)
def test_rejects_non_select(sql: str) -> None:
    with pytest.raises(SqlGuardError):
        validate_query(sql)


def test_rejects_data_modifying_cte() -> None:
    sql = "WITH x AS (DELETE FROM org_members RETURNING *) SELECT * FROM x"
    with pytest.raises(SqlGuardError, match="Delete"):
        validate_query(sql)


def test_rejects_session_context_functions() -> None:
    """A SELECT must not be able to rewrite the row-level-security context.

    ``set_config`` and ``current_setting`` read or write the transaction-local
    settings the access policies depend on, so any reference to them is denied
    even though they appear inside an otherwise valid SELECT.
    """
    payloads = [
        "SELECT set_config('app.principal_dept', 'Finance', true)",
        "SELECT current_setting('app.principal_dept')",
        "SELECT pg_catalog.set_config('app.principal_dept', 'Finance', true)",
        "SELECT pg_catalog.current_setting('app.principal_dept')",
        'SELECT "set_config"(\'app.principal_dept\', \'Finance\', true)',
        "WITH x AS MATERIALIZED "
        "(SELECT set_config('app.principal_dept', 'Finance', true)) "
        "SELECT name FROM org_members",
        "SELECT m.name FROM org_members m, "
        "set_config('app.principal_dept', 'Finance', true) s",
        "SELECT name FROM org_members "
        "WHERE set_config('app.principal_dept', 'Finance', true) IS NOT NULL",
    ]
    for sql in payloads:
        with pytest.raises(SqlGuardError, match="not allowed"):
            validate_query(sql)


def test_allows_non_context_functions() -> None:
    sql = (
        "SELECT count(*), max(created_at) FROM tickets "
        "WHERE created_at > now() - interval '7 days'"
    )
    assert validate_query(sql) == sql


def test_rejects_select_into() -> None:
    with pytest.raises(SqlGuardError, match="Into"):
        validate_query("SELECT * INTO backup FROM org_members")


def test_rejects_row_locking() -> None:
    with pytest.raises(SqlGuardError, match="Lock"):
        validate_query("SELECT * FROM org_members FOR UPDATE")
