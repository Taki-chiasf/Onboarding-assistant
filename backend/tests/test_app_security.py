"""App-startup guardrails for trust-bearing auth configuration.

A deployment that trusts cookie sessions must never do so with the shipped
placeholder secret, and a configured identity provider must never be silently
overridden by a mock mode. Both are checked when the app is built.
"""

import pytest

from app.core.config import get_settings
from app.main import create_app

PLACEHOLDER = "dev-only-insecure-secret"


def _app_env(monkeypatch: pytest.MonkeyPatch, **env: str) -> None:
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("REDIS_URL", "")
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()


def test_persona_mode_without_secret_generates_an_ephemeral_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _app_env(monkeypatch, MOCK_OIDC="2")
    create_app()
    assert get_settings().session_secret != PLACEHOLDER
    get_settings.cache_clear()


def test_ephemeral_secrets_differ_between_boots(monkeypatch: pytest.MonkeyPatch) -> None:
    _app_env(monkeypatch, MOCK_OIDC="2")
    create_app()
    first = get_settings().session_secret
    get_settings.cache_clear()

    _app_env(monkeypatch, MOCK_OIDC="2")
    create_app()
    second = get_settings().session_secret
    get_settings.cache_clear()

    assert first != second


def test_static_mode_keeps_the_placeholder(monkeypatch: pytest.MonkeyPatch) -> None:
    # Nothing is trusted in static mode, so the placeholder stays as an
    # explicit "nothing logged in" marker rather than turning into a secret.
    _app_env(monkeypatch, MOCK_OIDC="1")
    create_app()
    assert get_settings().session_secret == PLACEHOLDER
    get_settings.cache_clear()


def test_oidc_requires_a_real_session_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    _app_env(
        monkeypatch,
        MOCK_OIDC="0",
        OIDC_ISSUER="https://tenant.example.auth0.com/",
        OIDC_CLIENT_ID="client-123",
        OIDC_CLIENT_SECRET="client-secret-1",
    )
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        create_app()
    get_settings.cache_clear()


def test_static_mode_refuses_to_start_with_oidc_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # MOCK_OIDC=1 short-circuits every request to the shared dev principal and
    # would silently ignore the configured provider, collapsing all users
    # into one identity. Refuse the combination instead of shipping it.
    _app_env(
        monkeypatch,
        MOCK_OIDC="1",
        OIDC_ISSUER="https://tenant.example.auth0.com/",
        OIDC_CLIENT_ID="client-123",
        OIDC_CLIENT_SECRET="client-secret-1",
    )
    with pytest.raises(RuntimeError, match="MOCK_OIDC"):
        create_app()
    get_settings.cache_clear()
