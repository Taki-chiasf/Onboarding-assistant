from fastapi import HTTPException, Request, status
from itsdangerous import BadData, URLSafeTimedSerializer

from app.auth.principal import Principal
from app.core.deps import SettingsDep

SESSION_COOKIE = "session"
MAX_AGE_SECONDS = 60 * 60 * 8


def make_serializer(secret: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret, salt="session")


def encode_principal(serializer: URLSafeTimedSerializer, principal: Principal) -> str:
    return serializer.dumps(principal.model_dump())


def decode_principal(serializer: URLSafeTimedSerializer, token: str) -> Principal | None:
    try:
        data = serializer.loads(token, max_age=MAX_AGE_SECONDS)
    except BadData:
        return None
    return Principal(**data)


def resolve_principal(request: Request, settings: SettingsDep) -> Principal | None:
    if settings.mock_oidc == 1:
        return Principal(
            sub=settings.dev_principal_sub,
            email=settings.dev_principal_email,
            dept=settings.dev_principal_dept,
            role=settings.dev_principal_role,
        )
    # Persona mode and the real OIDC path both carry the principal in the
    # signed session cookie, so a disabled mock (0) still reads it.
    token = request.cookies.get(SESSION_COOKIE)
    if token is None:
        return None
    return decode_principal(make_serializer(settings.session_secret), token)


def get_principal(request: Request, settings: SettingsDep) -> Principal:
    principal = resolve_principal(request, settings)
    if principal is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")
    return principal
