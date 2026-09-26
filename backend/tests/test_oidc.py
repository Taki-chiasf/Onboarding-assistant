import json
import time
from collections.abc import Callable
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient

from app.api.oidc import get_oidc_service
from app.auth.claims import ClaimError, principal_from_claims
from app.auth.oidc import (
    IdTokenError,
    IdTokenVerifier,
    OidcConfig,
    OidcService,
    exchange_code,
    load_oidc_config,
)
from app.core.config import Settings, get_settings
from app.main import create_app

ISSUER = "https://tenant.example.auth0.com/"
CLIENT_ID = "client-123"


def _keypair() -> tuple[bytes, dict[str, Any]]:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key()))
    jwk.update({"kid": "test-key", "use": "sig", "alg": "RS256"})
    return private_pem, {"keys": [jwk]}


def _token(
    private_pem: bytes,
    *,
    iss: str = ISSUER,
    aud: str = CLIENT_ID,
    sub: str = "auth0|u1",
    dept: str = "Engineering",
    role: str = "employee",
    email: str = "ada@engineering.demo.example",
    expires_in: int = 300,
    kid: str = "test-key",
    extra: dict[str, Any] | None = None,
) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": iss,
        "aud": aud,
        "sub": sub,
        "exp": now + expires_in,
        "iat": now,
        "dept": dept,
        "role": role,
        "email": email,
    }
    claims.update(extra or {})
    return jwt.encode(claims, private_pem, algorithm="RS256", headers={"kid": kid})


def _config(**overrides: Any) -> OidcConfig:
    defaults: dict[str, Any] = {
        "issuer": ISSUER,
        "client_id": CLIENT_ID,
        "client_secret": "",
        "audience": "https://api.example",
        "scope": "openid profile email",
        "authorize_url": f"{ISSUER}authorize",
        "token_url": f"{ISSUER}oauth/token",
        "jwks_url": f"{ISSUER}.well-known/jwks.json",
        "dept_claim": "dept",
        "role_claim": "role",
        "email_claim": "email",
        "allowed_departments": (),
        "allowed_roles": ("employee", "admin"),
    }
    defaults.update(overrides)
    return OidcConfig(**defaults)


def _verifier(jwks: dict[str, Any], **overrides: Any) -> IdTokenVerifier:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=jwks)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return IdTokenVerifier(_config(**overrides), http=client)


# --- claim mapping ----------------------------------------------------------


def _claims(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "sub": "auth0|u1",
        "email": "ada@engineering.demo.example",
        "dept": "Engineering",
        "role": "employee",
    }
    base.update(overrides)
    return base


def test_maps_claims_to_principal() -> None:
    result = principal_from_claims(
        _claims(), dept_claim="dept", role_claim="role", email_claim="email"
    )
    assert result.principal.sub == "auth0|u1"
    assert result.principal.dept == "Engineering"
    assert result.principal.role == "employee"
    assert result.drift == ()


def test_missing_subject_is_rejected() -> None:
    with pytest.raises(ClaimError):
        principal_from_claims(
            _claims(sub=None), dept_claim="dept", role_claim="role", email_claim="email"
        )


def test_missing_department_is_rejected() -> None:
    with pytest.raises(ClaimError):
        principal_from_claims(
            _claims(dept=None), dept_claim="dept", role_claim="role", email_claim="email"
        )


def test_unmapped_department_is_rejected_when_allowlisted() -> None:
    with pytest.raises(ClaimError):
        principal_from_claims(
            _claims(dept="Shadow"),
            dept_claim="dept",
            role_claim="role",
            email_claim="email",
            allowed_departments=("Engineering", "Finance"),
        )


def test_unknown_role_degrades_and_reports_drift() -> None:
    result = principal_from_claims(
        _claims(role="superuser"), dept_claim="dept", role_claim="role", email_claim="email"
    )
    assert result.principal.role == "employee"
    assert result.drift and "superuser" in result.drift[0]


def test_missing_role_defaults_and_reports_drift() -> None:
    result = principal_from_claims(
        _claims(role=None), dept_claim="dept", role_claim="role", email_claim="email"
    )
    assert result.principal.role == "employee"
    assert result.drift


def test_namespaced_claims_and_role_list() -> None:
    claims = {
        "sub": "auth0|u2",
        "https://tenant.example/dept": "Finance",
        "https://tenant.example/roles": ["admin", "employee"],
        "email": "priya@finance.demo.example",
    }
    result = principal_from_claims(
        claims,
        dept_claim="https://tenant.example/dept",
        role_claim="https://tenant.example/roles",
        email_claim="email",
    )
    assert result.principal.dept == "Finance"
    assert result.principal.role == "admin"


# --- id token verification --------------------------------------------------


async def test_verifier_accepts_valid_token() -> None:
    private_pem, jwks = _keypair()
    verifier = _verifier(jwks)
    claims = await verifier.verify(_token(private_pem))
    assert claims["sub"] == "auth0|u1"
    assert claims["dept"] == "Engineering"


async def test_verifier_rejects_wrong_audience() -> None:
    private_pem, jwks = _keypair()
    verifier = _verifier(jwks)
    with pytest.raises(IdTokenError):
        await verifier.verify(_token(private_pem, aud="other-client"))


async def test_verifier_rejects_wrong_issuer() -> None:
    private_pem, jwks = _keypair()
    verifier = _verifier(jwks)
    with pytest.raises(IdTokenError):
        await verifier.verify(_token(private_pem, iss="https://evil.example/"))


async def test_verifier_rejects_expired_token() -> None:
    private_pem, jwks = _keypair()
    verifier = _verifier(jwks)
    with pytest.raises(IdTokenError):
        await verifier.verify(_token(private_pem, expires_in=-10))


async def test_verifier_rejects_unknown_key_id() -> None:
    private_pem, jwks = _keypair()
    verifier = _verifier(jwks)
    with pytest.raises(IdTokenError):
        await verifier.verify(_token(private_pem, kid="rotated-away"))


async def test_verifier_caches_jwks() -> None:
    private_pem, jwks = _keypair()
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=jwks)

    verifier = IdTokenVerifier(
        _config(), http=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    await verifier.verify(_token(private_pem))
    await verifier.verify(_token(private_pem))
    assert calls["n"] == 1


# --- exchange + service -----------------------------------------------------


async def test_exchange_code_posts_pkce_grant() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = dict(httpx.QueryParams(request.content.decode()))
        return httpx.Response(200, json={"id_token": "x", "access_token": "y"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    tokens = await exchange_code(
        _config(), code="code-1", code_verifier="verifier-1", redirect_uri="http://cb", http=client
    )
    assert tokens["id_token"] == "x"
    assert seen["body"]["grant_type"] == "authorization_code"
    assert seen["body"]["code_verifier"] == "verifier-1"
    assert "client_secret" not in seen["body"]


async def test_service_authenticates_code_and_maps_principal() -> None:
    private_pem, jwks = _keypair()
    token = _token(private_pem, role="admin", dept="People", sub="auth0|hr")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth/token"):
            return httpx.Response(200, json={"id_token": token})
        return httpx.Response(200, json=jwks)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = OidcService(
        config=_config(), verifier=IdTokenVerifier(_config(), http=client), http=client
    )
    result = await service.authenticate(code="c", code_verifier="v", redirect_uri="http://cb")
    assert result.principal.sub == "auth0|hr"
    assert result.principal.role == "admin"


async def test_service_rejects_missing_id_token() -> None:
    private_pem, jwks = _keypair()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth/token"):
            return httpx.Response(200, json={"access_token": "y"})
        return httpx.Response(200, json=jwks)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = OidcService(
        config=_config(), verifier=IdTokenVerifier(_config(), http=client), http=client
    )
    with pytest.raises(IdTokenError):
        await service.authenticate(code="c", code_verifier="v", redirect_uri="http://cb")


# --- config loading ---------------------------------------------------------


def test_load_config_requires_issuer_and_client() -> None:
    assert load_oidc_config(Settings(oidc_issuer="", oidc_client_id="")) is None
    assert load_oidc_config(Settings(oidc_issuer=ISSUER, oidc_client_id="")) is None


def test_load_config_derives_provider_urls() -> None:
    config = load_oidc_config(Settings(oidc_issuer=ISSUER, oidc_client_id=CLIENT_ID))
    assert config is not None
    assert config.authorize_url == f"{ISSUER}authorize"
    assert config.token_url == f"{ISSUER}oauth/token"
    assert config.jwks_url == f"{ISSUER}.well-known/jwks.json"
    assert config.allowed_roles == ("employee", "admin")


# --- endpoint ---------------------------------------------------------------


class _FakeService:
    def __init__(self, outcome: Any) -> None:
        self._outcome = outcome

    async def authenticate(self, *, code: str, code_verifier: str, redirect_uri: str) -> Any:
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


def _client_with_service(outcome: Any) -> Callable[[], AsyncClient]:
    app = create_app()
    app.dependency_overrides[get_oidc_service] = lambda: _FakeService(outcome)
    transport = ASGITransport(app=app)
    return lambda: AsyncClient(transport=transport, base_url="http://test")


async def test_exchange_sets_session_cookie_and_returns_principal() -> None:
    from app.auth.claims import ClaimResult
    from app.auth.principal import Principal

    result = ClaimResult(
        principal=Principal(
            sub="auth0|u1",
            email="ada@engineering.demo.example",
            dept="Engineering",
            role="employee",
        )
    )
    factory = _client_with_service(result)
    async with factory() as client:
        resp = await client.post(
            "/auth/oidc/exchange",
            json={"code": "c", "code_verifier": "v", "redirect_uri": "http://cb"},
        )
        assert resp.status_code == 200
        assert resp.json()["sub"] == "auth0|u1"
        assert client.cookies.get("session") is not None


async def test_exchange_rejects_claim_drift_error_as_unauthorized() -> None:
    factory = _client_with_service(ClaimError("missing department"))
    async with factory() as client:
        resp = await client.post(
            "/auth/oidc/exchange",
            json={"code": "c", "code_verifier": "v", "redirect_uri": "http://cb"},
        )
        assert resp.status_code == 401


async def test_exchange_rejects_invalid_token_as_unauthorized() -> None:
    factory = _client_with_service(IdTokenError("bad signature"))
    async with factory() as client:
        resp = await client.post(
            "/auth/oidc/exchange",
            json={"code": "c", "code_verifier": "v", "redirect_uri": "http://cb"},
        )
        assert resp.status_code == 401


async def test_exchange_reports_provider_outage() -> None:
    factory = _client_with_service(httpx.ConnectError("down"))
    async with factory() as client:
        resp = await client.post(
            "/auth/oidc/exchange",
            json={"code": "c", "code_verifier": "v", "redirect_uri": "http://cb"},
        )
        assert resp.status_code == 502


async def test_exchange_is_not_configured_without_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("REDIS_URL", "")
    monkeypatch.delenv("OIDC_ISSUER", raising=False)
    monkeypatch.delenv("OIDC_CLIENT_ID", raising=False)
    get_settings.cache_clear()
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/auth/oidc/exchange",
            json={"code": "c", "code_verifier": "v", "redirect_uri": "http://cb"},
        )
        assert resp.status_code == 404
    get_settings.cache_clear()
