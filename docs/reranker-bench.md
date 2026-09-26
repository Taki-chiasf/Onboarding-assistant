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

**Status: decided — cross-encoder off for the MVP.**

Measured on one pinned core against the 168-chunk synthetic corpus
(`BAAI/bge-reranker-base`, 10 rounds per query, 5 queries):

| Batch | p50 | p95 | mean |
|---|---|---|---|
| top-20 | 1857ms | 1983ms | 1852ms |
| top-30 | 2769ms | 2998ms | 2774ms |

`BAAI/bge-reranker-v2-m3` was not run: it is the larger, slower model, so it
cannot beat these numbers on the same host.

Both batch sizes exceed the ~600ms re-rank budget, and top-30 also exceeds the
2.5s first-token budget on its own. The cross-encoder stage therefore stays out
of the MVP answer path: retrieval uses hybrid top-k ranking only, and the
`CrossEncoderReranker` seam remains available for a host with CPU headroom. A
GPU-backed host is the only realistic way to bring a cross-encoder inside the
first-token budget, so this is revisited if the demo moves to GPU.

The number must be re-confirmed on the actual demo host before any reranker is
enabled there.

