'''Payments HTTP entrypoint: charges and refunds.

Every write accepts an idempotency key. The ledger stores the key with the
original result; a replay with the same key returns that result, and a replay
with a different body is rejected as a conflict.
'''

from fastapi import FastAPI, Header, HTTPException

from .ledger import Ledger, LedgerConflict

app = FastAPI(title="payments")
ledger = Ledger()


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.post("/charges")
def create_charge(
    account_id: str,
    amount_cents: int,
    idempotency_key: str = Header(alias="Idempotency-Key"),
) -> dict:
    if amount_cents <= 0:
        raise HTTPException(status_code=422, detail="amount must be positive")
    try:
        entry = ledger.record(account_id, amount_cents, idempotency_key)
    except LedgerConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {"charge_id": entry.id, "status": entry.status}


@app.post("/charges/{charge_id}/refund")
def refund_charge(
    charge_id: str,
    idempotency_key: str = Header(alias="Idempotency-Key"),
) -> dict:
    try:
        entry = ledger.refund(charge_id, idempotency_key)
    except LedgerConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {"charge_id": entry.id, "status": entry.status}
