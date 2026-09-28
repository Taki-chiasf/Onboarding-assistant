# onboarding-assistant

A conversational onboarding assistant that answers new-hire questions from
company documents (retrieval-augmented generation) and live business data
(text-to-SQL), with a source citation and row-level access control on every
answer.

Full-stack and portfolio-grade:

- **Backend** — FastAPI (Python), streaming responses, OpenTelemetry traces.
- **Web** — Next.js (TypeScript, App Router), chat UI and admin console.
- **Workers** — async ingestion jobs and a nightly evaluation runner.
- **Data** — PostgreSQL 16 with pgvector + full-text search; read-only SQL
  execution with row-level security.
- **Inference** — Mistral La Plateforme end-to-end (LLM, embeddings, OCR).

## Layout

| Path | Purpose |
|---|---|
| `backend/` | FastAPI service (API, auth, retrieval, SQL, ingestion, eval) |
| `web/` | Next.js app (chat UI, admin console, BFF routes) |
| `ingest-worker/` | async ingestion workers (shares `backend/app`) |
| `eval-runner/` | nightly evaluation cron container |
| `infra/` | docker-compose, Kubernetes manifests, OTel collector config |
| `.github/workflows/` | CI: lint, typecheck, tests, build |

## Quickstart

Prerequisites: Docker with the Compose plugin. Everything else runs in
containers.

```sh
cp .env.example .env
# Set MOCK_OIDC=2 in .env to enable the persona picker on /login
make up
```

`make up` builds the images, starts Postgres (pgvector), Redis, the API, the
worker, and the web app, runs the schema migrations, and seeds a synthetic
company. Then open <http://localhost:3000>, pick a demo identity, and ask a
question.

Useful targets:

| Command | What it does |
|---|---|
| `make up` | Build and start the full stack |
| `make down` | Stop the stack |
| `make seed` | Re-seed the demo data |
| `make demo-reset` | Re-seed and clear conversation history |
| `make obs` | Start the stack plus Grafana/Tempo/Loki |
| `make lint` | Lint backend (ruff) and web (eslint) |
| `make typecheck` | mypy (backend) and tsc (web) |
| `make test` | Run the full test suite with the coverage gate |

## Auth modes

The backend has no real identity provider in this foundation stage. Two mock
modes cover local development and the public demo:

- `MOCK_OIDC=2` (default) — a persona picker on `/login`; the session is bound
  to the chosen demo identity for the whole conversation.
- `MOCK_OIDC=1` — a static developer principal injected on every request, for
  backend-only work via curl.

The demo data is fully synthetic: a fictional company with departments, people,
projects, assets, objectives, tickets, and a document corpus. No real company
data is used anywhere.

## Codebase answers

The corpus includes a synthetic service repository under
`backend/seed_corpus/code/` (READMEs, ADRs, runbooks, and source files). Code
questions are answered by Codestral over the `code` source type, and every
citation carries a `file:line` anchor that opens a read-only viewer in the chat
transcript. Code chunks are scoped to the Engineering department, like the rest
of the engineering corpus.

## Reingest webhooks

`POST /api/webhooks/ingest` accepts signed source-edit notifications and queues
a reingest on the worker queue. Reingest is idempotent - unchanged chunks are
skipped by content hash - so a redelivered webhook is harmless. The request body
is JSON and the signature is an HMAC-SHA256 of the raw body with
`WEBHOOK_SECRET` as the key, sent as `X-Hub-Signature-256` (or
`X-Webhook-Signature`) in the `sha256=<hex>` form.

- Repository push:
  `{"source": "repo", "ref": "refs/heads/main", "changed": ["services/auth/app.py"]}`.
  Only pushes to `WEBHOOK_BRANCH` (default `main`) trigger a reindex.
- Drive or docs edit:
  `{"source": "drive", "changed": ["file:policies/parental-leave.md"]}`. This
  generic form is the seam for a real integration; no provider-specific client
  ships in this repo.

An unset `WEBHOOK_SECRET` rejects every webhook, and each accepted delivery
appears as a job in the admin console's Ingest tab.

```sh
body='{"source":"repo","ref":"refs/heads/main"}'
sig="sha256=$(printf '%s' "$body" | openssl dgst -sha256 -hmac "$WEBHOOK_SECRET" | awk '{print $2}')"
curl -X POST localhost:8000/api/webhooks/ingest -H "content-type: application/json" \
  -H "x-hub-signature-256: $sig" -d "$body"
```

## Conversation history

History is per user: a signed-in caller only reads, extends, or deletes their
own conversations. With `ENCRYPTION_KEY` set, message bodies and conversation
titles are sealed at rest with AES-256-GCM. Each conversation gets its own data
key, wrapped by the key-encryption key, and every payload is bound to its row
through associated data, so a ciphertext cannot be moved to another row and
still open. Generate a key with:

```sh
python -c "from app.core.crypto import generate_key; print(generate_key())"
```

History written before a key existed stays readable as plaintext. Backfill
seals those rows; rotation rewraps the data keys under a new key without
touching the message bodies:

```sh
make history-backfill            # run with ENCRYPTION_KEY set
make history-rotate OLD_KEY=...  # run with the new ENCRYPTION_KEY set
```

Deleting a conversation, or the whole history, is a hard cascade: messages and
their feedback go, along with eval candidates filed from those messages that
are still awaiting review. Promoted or rejected cases survive with their
redacted prompt. In the web app each conversation row has a delete action and
the Recent header has "Clear all"; both call the owner-scoped API.
