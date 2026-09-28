"""Deterministic seed data for the demo organization.

Generates a synthetic company (people, projects, assets, objectives, tickets)
and loads it into a dedicated schema, then creates security-invoker views with
row-level security policies and grants them to a read-only role used by the
query layer. The same seed always produces the same data.
"""

from __future__ import annotations

import argparse
import logging
import os
import uuid
from datetime import UTC, timedelta
from typing import Any

from faker import Faker
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

logger = logging.getLogger(__name__)

SEED = 20260920
ORG_SCHEMA = "org"
READONLY_ROLE = "app_readonly"

DEPARTMENTS: dict[str, list[str]] = {
    "Engineering": ["Platform", "Payments", "Data", "Infra"],
    "People": ["Recruiting", "HR Ops"],
    "Finance": ["Accounting", "FP&A"],
    "Sales": ["Enterprise", "SMB"],
    "Marketing": ["Brand", "Demand Gen"],
    "Design": ["Product Design"],
    "Support": ["Customer Support"],
    "Legal": ["Compliance"],
}

ASSET_TYPES = ["laptop", "monitor", "phone", "keyboard", "dock"]
ASSET_STATUSES = ["assigned", "available", "repair"]
PROJECT_STATUSES = ["active", "completed", "planned"]
TICKET_CATEGORIES = ["it", "hr", "access", "tools"]
TICKET_STATUSES = ["open", "in-progress", "resolved", "closed"]
QUARTERS = ["2026-Q1", "2026-Q2", "2026-Q3", "2026-Q4"]


def _uuid(kind: str, index: int) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"seed:{kind}:{index}")


def _slug(value: str) -> str:
    return "".join(char for char in value.lower() if char.isalnum())


def make_faker() -> Faker:
    Faker.seed(SEED)
    return Faker()


def generate_org_members(fake: Faker) -> list[dict[str, Any]]:
    members: list[dict[str, Any]] = []
    fake.unique.clear()
    index = 0
    for dept, teams in DEPARTMENTS.items():
        roles = ["lead"] + ["manager"] + ["employee"] * 13
        for position, role in enumerate(roles):
            first = fake.unique.first_name()
            last = fake.unique.last_name()
            members.append(
                {
                    "id": _uuid("member", index),
                    "name": f"{first} {last}",
                    "email": f"{_slug(first)}.{_slug(last)}@{dept.lower()}.demo.example",
                    "dept": dept,
                    "team": teams[position % len(teams)],
                    "role": role,
                    "manager_id": None,
                }
            )
            index += 1

    dept_manager = {m["dept"]: m["id"] for m in members if m["role"] == "manager"}
    for member in members:
        if member["role"] == "employee":
            member["manager_id"] = dept_manager[member["dept"]]
    return members


def generate_projects(fake: Faker, members: list[dict[str, Any]]) -> list[dict[str, Any]]:
    leads = [m for m in members if m["role"] in ("lead", "manager")]
    projects: list[dict[str, Any]] = []
    for i in range(30):
        lead = leads[i % len(leads)]
        start = fake.date_between(start_date="-1y", end_date="today")
        status = fake.random_element(PROJECT_STATUSES)
        end = start + timedelta(days=fake.random_int(30, 180)) if status == "completed" else None
        projects.append(
            {
                "id": _uuid("project", i),
                "name": fake.catch_phrase(),
                "lead_id": lead["id"],
                "status": status,
                "start_date": start,
                "end_date": end,
            }
        )
    return projects


def generate_assets(fake: Faker, members: list[dict[str, Any]]) -> list[dict[str, Any]]:
    emails = [m["email"] for m in members]
    assets: list[dict[str, Any]] = []
    for i in range(200):
        status = fake.random_element(ASSET_STATUSES)
        assets.append(
            {
                "asset_tag": f"AST-{i:04d}",
                "assignee_email": fake.random_element(emails) if status == "assigned" else None,
                "type": fake.random_element(ASSET_TYPES),
                "status": status,
            }
        )
    return assets


def generate_okrs(fake: Faker, members: list[dict[str, Any]]) -> list[dict[str, Any]]:
    okrs: list[dict[str, Any]] = []
    for i in range(60):
        okrs.append(
            {
                "id": _uuid("okr", i),
                "owner_id": fake.random_element(members)["id"],
                "objective": fake.sentence(nb_words=8),
                "quarter": fake.random_element(QUARTERS),
                "progress": fake.random_int(0, 100),
            }
        )
    return okrs


def generate_tickets(fake: Faker, members: list[dict[str, Any]]) -> list[dict[str, Any]]:
    emails = [m["email"] for m in members]
    tickets: list[dict[str, Any]] = []
    for i in range(150):
        tickets.append(
            {
                "id": _uuid("ticket", i),
                "requester_email": fake.random_element(emails),
                "category": fake.random_element(TICKET_CATEGORIES),
                "status": fake.random_element(TICKET_STATUSES),
                "created_at": fake.date_time_between(start_date="-3M", end_date="now", tzinfo=UTC),
            }
        )
    return tickets


def _create_org_tables(conn: Connection) -> None:
    conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {ORG_SCHEMA}"))
    conn.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS {ORG_SCHEMA}.org_members (
                id UUID PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                dept TEXT NOT NULL,
                team TEXT NOT NULL,
                role TEXT NOT NULL,
                manager_id UUID
            )
            """
        )
    )
    conn.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS {ORG_SCHEMA}.projects (
                id UUID PRIMARY KEY,
                name TEXT NOT NULL,
                lead_id UUID,
                status TEXT NOT NULL,
                start_date DATE,
                end_date DATE
            )
            """
        )
    )
    conn.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS {ORG_SCHEMA}.assets (
                asset_tag TEXT PRIMARY KEY,
                assignee_email TEXT,
                type TEXT NOT NULL,
                status TEXT NOT NULL
            )
            """
        )
    )
    conn.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS {ORG_SCHEMA}.okrs (
                id UUID PRIMARY KEY,
                owner_id UUID,
                objective TEXT NOT NULL,
                quarter TEXT NOT NULL,
                progress INTEGER NOT NULL
            )
            """
        )
    )
    conn.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS {ORG_SCHEMA}.tickets (
                id UUID PRIMARY KEY,
                requester_email TEXT,
                category TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL
            )
            """
        )
    )


def _ensure_readonly_role(conn: Connection) -> None:
    conn.execute(
        text(
            f"""
            DO $$ BEGIN
                IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{READONLY_ROLE}') THEN
                    CREATE ROLE {READONLY_ROLE};
                END IF;
            END $$;
            """
        )
    )
    conn.execute(text(f"GRANT USAGE ON SCHEMA {ORG_SCHEMA} TO {READONLY_ROLE}"))
    conn.execute(text(f"GRANT SELECT ON ALL TABLES IN SCHEMA {ORG_SCHEMA} TO {READONLY_ROLE}"))
    # The access policies read the caller's context from transaction-local
    # settings. A query running as the read-only role must not be able to
    # rewrite that context before the policies are evaluated, so the function
    # that writes it is revoked here too. PUBLIC carries an implicit execute
    # grant on every built-in, which a role-level revoke alone does not remove,
    # so both the role and PUBLIC are covered.
    set_config = "pg_catalog.set_config(text, text, boolean)"
    conn.execute(text(f"REVOKE EXECUTE ON FUNCTION {set_config} FROM {READONLY_ROLE}"))
    conn.execute(text(f"REVOKE EXECUTE ON FUNCTION {set_config} FROM PUBLIC"))


_READ_VIEWS: dict[str, str] = {
    "org_members": "SELECT id, name, email, dept, team, role, manager_id FROM org.org_members",
    "projects": "SELECT id, name, lead_id, status, start_date, end_date FROM org.projects",
    "assets": "SELECT asset_tag, assignee_email, type, status FROM org.assets",
    "okrs": "SELECT id, owner_id, objective, quarter, progress FROM org.okrs",
    "tickets": "SELECT id, requester_email, category, status, created_at FROM org.tickets",
}


def _dept_setting() -> str:
    # A pooled connection that once ran a scoped query keeps an empty
    # session-level value for a custom setting: Postgres reverts the
    # transaction-local value to the empty string rather than unsetting it.
    # An empty string must therefore count as "no context" wherever the
    # setting gates access, or a warm connection would pass the guard.
    return "NULLIF(current_setting('app.principal_dept', true), '')"


def _role_setting() -> str:
    return "NULLIF(current_setting('app.principal_role', true), '')"


# Which column on each read view points at a department-owned member, and
# whether that reference is the member id or email.
_OWNER_COLUMNS: dict[str, tuple[str, str]] = {
    "projects": ("lead_id", "id"),
    "assets": ("assignee_email", "email"),
    "okrs": ("owner_id", "id"),
    "tickets": ("requester_email", "email"),
}


def select_policy(table: str) -> str:
    """Return the deny-by-default SELECT predicate for a read view.

    A caller with no department context sees nothing. Admins see every row.
    Unassigned rows (a null owner) are shared demo data: visible to any caller
    with a department context, but never without one, so a context-less read
    cannot fall through to them.
    """
    is_admin = f"{_role_setting()} = 'admin'"
    dept = _dept_setting()
    if table == "org_members":
        return f"{is_admin} OR dept = {dept}"
    owner_column, member_key = _OWNER_COLUMNS[table]
    has_context = f"{dept} IS NOT NULL"
    return (
        f"{is_admin} OR ({has_context} AND ({owner_column} IS NULL OR {owner_column} IN "
        f"(SELECT {member_key} FROM {ORG_SCHEMA}.org_members WHERE dept = {dept})))"
    )


def _create_read_views(conn: Connection) -> None:
    """Create security-invoker views and row-level security policies.

    The views run with the invoker's privileges so row-level security on the
    base tables is applied to the calling role. Policies are deny-by-default:
    without a department setting (or an admin role) no rows are visible.
    """
    for name, select in _READ_VIEWS.items():
        conn.execute(text(f"DROP VIEW IF EXISTS public.{name} CASCADE"))
        conn.execute(text(f"CREATE VIEW public.{name} WITH (security_invoker = true) AS {select}"))
        conn.execute(text(f"GRANT SELECT ON public.{name} TO {READONLY_ROLE}"))

    for table in _READ_VIEWS:
        conn.execute(text(f"ALTER TABLE {ORG_SCHEMA}.{table} ENABLE ROW LEVEL SECURITY"))
        conn.execute(text(f"ALTER TABLE {ORG_SCHEMA}.{table} FORCE ROW LEVEL SECURITY"))
        conn.execute(text(f"DROP POLICY IF EXISTS {table}_select ON {ORG_SCHEMA}.{table}"))
        conn.execute(
            text(
                f"CREATE POLICY {table}_select ON {ORG_SCHEMA}.{table} "
                f"FOR SELECT USING ({select_policy(table)})"
            )
        )


def _reset_conversations(conn: Connection) -> None:
    exists = conn.execute(text("SELECT to_regclass('public.conversations')")).scalar()
    if exists:
        conn.execute(
            text("TRUNCATE TABLE public.conversations, public.messages, public.feedback CASCADE")
        )


def seed(engine: Engine, *, reset: bool = False) -> dict[str, int]:
    fake = make_faker()
    members = generate_org_members(fake)
    projects = generate_projects(fake, members)
    assets = generate_assets(fake, members)
    okrs = generate_okrs(fake, members)
    tickets = generate_tickets(fake, members)

    with engine.begin() as conn:
        _create_org_tables(conn)
        conn.execute(
            text(
                "TRUNCATE TABLE "
                f"{ORG_SCHEMA}.tickets, {ORG_SCHEMA}.okrs, {ORG_SCHEMA}.assets, "
                f"{ORG_SCHEMA}.projects, {ORG_SCHEMA}.org_members CASCADE"
            )
        )
        conn.execute(
            text(
                f"INSERT INTO {ORG_SCHEMA}.org_members "
                "(id, name, email, dept, team, role, manager_id) "
                "VALUES (:id, :name, :email, :dept, :team, :role, :manager_id)"
            ),
            members,
        )
        conn.execute(
            text(
                f"INSERT INTO {ORG_SCHEMA}.projects "
                "(id, name, lead_id, status, start_date, end_date) "
                "VALUES (:id, :name, :lead_id, :status, :start_date, :end_date)"
            ),
            projects,
        )
        conn.execute(
            text(
                f"INSERT INTO {ORG_SCHEMA}.assets "
                "(asset_tag, assignee_email, type, status) "
                "VALUES (:asset_tag, :assignee_email, :type, :status)"
            ),
            assets,
        )
        conn.execute(
            text(
                f"INSERT INTO {ORG_SCHEMA}.okrs "
                "(id, owner_id, objective, quarter, progress) "
                "VALUES (:id, :owner_id, :objective, :quarter, :progress)"
            ),
            okrs,
        )
        conn.execute(
            text(
                f"INSERT INTO {ORG_SCHEMA}.tickets "
                "(id, requester_email, category, status, created_at) "
                "VALUES (:id, :requester_email, :category, :status, :created_at)"
            ),
            tickets,
        )
        _ensure_readonly_role(conn)
        _create_read_views(conn)

    if reset:
        with engine.begin() as conn:
            _reset_conversations(conn)

    return {
        "members": len(members),
        "projects": len(projects),
        "assets": len(assets),
        "okrs": len(okrs),
        "tickets": len(tickets),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the demo organization")
    parser.add_argument("--reset", action="store_true", help="also clear conversation history")
    parser.add_argument("--database-url", help="override DATABASE_URL")
    args = parser.parse_args()

    database_url = args.database_url or os.environ["DATABASE_URL"]
    engine = create_engine(database_url)
    counts = seed(engine, reset=args.reset)
    engine.dispose()
    logger.info("seeded: %s", counts)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
