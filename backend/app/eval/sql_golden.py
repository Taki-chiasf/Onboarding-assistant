"""Golden evaluation set for text-to-SQL.

Cases are hand-authored questions mapped to a canonical SELECT over the read
views. Each case is graded two ways: the generated SQL must match a regex
pattern (catches wrong tables/columns/predicates) and, when executed, the
returned rows may be checked by a predicate (catches SQL that runs but answers
the wrong question). Cases apply to the three demo personas so the same set
replays once per department under that persona's row-level security scope.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

RowPredicate = Callable[[list[dict[str, Any]]], bool]

PERSONAS: tuple[tuple[str, str], ...] = (
    ("Engineering", "employee"),
    ("People", "admin"),
    ("Finance", "employee"),
)

DEFAULT_PERSONAS = tuple(dept for dept, _ in PERSONAS)

_TICKET_CATEGORIES = {"it", "hr", "access", "tools"}


def _all_status(expected: str) -> RowPredicate:
    return lambda rows: all(row.get("status") == expected for row in rows)


def _single_column_in(column: str, allowed: set[str]) -> RowPredicate:
    return lambda rows: all(row.get(column) in allowed for row in rows)


@dataclass(frozen=True)
class SqlCase:
    prompt: str
    golden_sql: str
    expected_sql_pattern: str
    expected_rows_predicate: RowPredicate | None = None
    personas: tuple[str, ...] = DEFAULT_PERSONAS


CASES: list[SqlCase] = [
    # org_members
    SqlCase(
        "How many people work here?",
        "SELECT count(*) AS headcount FROM org_members",
        r"count\(\*\).*org_members",
    ),
    SqlCase(
        "Who is in my department?",
        "SELECT name, email FROM org_members",
        r"SELECT name,\s*email FROM org_members",
    ),
    SqlCase(
        "List all managers in the company.",
        "SELECT name FROM org_members WHERE role = 'manager'",
        r"org_members.*role\s*=\s*'manager'",
    ),
    SqlCase(
        "Who are the department leads?",
        "SELECT name, dept FROM org_members WHERE role = 'lead'",
        r"org_members.*role\s*=\s*'lead'",
    ),
    SqlCase(
        "List everyone in the Data team.",
        "SELECT name, email FROM org_members WHERE team = 'Data'",
        r"org_members.*team\s*=\s*'Data'",
    ),
    SqlCase(
        "How many managers are there?",
        "SELECT count(*) AS managers FROM org_members WHERE role = 'manager'",
        r"count\(\*\).*org_members.*role\s*=\s*'manager'",
    ),
    SqlCase(
        "Who works in the Payments team?",
        "SELECT name, email FROM org_members WHERE team = 'Payments'",
        r"org_members.*team\s*=\s*'Payments'",
    ),
    SqlCase(
        "List employees in Finance.",
        "SELECT name, email FROM org_members WHERE dept = 'Finance'",
        r"org_members.*dept\s*=\s*'Finance'",
    ),
    SqlCase(
        "What roles exist in the organization?",
        "SELECT DISTINCT role FROM org_members",
        r"DISTINCT role FROM org_members",
    ),
    SqlCase(
        "Who is on the Brand team?",
        "SELECT name, email FROM org_members WHERE team = 'Brand'",
        r"org_members.*team\s*=\s*'Brand'",
    ),
    # projects
    SqlCase(
        "How many active projects are there?",
        "SELECT count(*) AS active_projects FROM projects WHERE status = 'active'",
        r"count\(\*\).*projects.*status\s*=\s*'active'",
    ),
    SqlCase(
        "List the names of completed projects.",
        "SELECT name FROM projects WHERE status = 'completed'",
        r"projects.*status\s*=\s*'completed'",
    ),
    SqlCase(
        "Which projects are planned?",
        "SELECT name FROM projects WHERE status = 'planned'",
        r"projects.*status\s*=\s*'planned'",
    ),
    SqlCase(
        "How many projects are there in total?",
        "SELECT count(*) AS total_projects FROM projects",
        r"count\(\*\).*FROM projects",
    ),
    SqlCase(
        "Who leads each active project?",
        "SELECT p.name, m.name AS lead FROM projects p "
        "JOIN org_members m ON p.lead_id = m.id WHERE p.status = 'active'",
        r"projects.*JOIN org_members.*lead_id.*status\s*=\s*'active'",
    ),
    SqlCase(
        "How many projects were completed this year?",
        "SELECT count(*) AS completed_this_year FROM projects "
        "WHERE status = 'completed' AND end_date >= '2026-01-01'",
        r"projects.*status\s*=\s*'completed'.*end_date",
    ),
    SqlCase(
        "What statuses can projects have?",
        "SELECT DISTINCT status FROM projects",
        r"DISTINCT status FROM projects",
    ),
    # assets
    SqlCase(
        "How many laptops do we have?",
        "SELECT count(*) AS laptops FROM assets WHERE type = 'laptop'",
        r"count\(\*\).*assets.*type\s*=\s*'laptop'",
    ),
    SqlCase(
        "Which assets are available?",
        "SELECT asset_tag, type, status FROM assets WHERE status = 'available'",
        r"assets.*status\s*=\s*'available'",
        _all_status("available"),
    ),
    SqlCase(
        "How many assets are currently assigned?",
        "SELECT count(*) AS assigned FROM assets WHERE status = 'assigned'",
        r"count\(\*\).*assets.*status\s*=\s*'assigned'",
    ),
    SqlCase(
        "Which phones are in repair?",
        "SELECT asset_tag FROM assets WHERE type = 'phone' AND status = 'repair'",
        r"assets.*type\s*=\s*'phone'.*status\s*=\s*'repair'",
    ),
    SqlCase(
        "What types of assets do we have?",
        "SELECT DISTINCT type FROM assets",
        r"DISTINCT type FROM assets",
    ),
    SqlCase(
        "How many monitors are assigned?",
        "SELECT count(*) AS assigned_monitors FROM assets "
        "WHERE type = 'monitor' AND status = 'assigned'",
        r"count\(\*\).*assets.*type\s*=\s*'monitor'.*status\s*=\s*'assigned'",
    ),
    SqlCase(
        "Which keyboards are available?",
        "SELECT asset_tag FROM assets WHERE type = 'keyboard' AND status = 'available'",
        r"assets.*type\s*=\s*'keyboard'.*status\s*=\s*'available'",
    ),
    # okrs
    SqlCase(
        "How many OKRs are there?",
        "SELECT count(*) AS okr_count FROM okrs",
        r"count\(\*\).*FROM okrs",
    ),
    SqlCase(
        "What is the average OKR progress?",
        "SELECT avg(progress) AS avg_progress FROM okrs",
        r"avg\(progress\).*okrs",
        lambda rows: not rows or 0 <= float(rows[0]["avg_progress"]) <= 100,
    ),
    SqlCase(
        "Which OKRs are less than 50 percent complete?",
        "SELECT objective FROM okrs WHERE progress < 50",
        r"okrs.*progress\s*<\s*50",
    ),
    SqlCase(
        "How many OKRs are in the final quarter?",
        "SELECT count(*) AS q4_okrs FROM okrs WHERE quarter = '2026-Q4'",
        r"count\(\*\).*okrs.*quarter\s*=\s*'2026-Q4'",
    ),
    SqlCase(
        "Who owns the OKRs in my department?",
        "SELECT m.name, o.objective FROM okrs o "
        "JOIN org_members m ON o.owner_id = m.id",
        r"okrs.*JOIN org_members.*owner_id",
    ),
    SqlCase(
        "What objective has the highest progress?",
        "SELECT objective, progress FROM okrs ORDER BY progress DESC LIMIT 1",
        r"okrs.*ORDER BY progress DESC.*LIMIT 1",
    ),
    SqlCase(
        "How many OKRs are fully complete?",
        "SELECT count(*) AS complete FROM okrs WHERE progress = 100",
        r"count\(\*\).*okrs.*progress\s*=\s*100",
    ),
    SqlCase(
        "List the first quarter OKRs.",
        "SELECT objective FROM okrs WHERE quarter = '2026-Q1'",
        r"okrs.*quarter\s*=\s*'2026-Q1'",
    ),
    # tickets
    SqlCase(
        "How many open tickets are there?",
        "SELECT count(*) AS open_tickets FROM tickets WHERE status = 'open'",
        r"count\(\*\).*tickets.*status\s*=\s*'open'",
    ),
    SqlCase(
        "How many tickets are in progress?",
        "SELECT count(*) AS in_progress FROM tickets WHERE status = 'in-progress'",
        r"count\(\*\).*tickets.*status\s*=\s*'in-progress'",
    ),
    SqlCase(
        "Which IT tickets are still open?",
        "SELECT id FROM tickets WHERE category = 'it' AND status = 'open'",
        r"tickets.*category\s*=\s*'it'.*status\s*=\s*'open'",
    ),
    SqlCase(
        "How many HR tickets have been resolved?",
        "SELECT count(*) AS resolved_hr FROM tickets "
        "WHERE category = 'hr' AND status = 'resolved'",
        r"count\(\*\).*tickets.*category\s*=\s*'hr'.*status\s*=\s*'resolved'",
    ),
    SqlCase(
        "What ticket categories exist?",
        "SELECT DISTINCT category FROM tickets",
        r"DISTINCT category FROM tickets",
        _single_column_in("category", _TICKET_CATEGORIES),
    ),
    SqlCase(
        "What is the most common ticket category?",
        "SELECT category, count(*) AS n FROM tickets GROUP BY category ORDER BY n DESC LIMIT 1",
        r"tickets.*GROUP BY category.*ORDER BY n DESC.*LIMIT 1",
    ),
    SqlCase(
        "How many access tickets have been closed?",
        "SELECT count(*) AS closed_access FROM tickets "
        "WHERE category = 'access' AND status = 'closed'",
        r"count\(\*\).*tickets.*category\s*=\s*'access'.*status\s*=\s*'closed'",
    ),
    SqlCase(
        "Which tools tickets are resolved?",
        "SELECT id FROM tickets WHERE category = 'tools' AND status = 'resolved'",
        r"tickets.*category\s*=\s*'tools'.*status\s*=\s*'resolved'",
    ),
]


def build_sql_set() -> list[SqlCase]:
    return list(CASES)
