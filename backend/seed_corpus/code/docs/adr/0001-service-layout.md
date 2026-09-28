# ADR 0001: One service per directory

## Status
Accepted

## Context
The first version of the backend mixed HTTP handlers, background workers, and
shared helpers in one module tree. Ownership was unclear and test runs grew
slower with every feature.

## Decision
Every deployable service lives in its own directory under `services/` with its
own settings, entrypoint, and migrations. Cross-service helpers live in
`libs/common` and stay small. Services talk to each other over the internal API
gateway, never by importing each other.

## Consequences
- Services can be deployed and scaled independently.
- Shared code must earn its place in `libs/common` or it drifts.
- A change to the shared library requires a release of every dependent service.
