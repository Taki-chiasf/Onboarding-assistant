# Reranker latency benchmark

The cross-encoder rerank step sits on the turn-1 answer path, so its latency
must fit inside the first-token budget (2.5s). This document records the
benchmark methodology and the model decision for the retrieval rerank stage.

## Context

- Hybrid retrieval produces top-20/30 candidate chunks per query.
- The reranker scores each (query, chunk) pair and reorders candidates before
  the top-k cutoff.
- The target demo host is a shared-vCPU box, so CPU latency dominates.

## Models under test

| Model | Params | Notes |
|---|---|---|
| `BAAI/bge-reranker-v2-m3` | ~568M | Higher quality, notably slower on CPU |
| `BAAI/bge-reranker-base` | ~278M | Faster, adequate for top-k reordering |

## Methodology

`scripts/bench_reranker.py` builds realistic (query, chunk) pairs from the
synthetic corpus, then times `CrossEncoder.predict` over top-20 and top-30
batches across several queries. Run it pinned to a single core to emulate a
shared-vCPU demo box:

```sh
cd backend
uv sync --group bench
taskset -c 0 uv run python scripts/bench_reranker.py --rounds 10
```

The script reports p50 and p95 latency per (model, batch size).

## Decision

**Status: provisional — timing run pending.** The benchmark has not been
executed against the actual demo-tier CPU yet; the local run was deferred to
avoid a multi-gigabyte model download in the development environment, and the
real number must come from the demo host anyway.

Provisional guidance for the retrieval stage:

- Start with `BAAI/bge-reranker-base` (278M). It is the safer default on a
  shared-vCPU host.
- If rerank latency alone would exceed ~600ms of the first-token budget, drop
  the cross-encoder stage for the MVP and rely on hybrid retrieval top-k only.
- Upgrade to `BAAI/bge-reranker-v2-m3` only if the demo host has headroom.

Re-run the benchmark during retrieval implementation and update this file with
the measured numbers and the final decision.
