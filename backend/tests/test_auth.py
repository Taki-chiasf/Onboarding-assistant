import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.main import create_app


async def test_me_returns_static_principal(client: AsyncClient) -> None:
    resp = await client.get("/auth/dev/me")
    assert resp.status_code == 200
    body = resp.json()
    assert body["sub"] == "test-user"
    assert body["dept"] == "Engineering"
    assert body["role"] == "employee"


async def test_personas_empty_in_static_mode(client: AsyncClient) -> None:
    resp = await client.get("/auth/dev/personas")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_persona_login_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_OIDC", "2")
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("REDIS_URL", "")
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    get_settings.cache_clear()

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        personas = await c.get("/auth/dev/personas")
        assert personas.status_code == 200
        assert len(personas.json()) == 3

        unauth = await c.get("/auth/dev/me")
        assert unauth.status_code == 401

        persona = personas.json()[0]
        login = await c.post("/auth/dev/login", json=persona)
        assert login.status_code == 200
        assert c.cookies.get("session") is not None

        me = await c.get("/auth/dev/me")
        assert me.status_code == 200
        assert me.json()["sub"] == persona["sub"]

        logout = await c.post("/auth/dev/logout")
        assert logout.status_code == 200
        me_after = await c.get("/auth/dev/me")
        assert me_after.status_code == 401

    get_settings.cache_clear()


async def test_me_unauthenticated_when_auth_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_OIDC", "0")
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("REDIS_URL", "")
    get_settings.cache_clear()

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get("/auth/dev/me")
        assert resp.status_code == 401

    get_settings.cache_clear()


async def test_login_disabled_outside_persona_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_OIDC", "1")
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("REDIS_URL", "")
    get_settings.cache_clear()

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.post(
            "/auth/dev/login",
            json={
                "sub": "x",
                "email": "x@example.com",
                "dept": "Engineering",
                "role": "employee",
            },
        )
        assert resp.status_code == 403

    get_settings.cache_clear()
