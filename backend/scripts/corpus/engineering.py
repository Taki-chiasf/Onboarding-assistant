"""Synthetic engineering documents for the demo corpus."""

DOCS: list[tuple[str, str]] = [
    (
        "engineering-overview.md",
        """# Engineering Overview

## Mission
The engineering organization builds and operates the products our customers
rely on every day.

## Teams
Engineering is organized into Platform, Payments, Data, and Infrastructure
teams.

## Principles
We value readable code, automated testing, incremental delivery, and blameless
postmortems.

## Toolchain
We use a modern typed language on the backend, a typed frontend framework, and
a single relational database with a full-text and vector search extension.
""",
    ),
    (
        "code-review.md",
        """# Code Review

## Purpose
Code review catches bugs, shares knowledge, and keeps the codebase consistent.

## Process
Request review from your team. Reviews should be returned within one business
day.

## What reviewers look for
Correctness, readability, test coverage, security, and alignment with existing
conventions.

## Feedback
Be specific and kind. Distinguish blocking issues from suggestions. Approve when
concerns are addressed.
""",
    ),
    (
        "architecture-overview.md",
        """# Architecture Overview

## Services
The platform is a set of services behind a single API gateway. Each service
owns its data and exposes a typed API.

## Data stores
A single relational database holds application data, full-text search indexes,
and vector embeddings.

## Async work
Long-running jobs run on a queue with background workers, separate from the
request path.

## Observability
Every request is traced end to end. Logs and metrics feed a central dashboard.
""",
    ),
    (
        "testing-guidelines.md",
        """# Testing Guidelines

## Levels
Write unit tests for pure logic, integration tests for boundaries, and a small
set of end-to-end tests for critical paths.

## Coverage
We gate merges on at least 80% coverage of core services.

## What to test
Test behavior, not implementation. Cover happy paths, error paths, and edge
cases.

## Running tests
Run the full suite locally before opening a pull request. Fix flaky tests rather
than skipping them.
""",
    ),
    (
        "api-conventions.md",
        """# API Conventions

## Style
Use a typed API framework and consistent error shapes. Every endpoint returns
JSON.

## Errors
Return structured errors with a machine-readable code and a human-readable
message.

## Versioning
Version breaking changes with a URL prefix. Avoid breaking changes to stable
endpoints.

## Authentication
All endpoints require authentication. Authorization is checked per resource.
""",
    ),
    (
        "database-migrations.md",
        """# Database Migrations

## Tooling
Schema changes are managed with a migration framework. Migrations are versioned
and applied automatically before rollout.

## Rules
Migrations must be backward compatible so old and new versions can run side by
side during a rollout.

## Process
Add a migration with every schema change. Review migrations as carefully as code.

## Rollback
Rollback is manual and documented. Prefer additive changes that avoid destructive
rollbacks.
""",
    ),
    (
        "monitoring-and-alerting.md",
        """# Monitoring and Alerting

## Metrics
Track request rate, error rate, and latency for every service. Alert on
sustained deviations from baseline.

## Dashboards
Each service has a dashboard showing traffic, errors, and resource usage.

## Alerts
Alerts must be actionable and route to the on-call engineer. Tune noisy alerts
promptly.

## Tracing
Every request carries a trace id so issues can be followed across services.
""",
    ),
    (
        "security-in-code.md",
        """# Security in Code

## Input validation
Validate all input at the boundary. Never trust client-supplied data.

## Secrets
Never commit secrets. Load credentials from the secrets manager at runtime.

## Least privilege
Run services with the minimum permissions required. Scope database access to
what a service needs.

## Dependencies
Keep dependencies up to date and scan them for known vulnerabilities in CI.
""",
    ),
]
