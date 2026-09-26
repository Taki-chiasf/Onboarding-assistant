"""Map identity-provider claims onto the request principal.

The mapping is the only place an external identity becomes a `Principal`, so it
is deliberately strict: a token without a subject or department is rejected, and
a role the deployment does not recognize degrades to the least-privileged role
and is reported as claim drift rather than silently trusted. The mapping is a
pure function; reporting is kept separate so it can be tested without a meter.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from opentelemetry import metrics
from opentelemetry.metrics import Counter

from app.auth.principal import Principal

logger = logging.getLogger(__name__)

DEFAULT_ROLE = "employee"
KNOWN_ROLES = ("employee", "admin")

_counter: Counter | None = None


class ClaimError(Exception):
    """The claims cannot produce a usable principal."""


@dataclass(frozen=True)
class ClaimResult:
    principal: Principal
    drift: tuple[str, ...] = ()


def _value(claims: dict[str, Any], name: str) -> str | None:
    if not name:
        return None
    raw = claims.get(name)
    if isinstance(raw, (list, tuple)):
        raw = raw[0] if raw else None
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def principal_from_claims(
    claims: dict[str, Any],
    *,
    dept_claim: str,
    role_claim: str,
    email_claim: str,
    allowed_roles: tuple[str, ...] = KNOWN_ROLES,
    allowed_departments: tuple[str, ...] = (),
) -> ClaimResult:
    """Turn verified token claims into a principal.

    Raises `ClaimError` when no principal can be established: a missing subject,
    a missing or unmapped department. A missing or unmapped role never rejects
    the login; it downgrades to the least-privileged role and is reported.
    """
    sub = _value(claims, "sub")
    if sub is None:
        raise ClaimError("id token has no subject")

    dept = _value(claims, dept_claim)
    if dept is None:
        raise ClaimError(f"id token has no department claim ({dept_claim})")
    if allowed_departments and dept not in allowed_departments:
        raise ClaimError(f"department claim is not mapped: {dept}")

    drift: list[str] = []
    raw_role = _value(claims, role_claim)
    if raw_role is not None and raw_role in allowed_roles:
        role = raw_role
    else:
        role = DEFAULT_ROLE
        if raw_role is None:
            drift.append(f"missing role claim ({role_claim}): defaulted to {DEFAULT_ROLE}")
        else:
            drift.append(f"unmapped role claim value {raw_role!r}: defaulted to {DEFAULT_ROLE}")

    email = _value(claims, email_claim) or ""
    principal = Principal(sub=sub, email=email, dept=dept, role=role)
    return ClaimResult(principal=principal, drift=tuple(drift))


def _drift_counter() -> Counter:
    global _counter
    if _counter is None:
        _counter = metrics.get_meter(__name__).create_counter(
            "auth.claim_drift",
            description="Identity-provider claims that did not map cleanly",
        )
    return _counter


def report_claim_drift(drift: tuple[str, ...], *, sub: str) -> None:
    """Log and count claim drift. A no-op when the mapping was clean."""
    if not drift:
        return
    for note in drift:
        logger.warning("identity claim drift for sub=%s: %s", sub, note)
    _drift_counter().add(len(drift), {"sub": sub})
