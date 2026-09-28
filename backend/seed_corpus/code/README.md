# Platform Services

One repository for the backend services behind the product API.

## Layout
- `services/auth` - issues and verifies access tokens.
- `services/payments` - charges, refunds, and the ledger.
- `services/notifications` - email and push delivery on a background queue.
- `libs/common` - settings, database sessions, and logging shared by services.
- `docs` - architecture decision records and runbooks.

## Running a service locally
1. Start the dependencies: `make deps` brings up Postgres and Redis.
2. Export the service settings. `libs/common/config.py` lists the names.
3. Run it: `make run SERVICE=auth` starts the service with reload on port 8081.
4. Check health: `curl localhost:8081/healthz`.

## Tests
Run `make test` for the whole repository, or `make test SERVICE=payments` for
one service. New endpoints and bug fixes ship with tests.

## Migrations
Migrations live next to the service that owns the schema. Apply them with
`make migrate SERVICE=payments`; roll back with `make migrate-down SERVICE=payments`.
