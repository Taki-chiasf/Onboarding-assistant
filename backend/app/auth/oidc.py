"""OpenID Connect authorization-code flow against the identity provider.

The backend owns every security decision: it exchanges the authorization code,
validates the id token signature against the provider's JWKS (RS256), checks the
issuer and audience, and maps the claims onto a principal. The web app only
brokers the redirect and hands back the code, so no IdP secret or validation
logic lives in the browser-facing tier.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx
import jwt

from app.auth.claims import ClaimResult, principal_from_claims
from app.core.config import Settings

ALGORITHMS = ["RS256"]


class IdTokenError(Exception):
    """The id token could not be trusted."""


@dataclass(frozen=True)
class OidcConfig:
    issuer: str
    client_id: str
    client_secret: str
    audience: str
    scope: str
    authorize_url: str
    token_url: str
    jwks_url: str
    dept_claim: str
    role_claim: str
    email_claim: str
    allowed_departments: tuple[str, ...]
    allowed_roles: tuple[str, ...]


def _split(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


def load_oidc_config(settings: Settings) -> OidcConfig | None:
    """Build the OIDC config, or None when it is not configured.

    An issuer and client id are the minimum; the endpoint URLs default to the
    provider's conventional paths derived from the issuer.
    """
    if not settings.oidc_issuer or not settings.oidc_client_id:
        return None
    base = settings.oidc_issuer.rstrip("/")
    return OidcConfig(
        issuer=settings.oidc_issuer,
        client_id=settings.oidc_client_id,
        client_secret=settings.oidc_client_secret,
        audience=settings.oidc_audience,
        scope=settings.oidc_scope,
        authorize_url=settings.oidc_authorize_url or f"{base}/authorize",
        token_url=settings.oidc_token_url or f"{base}/oauth/token",
        jwks_url=settings.oidc_jwks_url or f"{base}/.well-known/jwks.json",
        dept_claim=settings.oidc_dept_claim,
        role_claim=settings.oidc_role_claim,
        email_claim=settings.oidc_email_claim,
        allowed_departments=_split(settings.oidc_allowed_departments),
        allowed_roles=_split(settings.oidc_allowed_roles) or ("employee", "admin"),
    )


class IdTokenVerifier:
    """Verify id tokens against a cached JWKS document."""

    def __init__(
        self,
        config: OidcConfig,
        *,
        http: httpx.AsyncClient | None = None,
        cache_ttl_s: float = 3600.0,
    ) -> None:
        self._config = config
        self._http = http
        self._cache_ttl_s = cache_ttl_s
        self._jwks: jwt.PyJWKSet | None = None
        self._fetched_at = 0.0

    async def _get_jwks(self) -> jwt.PyJWKSet:
        now = time.monotonic()
        if self._jwks is not None and now - self._fetched_at < self._cache_ttl_s:
            return self._jwks
        client = self._http or httpx.AsyncClient(timeout=10.0)
        try:
            response = await client.get(self._config.jwks_url)
            response.raise_for_status()
            document = response.json()
        finally:
            if self._http is None:
                await client.aclose()
        try:
            self._jwks = jwt.PyJWKSet.from_dict(document)
        except (jwt.PyJWKSetError, KeyError, TypeError) as exc:
            raise IdTokenError(f"invalid JWKS document: {exc}") from exc
        self._fetched_at = now
        return self._jwks

    async def verify(self, token: str) -> dict[str, Any]:
        jwks = await self._get_jwks()
        try:
            headers = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise IdTokenError(f"malformed token: {exc}") from exc
        kid = headers.get("kid")
        signing_key = next(
            (jwk.key for jwk in jwks.keys if kid is None or jwk.key_id == kid),
            None,
        )
        if signing_key is None:
            raise IdTokenError(f"no signing key for key id {kid!r}")
        try:
            claims = jwt.decode(
                token,
                key=signing_key,
                algorithms=ALGORITHMS,
                audience=self._config.client_id,
                issuer=self._config.issuer,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise IdTokenError(str(exc)) from exc
        return claims


async def exchange_code(
    config: OidcConfig,
    *,
    code: str,
    code_verifier: str,
    redirect_uri: str,
    http: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Exchange an authorization code for tokens at the provider's token endpoint."""
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": config.client_id,
        "code_verifier": code_verifier,
    }
    if config.client_secret:
        data["client_secret"] = config.client_secret
    client = http or httpx.AsyncClient(timeout=10.0)
    try:
        response = await client.post(config.token_url, data=data)
        response.raise_for_status()
    finally:
        if http is None:
            await client.aclose()
    payload = response.json()
    if not isinstance(payload, dict):
        raise IdTokenError("token endpoint returned a non-object response")
    return payload


@dataclass
class OidcService:
    config: OidcConfig
    verifier: IdTokenVerifier
    http: httpx.AsyncClient | None = None

    async def authenticate(
        self, *, code: str, code_verifier: str, redirect_uri: str
    ) -> ClaimResult:
        tokens = await exchange_code(
            self.config,
            code=code,
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
            http=self.http,
        )
        id_token = tokens.get("id_token")
        if not isinstance(id_token, str) or not id_token:
            raise IdTokenError("token response has no id_token")
        claims = await self.verifier.verify(id_token)
        return principal_from_claims(
            claims,
            dept_claim=self.config.dept_claim,
            role_claim=self.config.role_claim,
            email_claim=self.config.email_claim,
            allowed_roles=self.config.allowed_roles,
            allowed_departments=self.config.allowed_departments,
        )
