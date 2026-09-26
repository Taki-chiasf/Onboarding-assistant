from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.auth.mock_oidc import (
    SESSION_COOKIE,
    encode_principal,
    get_principal,
    make_serializer,
)
from app.auth.oidc import load_oidc_config
from app.auth.principal import DEMO_PERSONAS, Principal
from app.core.deps import SettingsDep

router = APIRouter(prefix="/auth/dev", tags=["auth"])


def _persona_login_enabled(settings: SettingsDep) -> bool:
    """Persona login is for local dev and the public demo only.

    Configuring a real identity provider turns it off, so a deployment that
    enables OIDC but forgets to clear the mock mode cannot be bypassed by
    signing in as a seeded persona.
    """
    return settings.mock_oidc == 2 and load_oidc_config(settings) is None


@router.post("/login", response_model=Principal)
async def login(payload: Principal, response: Response, settings: SettingsDep) -> Principal:
    if not _persona_login_enabled(settings):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="mock persona login is disabled",
        )
    token = encode_principal(make_serializer(settings.session_secret), payload)
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax")
    return payload


@router.post("/logout")
async def logout(response: Response) -> dict[str, str]:
    response.delete_cookie(SESSION_COOKIE)
    return {"status": "ok"}


@router.get("/personas", response_model=list[Principal])
async def personas(settings: SettingsDep) -> list[Principal]:
    if not _persona_login_enabled(settings):
        return []
    return DEMO_PERSONAS


@router.get("/me", response_model=Principal)
async def me(principal: Annotated[Principal, Depends(get_principal)]) -> Principal:
    return principal
