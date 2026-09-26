from pathlib import Path

from scripts.pii_scan import DEFAULT_ROOT, scan

# Assembled at runtime so the scanner does not flag its own fixtures.
REAL_EMAIL = "jane.doe@" + "acme.com"
REAL_PHONE = "+44 " + "20 7946 0958"


def _write(root: Path, name: str, text: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_scan_flags_a_real_looking_email(tmp_path: Path) -> None:
    _write(tmp_path, "notes.md", f"contact {REAL_EMAIL} for access")
    findings = scan(tmp_path)
    assert [finding.kind for finding in findings] == ["email"]
    assert findings[0].value == REAL_EMAIL


def test_scan_flags_a_real_looking_phone(tmp_path: Path) -> None:
    _write(tmp_path, "notes.md", f"call {REAL_PHONE}")
    findings = scan(tmp_path)
    assert [finding.kind for finding in findings] == ["phone"]


def test_scan_allows_synthetic_addresses_and_reserved_phones(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "notes.md",
        "alex.chen@demo.example ada@finance.example dev@example.com +1 555 010 0000",
    )
    assert scan(tmp_path) == []


def test_scan_skips_ignored_directories(tmp_path: Path) -> None:
    _write(tmp_path, "node_modules/pkg/notes.md", REAL_EMAIL)
    assert scan(tmp_path) == []


def test_repository_is_clean() -> None:
    assert scan(DEFAULT_ROOT) == []
