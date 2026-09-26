import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.auth.mock_oidc import encode_principal, make_serializer
from app.auth.principal import Principal
from app.core.config import get_settings
from app.main import create_app


@pytest.fixture(autouse=True)
def _isolate_oidc_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OIDC_ISSUER", raising=False)
    monkeypatch.delenv("OIDC_CLIENT_ID", raising=False)


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


def _app_with_env(monkeypatch: pytest.MonkeyPatch, **env: str) -> tuple[FastAPI, str]:
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("REDIS_URL", "")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    return create_app(), "http://test"


async def test_auth_mode_static(monkeypatch: pytest.MonkeyPatch) -> None:
    app, base = _app_with_env(monkeypatch, MOCK_OIDC="1")
    async with AsyncClient(transport=ASGITransport(app=app), base_url=base) as c:
        assert (await c.get("/auth/mode")).json() == {"mode": "static", "oidc": None}
    get_settings.cache_clear()


async def test_auth_mode_persona(monkeypatch: pytest.MonkeyPatch) -> None:
    app, base = _app_with_env(monkeypatch, MOCK_OIDC="2")
    async with AsyncClient(transport=ASGITransport(app=app), base_url=base) as c:
        assert (await c.get("/auth/mode")).json()["mode"] == "persona"
    get_settings.cache_clear()


async def test_auth_mode_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    app, base = _app_with_env(monkeypatch, MOCK_OIDC="0")
    async with AsyncClient(transport=ASGITransport(app=app), base_url=base) as c:
        assert (await c.get("/auth/mode")).json()["mode"] == "disabled"
    get_settings.cache_clear()


async def test_auth_mode_oidc_returns_public_config(monkeypatch: pytest.MonkeyPatch) -> None:
    app, base = _app_with_env(
        monkeypatch,
        MOCK_OIDC="0",
        OIDC_ISSUER="https://tenant.example.auth0.com/",
        OIDC_CLIENT_ID="client-123",
        OIDC_AUDIENCE="https://api.example",
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url=base) as c:
        body = (await c.get("/auth/mode")).json()
    assert body["mode"] == "oidc"
    assert body["oidc"]["client_id"] == "client-123"
    assert body["oidc"]["authorize_url"] == "https://tenant.example.auth0.com/authorize"
    get_settings.cache_clear()


async def test_session_cookie_is_honored_when_mock_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, base = _app_with_env(monkeypatch, MOCK_OIDC="0", SESSION_SECRET="test-secret")
    settings = get_settings()
    principal = Principal(
        sub="oidc|u1", email="ada@engineering.demo.example", dept="Engineering", role="employee"
    )
    token = encode_principal(make_serializer(settings.session_secret), principal)
    async with AsyncClient(transport=ASGITransport(app=app), base_url=base) as c:
        c.cookies.set("session", token)
        resp = await c.get("/auth/dev/me")
        assert resp.status_code == 200
        assert resp.json()["sub"] == "oidc|u1"
    get_settings.cache_clear()


async def test_persona_login_is_disabled_when_oidc_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, base = _app_with_env(
        monkeypatch,
        MOCK_OIDC="2",
        OIDC_ISSUER="https://tenant.example.auth0.com/",
        OIDC_CLIENT_ID="client-123",
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url=base) as c:
        personas = await c.get("/auth/dev/personas")
        assert personas.json() == []
        login = await c.post(
            "/auth/dev/login",
            json={
                "sub": "jordan-lee",
                "email": "jordan.lee@people.demo.example",
                "dept": "People",
                "role": "admin",
            },
        )
        assert login.status_code == 403
    get_settings.cache_clear()
