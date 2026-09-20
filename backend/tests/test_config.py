import pytest

from app.auth.mock_oidc import decode_principal, encode_principal, make_serializer
from app.auth.principal import Principal
from app.core.config import Settings, get_settings


def test_settings_defaults() -> None:
    settings = Settings(mock_oidc=1)
    assert settings.app_name.endswith("-api")
    assert settings.dev_principal_role == "employee"


def test_settings_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://example")
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.database_url == "postgresql+psycopg://example"
    get_settings.cache_clear()


def test_principal_cookie_roundtrip() -> None:
    serializer = make_serializer("secret")
    principal = Principal(sub="u", email="e@example.com", dept="Engineering", role="employee")
    token = encode_principal(serializer, principal)
    assert decode_principal(serializer, token) == principal


def test_principal_cookie_rejects_garbage() -> None:
    serializer = make_serializer("secret")
    assert decode_principal(serializer, "not-a-valid-token") is None
