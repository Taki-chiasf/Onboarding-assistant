'''Ledger storage for charges and refunds.

The ledger is deliberately idempotent: replaying a write with the same
idempotency key returns the original entry instead of charging twice.
'''

from dataclasses import dataclass


class LedgerConflict(Exception):
    '''A replayed idempotency key did not match the original request.'''


@dataclass
class Entry:
    id: str
    account_id: str
    amount_cents: int
    status: str


class Ledger:
    def __init__(self) -> None:
        self._entries: dict[str, Entry] = {}
        self._by_key: dict[str, str] = {}

    def record(self, account_id: str, amount_cents: int, idempotency_key: str) -> Entry:
        '''Record a charge, or return the entry the key already produced.'''
        existing = self._by_key.get(idempotency_key)
        if existing is not None:
            entry = self._entries[existing]
            if entry.account_id != account_id or entry.amount_cents != amount_cents:
                raise LedgerConflict("idempotency key reused with a different request")
            return entry
        entry = Entry(
            id="ch_" + str(len(self._entries) + 1),
            account_id=account_id,
            amount_cents=amount_cents,
            status="captured",
        )
        self._entries[entry.id] = entry
        self._by_key[idempotency_key] = entry.id
        return entry

    def refund(self, charge_id: str, idempotency_key: str) -> Entry:
        existing = self._by_key.get(idempotency_key)
        if existing is not None:
            return self._entries[existing]
        entry = self._entries.get(charge_id)
        if entry is None:
            raise LedgerConflict("charge not found")
        refund = Entry(
            id="rf_" + charge_id,
            account_id=entry.account_id,
            amount_cents=-entry.amount_cents,
            status="refunded",
        )
        self._entries[refund.id] = refund
        self._by_key[idempotency_key] = refund.id
        return refund
