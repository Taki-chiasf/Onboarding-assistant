"""Benchmark cross-encoder rerankers on CPU against realistic corpus chunks.

The reranker sits on the turn-1 answer path, so its latency must fit inside the
first-token budget. This script scores top-20 and top-30 candidate batches with
each model and reports p50/p95 latency. Run it pinned to a single core to
emulate a shared-vCPU demo box:

    taskset -c 0 uv run python scripts/bench_reranker.py
"""

from __future__ import annotations

import argparse
import statistics
import time
from pathlib import Path
from typing import Any

from app.rag import chunk_markdown
from scripts.corpus import CATEGORIES

CORPUS_ROOT = Path(__file__).resolve().parents[1] / "seed_corpus"

QUERIES = [
    "How many weeks of parental leave do employees receive?",
    "What is the daily meal reimbursement limit during travel?",
    "How do I set up my laptop on the first day?",
    "What are the core collaboration hours?",
    "How do I report a suspected phishing attempt?",
]

BATCH_SIZES = (20, 30)


def load_passages() -> list[str]:
    passages: list[str] = []
    for category, docs in CATEGORIES.items():
        for filename, content in docs:
            chunks = chunk_markdown(
                f"file:{category}/{filename}", category, content, ["dept:all"]
            )
            passages.extend(chunk.content for chunk in chunks)
    return passages


def _measure(model: Any, query: str, passages: list[str], batch: int, rounds: int) -> list[float]:
    samples: list[float] = []
    pairs = [(query, passage) for passage in passages[:batch]]
    for _ in range(rounds):
        start = time.perf_counter()
        model.predict(pairs)
        samples.append((time.perf_counter() - start) * 1000)
    return samples


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark cross-encoder rerankers")
    parser.add_argument(
        "--models",
        nargs="+",
        default=["BAAI/bge-reranker-v2-m3", "BAAI/bge-reranker-base"],
        help="reranker model ids to benchmark",
    )
    parser.add_argument("--rounds", type=int, default=10, help="timing rounds per batch")
    args = parser.parse_args()

    from sentence_transformers import CrossEncoder

    passages = load_passages()
    print(f"passages loaded: {len(passages)}")

    for model_id in args.models:
        model = CrossEncoder(model_id)
        model.predict([(QUERIES[0], passages[0])])  # warm up
        print(f"\n{model_id}")
        for batch in BATCH_SIZES:
            latencies: list[float] = []
            for query in QUERIES:
                latencies.extend(_measure(model, query, passages, batch, args.rounds))
            latencies.sort()
            p50 = statistics.median(latencies)
            p95 = statistics.quantiles(latencies, n=20)[18]  # 19th of 20 = p95
            mean = statistics.mean(latencies)
            print(f"  top-{batch}: p50={p50:.0f}ms  p95={p95:.0f}ms  mean={mean:.0f}ms")


if __name__ == "__main__":
    main()
