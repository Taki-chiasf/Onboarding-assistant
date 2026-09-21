"""Golden evaluation set for retrieval.

The cases are hand-authored queries mapped to the synthetic corpus. Expected
source identifiers are computed from deterministic chunking, so they stay
stable across re-ingestion and can be compared against whatever the retrieval
stage returns.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.ingest.pipeline import acl_tags_for, source_type_for
from app.rag import chunk_id, chunk_markdown
from scripts.corpus import CATEGORIES

INTENT_RAG_DOCS = "rag-docs"


@dataclass(frozen=True)
class CaseSpec:
    prompt: str
    source_uri: str
    anchor: str
    tags: list[str]


@dataclass(frozen=True)
class GoldenCase:
    prompt: str
    expected_intent: str
    expected_source_ids: list[str]
    tags: list[str]


SPECS: list[CaseSpec] = [
    CaseSpec(
        "How many weeks of paid parental leave do employees get?",
        "file:policies/parental-leave.md",
        "Duration",
        ["all", "policy"],
    ),
    CaseSpec(
        "Who is eligible for parental leave?",
        "file:policies/parental-leave.md",
        "Eligibility",
        ["all", "policy"],
    ),
    CaseSpec(
        "How do I request parental leave?",
        "file:policies/parental-leave.md",
        "How to request",
        ["all", "policy"],
    ),
    CaseSpec(
        "Can I work from home?", "file:policies/remote-work.md", "Overview", ["all", "policy"]
    ),
    CaseSpec(
        "What are the core collaboration hours?",
        "file:policies/remote-work.md",
        "Core hours",
        ["all", "policy"],
    ),
    CaseSpec(
        "What is the daily meal limit during travel?",
        "file:policies/expenses.md",
        "Limits",
        ["all", "policy"],
    ),
    CaseSpec(
        "What expenses are reimbursable?",
        "file:policies/expenses.md",
        "Categories",
        ["all", "policy"],
    ),
    CaseSpec(
        "How many paid time off days do I get per year?",
        "file:policies/paid-time-off.md",
        "Allowance",
        ["all", "policy"],
    ),
    CaseSpec(
        "Do I need a doctor's note for sick leave?",
        "file:policies/paid-time-off.md",
        "Sick leave",
        ["all", "policy"],
    ),
    CaseSpec(
        "What is the annual learning budget?",
        "file:policies/benefits-overview.md",
        "Learning",
        ["all", "policy"],
    ),
    CaseSpec(
        "Does the company match retirement contributions?",
        "file:policies/benefits-overview.md",
        "Retirement",
        ["all", "policy"],
    ),
    CaseSpec(
        "How do I report a code of conduct concern?",
        "file:policies/code-of-conduct.md",
        "Reporting concerns",
        ["all", "policy"],
    ),
    CaseSpec(
        "What devices must have full disk encryption?",
        "file:policies/security-policy.md",
        "Devices",
        ["all", "policy"],
    ),
    CaseSpec(
        "What is the standard equipment issued to new hires?",
        "file:policies/equipment-policy.md",
        "Standard issue",
        ["all", "policy"],
    ),
    CaseSpec(
        "What is the hotel budget for business travel?",
        "file:policies/travel-policy.md",
        "Accommodation",
        ["all", "policy"],
    ),
    CaseSpec(
        "How often are performance reviews run?",
        "file:policies/performance-reviews.md",
        "Cadence",
        ["all", "policy"],
    ),
    CaseSpec(
        "What are the data classification levels?",
        "file:policies/data-classification.md",
        "Levels",
        ["all", "policy"],
    ),
    CaseSpec(
        "How is on-call compensation structured?",
        "file:policies/on-call-compensation.md",
        "Rates",
        ["engineering", "policy"],
    ),
    CaseSpec(
        "What should I do on my first day?",
        "file:handbook/welcome.md",
        "Your first day",
        ["all", "handbook"],
    ),
    CaseSpec(
        "Where do I go for help during onboarding?",
        "file:handbook/welcome.md",
        "Where to go for help",
        ["all", "handbook"],
    ),
    CaseSpec(
        "What does the company do?",
        "file:handbook/company-overview.md",
        "What we do",
        ["all", "handbook"],
    ),
    CaseSpec(
        "Who are our customers?",
        "file:handbook/company-overview.md",
        "Our customers",
        ["all", "handbook"],
    ),
    CaseSpec(
        "What are the company values?",
        "file:handbook/values.md",
        "Customers first",
        ["all", "handbook"],
    ),
    CaseSpec(
        "What departments does the company have?",
        "file:handbook/org-structure.md",
        "Departments",
        ["all", "handbook"],
    ),
    CaseSpec(
        "What are the engineering teams?",
        "file:handbook/org-structure.md",
        "Engineering teams",
        ["engineering", "handbook"],
    ),
    CaseSpec(
        "What should I do before my first day?",
        "file:handbook/new-hire-checklist.md",
        "Before day one",
        ["all", "handbook"],
    ),
    CaseSpec(
        "How should I use chat channels?",
        "file:handbook/communication-norms.md",
        "Channels",
        ["all", "handbook"],
    ),
    CaseSpec(
        "What is the default meeting duration?",
        "file:handbook/meeting-culture.md",
        "Guidelines",
        ["all", "handbook"],
    ),
    CaseSpec(
        "When is the no-meeting block?",
        "file:handbook/meeting-culture.md",
        "No-meeting blocks",
        ["all", "handbook"],
    ),
    CaseSpec(
        "How do promotions work?",
        "file:handbook/career-growth.md",
        "Promotions",
        ["all", "handbook"],
    ),
    CaseSpec(
        "Can I request a mentor outside my team?",
        "file:handbook/career-growth.md",
        "Mentorship",
        ["all", "handbook"],
    ),
    CaseSpec(
        "How should I give feedback?",
        "file:handbook/feedback-culture.md",
        "Giving feedback",
        ["all", "handbook"],
    ),
    CaseSpec(
        "How much notice do I give when leaving?",
        "file:handbook/leaving-the-company.md",
        "Notice",
        ["all", "handbook"],
    ),
    CaseSpec("How do I set up the VPN?", "file:runbooks/vpn-setup.md", "Steps", ["all", "runbook"]),
    CaseSpec(
        "How do I enroll in multi-factor authentication?",
        "file:runbooks/sso-mfa-setup.md",
        "Enrolling MFA",
        ["all", "runbook"],
    ),
    CaseSpec(
        "How do I set up my laptop?", "file:runbooks/laptop-setup.md", "Steps", ["all", "runbook"]
    ),
    CaseSpec(
        "Can I forward company email to personal accounts?",
        "file:runbooks/email-and-calendar.md",
        "Email",
        ["all", "runbook"],
    ),
    CaseSpec(
        "How do I set my chat status?", "file:runbooks/chat-usage.md", "Status", ["all", "runbook"]
    ),
    CaseSpec(
        "How do I connect to office Wi-Fi?",
        "file:runbooks/accessing-wifi.md",
        "Office network",
        ["all", "runbook"],
    ),
    CaseSpec(
        "How do I request access to a system?",
        "file:runbooks/request-access.md",
        "Steps",
        ["all", "runbook"],
    ),
    CaseSpec(
        "How should I name git branches?",
        "file:runbooks/git-workflow.md",
        "Branching",
        ["engineering", "runbook"],
    ),
    CaseSpec(
        "What is a severity 1 incident?",
        "file:runbooks/incident-response.md",
        "Severities",
        ["engineering", "runbook"],
    ),
    CaseSpec(
        "How do I roll back a failed deploy?",
        "file:runbooks/deploy-process.md",
        "Rollbacks",
        ["engineering", "runbook"],
    ),
    CaseSpec(
        "When should I escalate an incident?",
        "file:runbooks/on-call-guide.md",
        "Escalation",
        ["engineering", "runbook"],
    ),
    CaseSpec(
        "How do I set up local development?",
        "file:runbooks/local-dev-setup.md",
        "Steps",
        ["engineering", "runbook"],
    ),
    CaseSpec(
        "How do I submit an expense?",
        "file:runbooks/expense-submission.md",
        "Steps",
        ["all", "runbook"],
    ),
    CaseSpec(
        "What is the lead time for standard equipment?",
        "file:runbooks/request-equipment.md",
        "Lead times",
        ["all", "runbook"],
    ),
    CaseSpec(
        "What does the engineering organization do?",
        "file:engineering/engineering-overview.md",
        "Mission",
        ["engineering", "engineering"],
    ),
    CaseSpec(
        "What do code reviewers look for?",
        "file:engineering/code-review.md",
        "What reviewers look for",
        ["engineering", "engineering"],
    ),
    CaseSpec(
        "What data stores does the platform use?",
        "file:engineering/architecture-overview.md",
        "Data stores",
        ["engineering", "engineering"],
    ),
    CaseSpec(
        "What is the test coverage gate?",
        "file:engineering/testing-guidelines.md",
        "Coverage",
        ["engineering", "engineering"],
    ),
    CaseSpec(
        "How are API errors structured?",
        "file:engineering/api-conventions.md",
        "Errors",
        ["engineering", "engineering"],
    ),
    CaseSpec(
        "How are database migrations rolled back?",
        "file:engineering/database-migrations.md",
        "Rollback",
        ["engineering", "engineering"],
    ),
    CaseSpec(
        "What should alerts do?",
        "file:engineering/monitoring-and-alerting.md",
        "Alerts",
        ["engineering", "engineering"],
    ),
    CaseSpec(
        "How should secrets be handled in code?",
        "file:engineering/security-in-code.md",
        "Secrets",
        ["engineering", "engineering"],
    ),
]


def corpus_documents() -> dict[str, str]:
    documents: dict[str, str] = {}
    for category, entries in CATEGORIES.items():
        for filename, content in entries:
            documents[f"file:{category}/{filename}"] = content
    return documents


def _category_for(source_uri: str) -> str:
    return source_uri.split(":", 1)[1].split("/", 1)[0]


def build_golden_set() -> list[GoldenCase]:
    documents = corpus_documents()
    cases: list[GoldenCase] = []
    for spec in SPECS:
        markdown = documents[spec.source_uri]
        source_type = source_type_for(_category_for(spec.source_uri))
        chunks = chunk_markdown(spec.source_uri, source_type, markdown, acl_tags_for(source_type))
        title = chunks[0].section_anchor.split(" > ")[0] if chunks else spec.source_uri
        target = f"{title} > {spec.anchor}" if spec.anchor else title
        matched = [chunk for chunk in chunks if chunk.section_anchor == target]
        if not matched:
            raise ValueError(f"no chunks matched {spec.source_uri!r} anchor {spec.anchor!r}")
        cases.append(
            GoldenCase(
                prompt=spec.prompt,
                expected_intent=INTENT_RAG_DOCS,
                expected_source_ids=[
                    str(chunk_id(spec.source_uri, chunk.chunk_index)) for chunk in matched
                ],
                tags=spec.tags,
            )
        )
    return cases


def recall_at_k(expected: list[str], retrieved: list[str], k: int) -> bool:
    return any(source_id in retrieved[:k] for source_id in expected)
