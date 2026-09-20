SHELL := /bin/bash
.DEFAULT_GOAL := help

COMPOSE := docker compose

.PHONY: help up down obs logs ps seed demo-reset \
        install backend-install web-install \
        lint fmt typecheck test test-backend test-web

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-18s %s\n", $$1, $$2}'

up: ## Build and start the full stack
	$(COMPOSE) up --build -d

down: ## Stop the stack
	$(COMPOSE) down

obs: ## Start the stack plus the observability profile (Grafana, Tempo, Loki)
	$(COMPOSE) --profile observability up --build -d

logs: ## Tail logs for all services
	$(COMPOSE) logs -f

ps: ## Show running services
	$(COMPOSE) ps

seed: ## (Re)seed the database with demo data
	$(COMPOSE) run --rm db-seed

demo-reset: ## Reset demo data and clear conversation history
	$(COMPOSE) run --rm db-seed --reset

install: backend-install web-install ## Install all dependencies

backend-install: ## Install Python dependencies via uv
	cd backend && uv sync

web-install: ## Install JS dependencies via npm
	cd web && npm ci

lint: ## Lint backend and web
	cd backend && uv run ruff check .
	cd web && npm run lint

fmt: ## Format backend and web
	cd backend && uv run ruff format .
	cd web && npm run format

typecheck: ## Type-check backend and web
	cd backend && uv run mypy .
	cd web && npm run typecheck

test: test-backend test-web ## Run all tests

test-backend: ## Run backend tests with the coverage gate
	cd backend && uv run pytest --cov=app --cov-fail-under=80

test-web: ## Run web tests
	cd web && npm run test -- --run
