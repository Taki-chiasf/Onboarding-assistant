"""Authentication endpoints.

Exposes the auth mode (which sign-in the web app should offer) and the OIDC
authorization-code exchange. The persona endpoints for local dev and the public
demo live alongside under ``/auth/dev``.
"""

from __future__ import annotations

import logging
from typing import Annotated, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel

from app.auth.claims import ClaimError, report_claim_drift
from app.auth.mock_oidc import SESSION_COOKIE, encode_principal, make_serializer
from app.auth.oidc import IdTokenError, IdTokenVerifier, OidcService, load_oidc_config
from app.auth.principal import Principal
from app.core.deps import SettingsDep

router = APIRouter(prefix="/auth", tags=["auth"])

logger = logging.getLogger(__name__)

AuthMode = Literal["oidc", "persona", "static", "disabled"]


class OidcPublicConfig(BaseModel):
    authorize_url: str
    client_id: str
    audience: str
    scope: str


class AuthModeResponse(BaseModel):
    mode: AuthMode
    oidc: OidcPublicConfig | None = None


class OidcExchangeRequest(BaseModel):
    code: str
    code_verifier: str
    redirect_uri: str


def _auth_mode(settings: SettingsDep) -> AuthMode:
    if load_oidc_config(settings) is not None:
        return "oidc"
    if settings.mock_oidc == 2:
        return "persona"
    if settings.mock_oidc == 1:
        return "static"
    return "disabled"


@router.get("/mode", response_model=AuthModeResponse)
async def auth_mode(settings: SettingsDep) -> AuthModeResponse:
    mode = _auth_mode(settings)
    config = load_oidc_config(settings)
    if config is None:
        return AuthModeResponse(mode=mode)
    return AuthModeResponse(
        mode=mode,
        oidc=OidcPublicConfig(
            authorize_url=config.authorize_url,
            client_id=config.client_id,
            audience=config.audience,
            scope=config.scope,
        ),
    )


def get_oidc_service(request: Request, settings: SettingsDep) -> OidcService:
    """Return the OIDC service, cached on the app for the JWKS cache to survive."""
    config = getattr(request.app.state, "oidc_config", None) or load_oidc_config(settings)
    if config is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="oidc is not configured")
    verifier = getattr(request.app.state, "oidc_verifier", None)
    if verifier is None:
        verifier = IdTokenVerifier(config)
    request.app.state.oidc_config = config
    request.app.state.oidc_verifier = verifier
    return OidcService(config=config, verifier=verifier)


@router.post("/oidc/exchange", response_model=Principal)
async def oidc_exchange(
    payload: OidcExchangeRequest,
    response: Response,
    settings: SettingsDep,
    service: Annotated[OidcService, Depends(get_oidc_service)],
) -> Principal:
    try:
        result = await service.authenticate(
            code=payload.code,
            code_verifier=payload.code_verifier,
            redirect_uri=payload.redirect_uri,
        )
    except ClaimError as exc:
        logger.warning("rejected principal: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="login failed"
        ) from exc
    except IdTokenError as exc:
        logger.warning("id token validation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="login failed"
        ) from exc
    except httpx.HTTPError as exc:
        logger.warning("oidc token exchange failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="identity provider unavailable",
        ) from exc

    report_claim_drift(result.drift, sub=result.principal.sub)
    token = encode_principal(make_serializer(settings.session_secret), result.principal)
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax")
    return result.principal
