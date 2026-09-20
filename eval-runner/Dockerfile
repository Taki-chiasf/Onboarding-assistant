FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app


FROM base AS builder

RUN pip install --no-cache-dir uv
COPY backend/pyproject.toml backend/uv.lock ./
COPY backend/app ./app
RUN uv sync --frozen --no-dev


FROM base AS runtime

RUN useradd --uid 10001 --create-home appuser
COPY --from=builder /app/.venv /app/.venv
COPY backend/app ./app

ENV PATH="/app/.venv/bin:$PATH"

USER appuser

CMD ["python", "-m", "app.eval.runner"]
