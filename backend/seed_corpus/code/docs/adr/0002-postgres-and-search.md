# ADR 0002: Postgres for storage, search, and vectors

## Status
Accepted

## Context
The platform needs transactional storage for accounts and payments, full-text
search for the help center, and vector similarity for the document assistant.
Running three separate systems was rejected as too much operational surface for
the team size.

## Decision
Use one Postgres cluster for all three workloads. Full-text search uses
`tsvector` indexes; embeddings are stored with the pgvector extension at 1024
dimensions.

## Consequences
- One backup, one failover path, one set of runbooks.
- Search and vector indexes share resources with the primary workload, so
  heavy backfills run in a batch window.
- If vector traffic outgrows the cluster, embeddings move to a dedicated store
  behind the same repository interface.
