FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app


FROM base AS builder

RUN pip install --no-cache-dir uv
COPY pyproject.toml uv.lock ./
COPY app ./app
RUN uv sync --frozen --no-dev


FROM base AS runtime

RUN useradd --uid 10001 --create-home appuser
COPY --from=builder /app/.venv /app/.venv
COPY app ./app
COPY scripts ./scripts
COPY alembic.ini entrypoint.sh ./
COPY migrations ./migrations

ENV PATH="/app/.venv/bin:$PATH"

RUN chmod +x /app/entrypoint.sh

USER appuser
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/healthz').status==200 else 1)"

ENTRYPOINT ["/app/entrypoint.sh"]
