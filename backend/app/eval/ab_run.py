"""A/B comparison command line.

Measures two router providers (local open weights against the hosted small
model) or two SQL generators (incumbent against challenger) on the golden sets
and applies the adoption rule. Needs the corresponding model access: a key for
the hosted path, and Ollama serving the local router for the local path.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from collections.abc import Callable, Coroutine, Sequence
from typing import Any

logger = logging.getLogger(__name__)


async def _router_ab(args: argparse.Namespace) -> int:
    from app.core.config import get_settings
    from app.eval.ab import measure_router, router_ab_result
    from app.eval.router_golden import build_router_set
    from app.llm.client import get_provider
    from app.llm.local import LocalProvider
    from app.router.router import IntentRouter

    settings = get_settings()
    cases = build_router_set()
    local_router = IntentRouter(LocalProvider(settings.ollama_base_url), args.local_model)
    api_router = IntentRouter(get_provider(), args.api_model)

    local = await measure_router(local_router, cases, label="local", model=args.local_model)
    api = await measure_router(api_router, cases, label="api", model=args.api_model)
    print(json.dumps(router_ab_result(local, api).to_dict(), indent=2))
    return 0


async def _sql_ab(args: argparse.Namespace) -> int:
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import get_settings
    from app.eval.ab import measure_sql, sql_ab_result
    from app.eval.sql_golden import build_sql_set
    from app.llm.client import get_provider
    from app.text_to_sql.builder import SqlBuilder
    from app.text_to_sql.executor import SqlExecutor

    settings = get_settings()
    if not settings.database_url or not settings.mistral_api_key:
        raise SystemExit("DATABASE_URL and MISTRAL_API_KEY are required for the SQL A/B")

    cases = build_sql_set()
    provider = get_provider()
    engine = create_async_engine(settings.database_url)
    executor = SqlExecutor(
        engine,
        readonly_role=settings.sql_readonly_role,
        statement_timeout_ms=settings.sql_statement_timeout_ms,
        max_rows=settings.sql_max_rows,
    )
    try:
        incumbent = await measure_sql(
            SqlBuilder(provider, args.incumbent),
            executor,
            cases,
            label="incumbent",
            model=args.incumbent,
        )
        challenger = await measure_sql(
            SqlBuilder(provider, args.challenger),
            executor,
            cases,
            label="challenger",
            model=args.challenger,
        )
    finally:
        await engine.dispose()
    print(json.dumps(sql_ab_result(incumbent, challenger).to_dict(), indent=2))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a model A/B comparison")
    subparsers = parser.add_subparsers(dest="command", required=True)

    router = subparsers.add_parser("router", help="local router vs hosted router")
    router.add_argument("--local-model", default="ministral-3:8b")
    router.add_argument("--api-model", default="mistral-small-2603")
    router.set_defaults(func=_router_ab)

    sql = subparsers.add_parser("sql", help="incumbent vs challenger SQL generator")
    sql.add_argument("--incumbent", default="mistral-large-2512")
    sql.add_argument("--challenger", default="magistral-small-2509")
    sql.set_defaults(func=_sql_ab)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    handler: Callable[[argparse.Namespace], Coroutine[Any, Any, int]] = args.func
    return asyncio.run(handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
