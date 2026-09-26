"""Scan the repository for PII that is not clearly synthetic.

The demo ships only synthetic data, so any real-looking email or phone number
in a committed file is a leak. Emails on the example domains and the seeded
fake org's ``.demo.example`` domains are allowed; phone numbers must be in the
reserved fictional range. Runs in CI (``make pii-scan``).
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

# Deliberately tighter than the redaction patterns: a broad digit match would
# flag dates and version strings, which would make a repository scan useless.
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
PHONE_RE = re.compile(r"\+\d[\d\s().-]{8,}\d")

ALLOWED_EMAIL_DOMAINS = frozenset({"example.com", "example.org", "example.net"})
# `.example` is a reserved documentation TLD, so any address under it is
# synthetic. The exact allowlist covers redaction fixtures that deliberately
# use a non-synthetic address to prove the redactor works.
ALLOWED_EMAIL_SUFFIXES = (".example",)
ALLOWED_EMAILS = frozenset({"bob@corp.com"})
ALLOWED_PHONE_PREFIXES = ("+1555", "+1 555", "+1-555", "+1 (555")

SKIP_DIRS = frozenset(
    {
        ".git",
        ".next",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        ".impeccable",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
    }
)
SKIP_SUFFIXES = frozenset(
    {
        ".gif",
        ".ico",
        ".jpeg",
        ".jpg",
        ".lock",
        ".map",
        ".pdf",
        ".png",
        ".pyc",
        ".woff",
        ".woff2",
        ".zip",
    }
)
SKIP_NAMES = frozenset({"package-lock.json", "uv.lock"})
MAX_FILE_BYTES = 2_000_000

DEFAULT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    kind: str
    value: str


def _allowed_email(value: str) -> bool:
    if value in ALLOWED_EMAILS:
        return True
    domain = value.rsplit("@", 1)[-1].lower()
    if domain in ALLOWED_EMAIL_DOMAINS:
        return True
    return any(domain.endswith(suffix) for suffix in ALLOWED_EMAIL_SUFFIXES)


def _allowed_phone(value: str) -> bool:
    return value.startswith(ALLOWED_PHONE_PREFIXES)


def iter_files(root: Path) -> Iterator[Path]:
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.name in SKIP_NAMES or path.suffix in SKIP_SUFFIXES:
            continue
        if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
            continue
        yield path


def scan_file(path: Path, *, root: Path) -> list[Finding]:
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []
    relative = path.relative_to(root).as_posix()
    findings: list[Finding] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for value in EMAIL_RE.findall(line):
            if not _allowed_email(value):
                findings.append(Finding(relative, number, "email", value))
        for value in PHONE_RE.findall(line):
            if not _allowed_phone(value):
                findings.append(Finding(relative, number, "phone", value))
    return findings


def scan(root: Path = DEFAULT_ROOT) -> list[Finding]:
    findings: list[Finding] = []
    for path in iter_files(root):
        findings.extend(scan_file(path, root=root))
    return findings


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan the repository for non-synthetic PII")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args(argv)

    findings = scan(args.root)
    if not findings:
        print(f"pii scan: clean ({args.root})")
        return 0
    for finding in findings:
        print(f"{finding.path}:{finding.line}: {finding.kind}: {finding.value}")
    print(f"pii scan: {len(findings)} finding(s)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
