"""Best-effort PII redaction for logged prompt text.

Email addresses and phone numbers are replaced with placeholders before a
prompt is written to logs. An allowlist keeps the caller's own identity intact.
"""

from __future__ import annotations

import re

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
PHONE_RE = re.compile(r"\+?\d[\d\s().-]{7,}\d")


def redact_pii(text: str, *, allow: list[str] | None = None) -> str:
    allowed = set(allow or [])

    def _redact_email(match: re.Match[str]) -> str:
        return match.group(0) if match.group(0) in allowed else "[email]"

    redacted = EMAIL_RE.sub(_redact_email, text)
    return PHONE_RE.sub("[phone]", redacted)
