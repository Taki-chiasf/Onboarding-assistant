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

> Status: early bootstrap. Setup and quickstart instructions land with the
> foundation milestone.

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

Coming soon — `make up` will bring up the full stack once the foundation is in
place.
