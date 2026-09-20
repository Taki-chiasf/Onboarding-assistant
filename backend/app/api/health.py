from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.readiness import ReadyCheck

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(request: Request) -> JSONResponse:
    checks: list[ReadyCheck] = getattr(request.app.state, "ready_checks", [])
    results: list[dict[str, object]] = []
    for check in checks:
        name, ok = await check()
        results.append({"name": name, "ok": ok})
    ready = all(result["ok"] for result in results)
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": "ready" if ready else "not-ready", "checks": results},
    )
