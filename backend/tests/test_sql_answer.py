from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from app.auth.principal import Principal
from app.llm.fake import FakeProvider
from app.llm.models import ModelConfig
from app.llm.provider import ChatProvider
from app.text_to_sql import answer as answer_mod
from app.text_to_sql.answer import NO_MATCHING_RECORDS, SqlAnswerer, format_row_packet
from app.text_to_sql.executor import SqlExecutor, SqlResult


def _principal() -> Principal:
    return Principal(sub="alex", email="alex@example.com", dept="Engineering", role="employee")


def _models() -> ModelConfig:
    return ModelConfig(
        provider="fake",
        models={"sql_builder": "fake-builder", "grounding": "fake-grounding"},
    )


class _FakeExecutor:
    def __init__(self, result: SqlResult) -> None:
        self._result = result
        self.calls: list[str] = []

    async def execute(
        self, sql: str, *, dept: str, role: str, principal: str, trace_id: str | None = None
    ) -> SqlResult:
        self.calls.append(sql)
        return self._result


class _FakeSession:
    def __init__(self, added: list[Any]) -> None:
        self.added = added
        self.committed = 0

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.committed += 1

    async def execute(self, statement: object, params: dict[str, Any] | None = None) -> None:
        return None

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False


def _patch_session_factory(monkeypatch: pytest.MonkeyPatch, added: list[Any]) -> None:
    def factory() -> _FakeSession:
        return _FakeSession(added)

    monkeypatch.setattr(answer_mod, "async_sessionmaker", lambda engine, expire_on_commit: factory)


def _answerer(provider: FakeProvider, result: SqlResult) -> SqlAnswerer:
    return SqlAnswerer(
        MagicMock(),
        cast(ChatProvider, provider),
        _models(),
        cast(SqlExecutor, _FakeExecutor(result)),
    )


def test_format_row_packet_renders_table() -> None:
    result = SqlResult(
        columns=["id", "name"], rows=[(1, "Ada"), (2, None)], truncated=False, latency_ms=0
    )
    packet = format_row_packet(result)

    assert "| id | name |" in packet
    assert "| 1 | Ada |" in packet
    assert "| 2 |  |" in packet


async def test_stream_emits_sql_and_grounded_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    added: list[Any] = []
    _patch_session_factory(monkeypatch, added)
    provider = FakeProvider(
        responses={
            "fake-builder": "SELECT id, name FROM org_members",
            "fake-grounding": "Ada is here",
        }
    )
    result = SqlResult(columns=["id", "name"], rows=[(1, "Ada")], truncated=False, latency_ms=7)
    answerer = _answerer(provider, result)

    events = [e async for e in answerer.stream("who is in my dept?", _principal())]

    assert [e["event"] for e in events] == ["sql", "token", "token", "token", "done"]
    sql = events[0]["data"]
    assert sql["sql"] == "SELECT id, name FROM org_members"
    assert sql["row_count"] == 1
    assert sql["latency_ms"] == 7
    done = events[-1]["data"]
    assert done["answer"] == "Ada is here"
    assert done["sql"] == "SELECT id, name FROM org_members"
    assert done["row_count"] == 1
    assert done["sql_prompt_version"] == "sql_builder.v1"
    assert done["prompt_version"] == "sql_summarize.v1"

    assistant = [obj for obj in added if getattr(obj, "role", None) == "assistant"]
    assert len(assistant) == 1
    assert assistant[0].content == "Ada is here"
    assert assistant[0].detail == {
        "sql": {
            "sql": "SELECT id, name FROM org_members",
            "row_count": 1,
            "truncated": False,
            "latency_ms": 7,
        }
    }


async def test_stream_empty_rows_uses_deterministic_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    added: list[Any] = []
    _patch_session_factory(monkeypatch, added)
    provider = FakeProvider(responses={"fake-builder": "SELECT id FROM org_members"})
    result = SqlResult(columns=["id"], rows=[], truncated=False, latency_ms=3)
    answerer = _answerer(provider, result)

    events = [e async for e in answerer.stream("who is in my dept?", _principal())]

    assert [e["event"] for e in events] == ["sql", "token", "done"]
    assert events[1]["data"]["text"] == NO_MATCHING_RECORDS
    assert events[-1]["data"]["answer"] == NO_MATCHING_RECORDS


async def test_stream_persists_the_router_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    added: list[Any] = []
    _patch_session_factory(monkeypatch, added)
    provider = FakeProvider(
        responses={"fake-builder": "SELECT id FROM org_members", "fake-grounding": "ok"}
    )
    result = SqlResult(columns=["id"], rows=[(1,)], truncated=False, latency_ms=1)
    answerer = _answerer(provider, result)
    route = {"intent": "text-to-sql", "route_source": "router", "router_confidence": 0.95}

    _ = [e async for e in answerer.stream("q", _principal(), route=route)]

    assistant = [obj for obj in added if getattr(obj, "role", None) == "assistant"]
    assert assistant[0].detail is not None
    assert assistant[0].detail["route"] == route
    assert assistant[0].detail["sql"]["sql"] == "SELECT id FROM org_members"


async def test_stream_records_cost_for_builder_and_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    added: list[Any] = []
    _patch_session_factory(monkeypatch, added)
    provider = FakeProvider(
        responses={"fake-builder": "SELECT id FROM org_members", "fake-grounding": "ok"}
    )
    result = SqlResult(columns=["id"], rows=[(1,)], truncated=False, latency_ms=0)
    answerer = _answerer(provider, result)

    events = [e async for e in answerer.stream("q", _principal())]
    assert events[-1]["event"] == "done"

    assistant = [obj for obj in added if getattr(obj, "role", None) == "assistant"]
    assert assistant[0].cost_usd is not None
