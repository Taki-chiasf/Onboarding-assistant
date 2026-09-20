# Architecture Overview

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
