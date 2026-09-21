"""Command-line entrypoint for corpus ingestion."""

from __future__ import annotations

import argparse
import asyncio
import logging

from app.ingest.service import run_ingest

logger = logging.getLogger(__name__)


async def _main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest the document corpus into the vector store"
    )
    parser.add_argument(
        "--enqueue",
        action="store_true",
        help="enqueue the job on the worker queue instead of running inline",
    )
    args = parser.parse_args()

    if args.enqueue:
        from app.ingest.tasks import enqueue_corpus

        enqueue_corpus()
        logger.info("enqueued corpus ingestion job")
        return

    result = await run_ingest()
    logger.info("ingested: %s", result)


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
