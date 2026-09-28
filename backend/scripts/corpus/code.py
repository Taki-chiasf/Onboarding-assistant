"""Synthetic service-repository files for the demo corpus.

The files mimic a small internal platform repository (services, shared library,
ADRs, runbooks) so codebase retrieval and ``file:line`` citations are demoable
without any real source. They are data, not code that runs in this project, and
are excluded from lint and type checks.
"""

DOCS: list[tuple[str, str]] = [
    (
        "README.md",
        """# Platform Services

One repository for the backend services behind the product API.

## Layout
- `services/auth` - issues and verifies access tokens.
- `services/payments` - charges, refunds, and the ledger.
- `services/notifications` - email and push delivery on a background queue.
- `libs/common` - settings, database sessions, and logging shared by services.
- `docs` - architecture decision records and runbooks.

## Running a service locally
1. Start the dependencies: `make deps` brings up Postgres and Redis.
2. Export the service settings. `libs/common/config.py` lists the names.
3. Run it: `make run SERVICE=auth` starts the service with reload on port 8081.
4. Check health: `curl localhost:8081/healthz`.

## Tests
Run `make test` for the whole repository, or `make test SERVICE=payments` for
one service. New endpoints and bug fixes ship with tests.

## Migrations
Migrations live next to the service that owns the schema. Apply them with
`make migrate SERVICE=payments`; roll back with `make migrate-down SERVICE=payments`.
""",
    ),
    (
        "CONTRIBUTING.md",
        """# Contributing

## Pull requests
Keep pull requests small and single-purpose. A review looks for:
- a clear description of the change and its risk,
- tests that fail before the change and pass after it,
- typed function signatures at service boundaries,
- no secrets, tokens, or customer data anywhere in the diff,
- migrations that stay backward compatible with the previous release.

## Style
Formatting and linting run in CI. Run `make lint` and `make format` before
pushing.

## Reviews
At least one approval is required. Reviewers focus on correctness and
operability; style is automated. Design changes are discussed in an ADR before
the code is written.
""",
    ),
    (
        "docs/adr/0001-service-layout.md",
        """# ADR 0001: One service per directory

## Status
Accepted

## Context
The first version of the backend mixed HTTP handlers, background workers, and
shared helpers in one module tree. Ownership was unclear and test runs grew
slower with every feature.

## Decision
Every deployable service lives in its own directory under `services/` with its
own settings, entrypoint, and migrations. Cross-service helpers live in
`libs/common` and stay small. Services talk to each other over the internal API
gateway, never by importing each other.

## Consequences
- Services can be deployed and scaled independently.
- Shared code must earn its place in `libs/common` or it drifts.
- A change to the shared library requires a release of every dependent service.
""",
    ),
    (
        "docs/adr/0002-postgres-and-search.md",
        """# ADR 0002: Postgres for storage, search, and vectors

## Status
Accepted

## Context
The platform needs transactional storage for accounts and payments, full-text
search for the help center, and vector similarity for the document assistant.
Running three separate systems was rejected as too much operational surface for
the team size.

## Decision
Use one Postgres cluster for all three workloads. Full-text search uses
`tsvector` indexes; embeddings are stored with the pgvector extension at 1024
dimensions.

## Consequences
- One backup, one failover path, one set of runbooks.
- Search and vector indexes share resources with the primary workload, so
  heavy backfills run in a batch window.
- If vector traffic outgrows the cluster, embeddings move to a dedicated store
  behind the same repository interface.
""",
    ),
    (
        "docs/adr/0003-background-jobs.md",
        """# ADR 0003: Background jobs on a Redis queue

## Status
Accepted

## Context
Notification delivery, report generation, and corpus ingestion are too slow or
too flaky for the request path.

## Decision
Background work runs on a Redis-backed queue with worker processes. Jobs are
plain functions with serializable arguments, and they are idempotent: a job
that runs twice must not duplicate its effect. Failures retry with exponential
backoff and land in a dead-letter queue after the final attempt.

## Consequences
- The request path stays fast and predictable.
- Workers scale independently from the API.
- Operating the queue is part of on-call; the runbook covers stuck jobs and
  the dead-letter queue.
""",
    ),
    (
        "docs/runbooks/auth-service.md",
        """# Auth Service Runbook

## Running locally
1. Start Postgres and Redis: `make deps`.
2. The service reads `AUTH_DATABASE_URL` and `AUTH_SIGNING_KEY` from the
   environment; copy `.env.example` to `.env` and fill both in.
3. Start it with `make run SERVICE=auth`.
4. Confirm it is up: `curl localhost:8081/healthz` returns `{"status":"ok"}`.

## Rotating the signing key
1. Generate a new key and store it in the secret manager.
2. Deploy the new key as the secondary key so the service accepts tokens
   signed by either key.
3. Wait for the longest token lifetime (one hour).
4. Promote the new key to primary and remove the old one.

## Common failures
- A `TokenError: signature mismatch` right after a rotation means step 2 was
  skipped or the old key was removed too early.
- The service refuses to start without a signing key; that is deliberate.
""",
    ),
    (
        "services/auth/settings.py",
        """'''Auth service settings loaded from the environment.'''

import os
from dataclasses import dataclass

DEFAULT_TOKEN_TTL_SECONDS = 3600


@dataclass(frozen=True)
class Settings:
    database_url: str
    signing_key: str
    token_ttl_seconds: int = DEFAULT_TOKEN_TTL_SECONDS

    @classmethod
    def from_env(cls) -> "Settings":
        '''Build settings, failing fast when the signing key is missing.'''
        signing_key = os.environ.get("AUTH_SIGNING_KEY", "")
        if not signing_key:
            raise RuntimeError("AUTH_SIGNING_KEY is required")
        return cls(
            database_url=os.environ["AUTH_DATABASE_URL"],
            signing_key=signing_key,
            token_ttl_seconds=int(
                os.environ.get("AUTH_TOKEN_TTL", DEFAULT_TOKEN_TTL_SECONDS)
            ),
        )
""",
    ),
    (
        "services/auth/tokens.py",
        """'''Access token minting and verification.

Tokens are HMAC-signed: an encoded payload plus a signature, both base64url.
The format is internal to the platform; clients only see the opaque string.
'''

import base64
import hashlib
import hmac
import json
import time

from .settings import Settings


class TokenError(Exception):
    '''Raised when a token is malformed, expired, or badly signed.'''


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _sign(signing_key: str, payload: str) -> str:
    digest = hmac.new(signing_key.encode(), payload.encode(), hashlib.sha256).digest()
    return _b64encode(digest)


def mint_token(settings: Settings, subject: str, scopes: list[str]) -> str:
    '''Mint a token for a subject with the given scopes.'''
    payload = {
        "sub": subject,
        "scopes": scopes,
        "exp": int(time.time()) + settings.token_ttl_seconds,
    }
    encoded = _b64encode(json.dumps(payload, separators=(",", ":")).encode())
    return encoded + "." + _sign(settings.signing_key, encoded)


def verify_token(settings: Settings, token: str) -> dict:
    '''Return the token payload, or raise TokenError.

    Signature comparison is constant time; expiry is checked after the
    signature so a forged token never reaches the payload parser.
    '''
    parts = token.split(".")
    if len(parts) != 2:
        raise TokenError("malformed token")
    encoded, signature = parts
    if not hmac.compare_digest(_sign(settings.signing_key, encoded), signature):
        raise TokenError("signature mismatch")
    payload = json.loads(_b64decode(encoded))
    if int(payload.get("exp", 0)) < int(time.time()):
        raise TokenError("token expired")
    return payload
""",
    ),
    (
        "services/auth/app.py",
        """'''Auth service HTTP entrypoint.'''

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
""",
    ),
    (
        "services/payments/api.py",
        """'''Payments HTTP entrypoint: charges and refunds.

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
""",
    ),
    (
        "services/payments/ledger.py",
        """'''Ledger storage for charges and refunds.

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
""",
    ),
    (
        "services/notifications/providers.py",
        """'''Channel providers used by the notification worker.'''

import logging

logger = logging.getLogger(__name__)


class Provider:
    def send(self, *, deduplication_key: str, recipient: str, body: str) -> None:
        raise NotImplementedError


class LocalProvider(Provider):
    '''Logs instead of sending; the local stack and tests use it.'''

    def send(self, *, deduplication_key: str, recipient: str, body: str) -> None:
        logger.info("notification %s to %s", deduplication_key, recipient)


_PROVIDERS: dict[str, Provider] = {"email": LocalProvider(), "push": LocalProvider()}


def for_channel(channel: str) -> Provider:
    if channel not in _PROVIDERS:
        raise ValueError("unknown channel: " + channel)
    return _PROVIDERS[channel]
""",
    ),
    (
        "services/notifications/worker.py",
        """'''Notification worker: consumes delivery jobs from the queue.

Delivery is at-least-once, so the provider call carries the notification id as
its deduplication key. Failed jobs retry with exponential backoff and move to
the dead-letter queue after the final attempt.
'''

import logging
import time

import redis
from rq import Queue, Worker

from .providers import for_channel

logger = logging.getLogger(__name__)

RETRYABLE_ERRORS = (TimeoutError, ConnectionError)
MAX_ATTEMPTS = 5


def deliver(notification_id: str, channel: str, recipient: str, body: str) -> None:
    '''Send one notification through the channel provider.'''
    provider = for_channel(channel)
    provider.send(deduplication_key=notification_id, recipient=recipient, body=body)
    logger.info("delivered notification %s over %s", notification_id, channel)


def deliver_with_retry(notification_id: str, channel: str, recipient: str, body: str) -> None:
    '''Deliver with exponential backoff, then give up to the dead-letter queue.'''
    delay = 1.0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            deliver(notification_id, channel, recipient, body)
            return
        except RETRYABLE_ERRORS as error:
            if attempt == MAX_ATTEMPTS:
                logger.error("dead-lettering notification %s", notification_id)
                raise
            logger.warning("attempt %d failed: %s", attempt, error)
            time.sleep(delay)
            delay = min(delay * 2, 30)


def main() -> None:
    connection = redis.from_url("redis://localhost:6379/0")
    queue = Queue("notifications", connection=connection)
    Worker([queue], connection=connection).work(with_scheduler=False)


if __name__ == "__main__":
    main()
""",
    ),
    (
        "libs/common/config.py",
        """'''Environment-backed settings shared by the services.'''

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class BaseSettings:
    database_url: str
    redis_url: str
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "BaseSettings":
        '''Read settings from the environment, applying local defaults.'''
        return cls(
            database_url=os.environ["PLATFORM_DATABASE_URL"],
            redis_url=os.environ.get("PLATFORM_REDIS_URL", "redis://localhost:6379/0"),
            log_level=os.environ.get("PLATFORM_LOG_LEVEL", "INFO"),
        )


@lru_cache
def settings() -> BaseSettings:
    return BaseSettings.from_env()
""",
    ),
    (
        "libs/common/db.py",
        """'''Database session handling shared by the services.'''

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import BaseSettings


def engine_for(config: BaseSettings) -> Engine:
    return create_engine(config.database_url, pool_pre_ping=True)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    '''Commit on success, roll back on failure, always close.'''
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
""",
    ),
    (
        "libs/common/logging.py",
        """'''Structured logging shared by the services.'''

import json
import logging
import time

from opentelemetry import trace


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        span = trace.get_current_span().get_span_context()
        entry = {
            "ts": time.time(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if span.is_valid:
            entry["trace_id"] = format(span.trace_id, "032x")
        return json.dumps(entry)


def configure(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
""",
    ),
]
