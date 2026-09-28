'''Auth service HTTP entrypoint.'''

from fastapi import FastAPI, HTTPException, Request

from .settings import Settings
from .tokens import TokenError, mint_token, verify_token

app = FastAPI(title="auth")
settings = Settings.from_env()


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.post("/token")
def issue_token(subject: str, scopes: list[str]) -> dict:
    return {"token": mint_token(settings, subject, scopes)}


@app.get("/verify")
def verify(request: Request) -> dict:
    '''Verify a bearer token and echo the claims it carries.'''
    header = request.headers.get("authorization", "")
    token = header.removeprefix("Bearer ").strip()
    try:
        payload = verify_token(settings, token)
    except TokenError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error
    return {"subject": payload["sub"], "scopes": payload["scopes"]}


def main() -> None:
    import uvicorn

    uvicorn.run("services.auth.app:app", host="0.0.0.0", port=8081, reload=True)


if __name__ == "__main__":
    main()
