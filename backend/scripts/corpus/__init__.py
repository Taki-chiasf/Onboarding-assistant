"""Synthetic document corpus content, grouped by category."""

from scripts.corpus import engineering, handbook, policies, runbooks

CATEGORIES: dict[str, list[tuple[str, str]]] = {
    "policies": policies.DOCS,
    "handbook": handbook.DOCS,
    "runbooks": runbooks.DOCS,
    "engineering": engineering.DOCS,
}

PDF_SOURCES: list[tuple[str, str]] = [
    ("benefits-summary.pdf", "policies/benefits-overview.md"),
    ("security-policy.pdf", "policies/security-policy.md"),
    ("equipment-guide.pdf", "policies/equipment-policy.md"),
]

__all__ = ["CATEGORIES", "PDF_SOURCES"]
