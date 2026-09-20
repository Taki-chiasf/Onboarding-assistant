from fastapi import FastAPI
from httpx import AsyncClient


async def test_healthz(client: AsyncClient) -> None:
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_readyz_without_checks(client: AsyncClient) -> None:
    resp = await client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"


async def test_readyz_reports_unready(app: FastAPI, client: AsyncClient) -> None:
    async def failing() -> tuple[str, bool]:
        return "postgres", False

    app.state.ready_checks = [failing]
    resp = await client.get("/readyz")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "not-ready"
    assert body["checks"] == [{"name": "postgres", "ok": False}]
