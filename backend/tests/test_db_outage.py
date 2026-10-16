"""Database-outage behavior: live connections dying must read as 503s.

A configured-but-unavailable database is an operational condition, not an
application error: endpoints report it as 503 with a stable payload, through
the same shared session dependency that already reports an unconfigured
database that way.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import OperationalError

from app.api.admin import get_session_factory
from app.core.config import get_settings
from tests.test_auth import _app_with_env


async def test_db_outage_maps_to_503(monkeypatch: pytest.MonkeyPatch) -> None:
    app, base = _app_with_env(monkeypatch, MOCK_OIDC="1", DEV_PRINCIPAL_ROLE="admin")

    def broken_factory() -> None:
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    app.dependency_overrides[get_session_factory] = broken_factory
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=base) as c:
            resp = await c.get("/api/admin/ingest")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 503
    assert resp.json() == {"detail": "database is not available"}
    get_settings.cache_clear()
