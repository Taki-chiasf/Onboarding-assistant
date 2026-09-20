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
