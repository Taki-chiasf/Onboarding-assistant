# ADR 0003: Background jobs on a Redis queue

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
