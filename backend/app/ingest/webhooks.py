"""Reingest webhook parsing.

Repo pushes and source edits arrive as an HMAC-signed JSON body. This module
holds the deterministic pieces - signature verification, payload parsing, and
the branch filter - so the endpoint and its tests share one definition.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping

from pydantic import BaseModel, Field, field_validator

SIGNATURE_HEADERS = ("x-hub-signature-256", "x-webhook-signature")

REPO_SOURCE = "repo"
GENERIC_SOURCES = frozenset({"drive", "docs"})
KNOWN_SOURCES = GENERIC_SOURCES | {REPO_SOURCE}

MAX_CHANGED_PATHS = 500


class IngestWebhookPayload(BaseModel):
    """A source-edit notification: which source changed and, for a repo push,
    the branch and the changed paths."""

    source: str
    ref: str | None = None
    changed: list[str] = Field(default_factory=list, max_length=MAX_CHANGED_PATHS)

    @field_validator("source")
    @classmethod
    def source_is_known(cls, value: str) -> str:
        if value not in KNOWN_SOURCES:
            raise ValueError(f"unknown source: {value}")
        return value


def expected_signature(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def verify_signature(secret: str, body: bytes, header: str | None) -> bool:
    """Constant-time check of a ``sha256=<hex>`` signature over the raw body."""
    if not secret or not header:
        return False
    return hmac.compare_digest(expected_signature(secret, body), header.strip())


def signature_header(headers: Mapping[str, str]) -> str | None:
    for name in SIGNATURE_HEADERS:
        value = headers.get(name)
        if value:
            return value
    return None


def branch_ref(branch: str) -> str:
    return branch if branch.startswith("refs/") else f"refs/heads/{branch}"


def should_reingest(payload: IngestWebhookPayload, *, branch: str) -> tuple[bool, str | None]:
    """Whether a verified payload warrants a reingest, and why not if it does not.

    A repo push only reindexes the tracked branch; drive/docs edits are generic
    by design (no provider-specific integration exists in demo scope).
    """
    if payload.source == REPO_SOURCE and payload.ref and payload.ref != branch_ref(branch):
        return False, "ref is not the tracked branch"
    return True, None


def source_label(payload: IngestWebhookPayload) -> str:
    if payload.source == REPO_SOURCE:
        return f"repo:{payload.ref or 'manual'}"
    return payload.source
