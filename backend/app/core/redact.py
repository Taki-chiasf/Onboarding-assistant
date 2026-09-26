"""Best-effort PII redaction for logged and persisted text.

Email addresses, IPv4 addresses, and phone-like numbers are replaced with
placeholders before text is written to logs or stored in the eval set. An
allowlist keeps the caller's own identity intact. The phone pattern is broad on
purpose: it also catches national-id and card-like digit runs, so anything
shaped like a long number is treated as sensitive.
"""

from __future__ import annotations

import re

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
PHONE_RE = re.compile(r"\+?\d[\d\s().-]{7,}\d")


def redact_pii(text: str, *, allow: list[str] | None = None) -> str:
    allowed = set(allow or [])

    def _redact_email(match: re.Match[str]) -> str:
        return match.group(0) if match.group(0) in allowed else "[email]"

    redacted = EMAIL_RE.sub(_redact_email, text)
    redacted = IPV4_RE.sub("[ip]", redacted)
    return PHONE_RE.sub("[phone]", redacted)
