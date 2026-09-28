# Auth Service Runbook

## Running locally
1. Start Postgres and Redis: `make deps`.
2. The service reads `AUTH_DATABASE_URL` and `AUTH_SIGNING_KEY` from the
   environment; copy `.env.example` to `.env` and fill both in.
3. Start it with `make run SERVICE=auth`.
4. Confirm it is up: `curl localhost:8081/healthz` returns `{"status":"ok"}`.

## Rotating the signing key
1. Generate a new key and store it in the secret manager.
2. Deploy the new key as the secondary key so the service accepts tokens
   signed by either key.
3. Wait for the longest token lifetime (one hour).
4. Promote the new key to primary and remove the old one.

## Common failures
- A `TokenError: signature mismatch` right after a rotation means step 2 was
  skipped or the old key was removed too early.
- The service refuses to start without a signing key; that is deliberate.
