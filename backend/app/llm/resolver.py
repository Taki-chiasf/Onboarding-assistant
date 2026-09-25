"""Keeps a rejected model from being retried on every request.

The preferred model for each role stays configured as the first choice. A
subscription tier may not grant access to every model, in which case the provider
rejects the call before producing any output. When that happens the rejection is
recorded here, so the rest of the process goes straight to a model the tier does
serve instead of paying a failed call per request.
"""

from __future__ import annotations

import logging

from app.llm.models import ModelConfig

logger = logging.getLogger(__name__)

# Header carrying the per-minute request ceiling granted to the key.
_QUOTA_HEADER = "x-ratelimit-limit-req-minute"


def is_model_unavailable(error: BaseException) -> bool:
    """True when the error means this model cannot serve the call at all.

    A throttled but healthy model reports a non-zero ceiling, so it is left to the
    caller to retry rather than being treated as unavailable.
    """
    status = getattr(error, "status_code", None)
    if status == 403:
        return True
    if status == 400:
        return "invalid model" in str(getattr(error, "body", "")).lower()
    if status == 429:
        headers = getattr(error, "headers", None)
        if headers is not None and headers.get(_QUOTA_HEADER) == "0":
            return True
    return False


def is_transient_throttle(error: BaseException) -> bool:
    """True when the call hit a real per-minute ceiling that will refill.

    Distinct from an unavailable model: waiting is the correct response here,
    whereas a locked-out model only needs a different one.
    """
    if getattr(error, "status_code", None) != 429 or is_model_unavailable(error):
        return False
    headers = getattr(error, "headers", None)
    retry_after = headers.get("retry-after") if headers is not None else None
    if retry_after is not None:
        try:
            return float(retry_after) > 0
        except ValueError:
            return True
    return True


class ModelResolver:
    """Maps a configured model to the chain of models that may replace it."""

    def __init__(self, config: ModelConfig) -> None:
        self._pools = self._build_pools(config)
        self._replacements: dict[str, str] = {}

    @staticmethod
    def _build_pools(config: ModelConfig) -> dict[str, list[str]]:
        """Collect, per model, every model configured as a stand-in for it.

        A stand-in is often shared between roles, so the pool for a model is the
        ordered union of the chains it appears in, with the model itself first.
        """
        pools: dict[str, list[str]] = {}
        for role, fallbacks in config.fallbacks.items():
            primary = config.models.get(role)
            if primary is None:
                continue
            for model_id in (primary, *fallbacks):
                pool = pools.setdefault(model_id, [])
                for candidate in (primary, *fallbacks):
                    if candidate not in pool:
                        pool.append(candidate)
        return pools

    def chain(self, model: str) -> list[str]:
        """Return the ordered candidates for a model, starting where we left off.

        Candidates already passed are dropped, so a rejected model is never tried
        a second time in the same or a later call.
        """
        pool = self._pools.get(model, [model])
        replacement = self._replacements.get(model)
        if replacement is None or replacement not in pool:
            return pool
        return pool[pool.index(replacement) :]

    def demote(self, model: str, failed: str) -> str | None:
        """Record that a candidate is unusable and return the one to try next.

        Returns None once the chain is exhausted, so the caller stops rather than
        looping back to a model already known to be unusable.
        """
        chain = self.chain(model)
        if failed not in chain:
            return None
        remaining = chain[chain.index(failed) + 1 :]
        if not remaining:
            return None
        replacement = remaining[0]
        self._replacements[model] = replacement
        logger.warning("model %s unavailable, falling back to %s", failed, replacement)
        return replacement

    def reset(self, model: str) -> None:
        """Forget a demotion so the preferred model is tried again."""
        self._replacements.pop(model, None)
