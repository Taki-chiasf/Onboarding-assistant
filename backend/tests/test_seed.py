from typing import Any

import pytest

from scripts.seed import (
    ASSET_STATUSES,
    ASSET_TYPES,
    DEPARTMENTS,
    PROJECT_STATUSES,
    TICKET_CATEGORIES,
    generate_assets,
    generate_okrs,
    generate_org_members,
    generate_projects,
    generate_tickets,
    make_faker,
    select_policy,
)


def _members() -> list[dict[str, Any]]:
    return generate_org_members(make_faker())


def test_members_are_deterministic() -> None:
    first = [m["email"] for m in _members()]
    second = [m["email"] for m in _members()]
    assert first == second


def test_member_counts_and_departments() -> None:
    members = _members()
    assert len(members) == 120
    by_dept: dict[str, int] = {}
    for member in members:
        by_dept[member["dept"]] = by_dept.get(member["dept"], 0) + 1
    assert set(by_dept) == set(DEPARTMENTS)
    assert all(count == 15 for count in by_dept.values())


def test_member_roles_per_department() -> None:
    members = _members()
    for dept in DEPARTMENTS:
        roles = [m["role"] for m in members if m["dept"] == dept]
        assert roles.count("lead") == 1
        assert roles.count("manager") == 1
        assert roles.count("employee") == 13


def test_manager_links_are_intra_department() -> None:
    members = _members()
    by_id = {m["id"]: m for m in members}
    for member in members:
        if member["role"] == "employee":
            assert member["manager_id"] is not None
            assert by_id[member["manager_id"]]["dept"] == member["dept"]
        else:
            assert member["manager_id"] is None


def test_projects_reference_valid_leads() -> None:
    fake = make_faker()
    members = generate_org_members(fake)
    projects = generate_projects(fake, members)
    member_ids = {m["id"] for m in members}
    assert len(projects) == 30
    for project in projects:
        assert project["lead_id"] in member_ids
        assert project["status"] in PROJECT_STATUSES


def test_assets_are_unique_and_assigned() -> None:
    fake = make_faker()
    members = generate_org_members(fake)
    assets = generate_assets(fake, members)
    member_emails = {m["email"] for m in members}
    tags = [a["asset_tag"] for a in assets]
    assert len(assets) == 200
    assert len(set(tags)) == 200
    for asset in assets:
        assert asset["type"] in ASSET_TYPES
        assert asset["status"] in ASSET_STATUSES
        if asset["status"] == "assigned":
            assert asset["assignee_email"] in member_emails


def test_okrs_reference_valid_owners() -> None:
    fake = make_faker()
    members = generate_org_members(fake)
    okrs = generate_okrs(fake, members)
    member_ids = {m["id"] for m in members}
    assert len(okrs) == 60
    for okr in okrs:
        assert okr["owner_id"] in member_ids
        assert 0 <= okr["progress"] <= 100


def test_tickets_reference_valid_requesters() -> None:
    fake = make_faker()
    members = generate_org_members(fake)
    tickets = generate_tickets(fake, members)
    member_emails = {m["email"] for m in members}
    assert len(tickets) == 150
    for ticket in tickets:
        assert ticket["requester_email"] in member_emails
        assert ticket["category"] in TICKET_CATEGORIES


OWNER_TABLES = ("projects", "assets", "okrs", "tickets")


def test_select_policy_requires_context_for_unassigned_rows() -> None:
    """A null owner must not be visible without a department context."""
    for table in OWNER_TABLES:
        policy = select_policy(table)
        assert "IS NULL" in policy
        assert "NULLIF(current_setting('app.principal_dept', true), '') IS NOT NULL" in policy


def test_select_policy_treats_an_empty_setting_as_no_context() -> None:
    """A warm pooled connection keeps an empty-string department setting, which
    must not count as a context."""
    for table in OWNER_TABLES + ("org_members",):
        policy = select_policy(table)
        assert "current_setting('app.principal_dept', true), '')" in policy


def test_select_policy_grants_unassigned_rows_only_with_context() -> None:
    for table in OWNER_TABLES:
        policy = select_policy(table)
        # The share branch is guarded by the context check, so a bare
        # top-level `<owner> IS NULL` cannot leak rows without context.
        assert "IS NOT NULL AND (" in policy


def test_select_policy_for_members_is_department_scoped() -> None:
    assert select_policy("org_members") == (
        "NULLIF(current_setting('app.principal_role', true), '') = 'admin' "
        "OR dept = NULLIF(current_setting('app.principal_dept', true), '')"
    )


def test_select_policy_rejects_unknown_table() -> None:
    with pytest.raises(KeyError):
        select_policy("secrets")
