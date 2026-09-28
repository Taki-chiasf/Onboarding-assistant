"""Nightly alert text and webhook delivery.

The alert summarizes gate failures, regressions against the last green run at
the same version pair, and failing promoted cases. Delivery is a single
incoming-webhook POST with a Slack-compatible payload; a failed delivery is
logged and never raises. Deep links into the run land with the admin console.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import httpx

from app.eval.baseline import BaselineComparison, MetricDelta
from app.eval.report import RunReport

logger = logging.getLogger(__name__)


def format_regression(delta: MetricDelta) -> str:
    if delta.baseline:
        change = f"{(delta.delta / abs(delta.baseline)) * 100:+.1f}%"
    else:
        change = f"{delta.delta:+.4f}"
    return f"{delta.name}: {delta.baseline:.4f} -> {delta.current:.4f} ({change})"


def build_alert(
    *,
    green: bool,
    keyless: bool,
    streak: int,
    report: RunReport,
    regression: BaselineComparison | None,
    promoted_total: int,
    promoted_failed: int,
) -> str | None:
    """Return the alert text, or None when the night is green and unremarkable."""
    regressions = list(regression.regressions) if regression is not None else []
    if green and not regressions and promoted_failed == 0:
        return None

    lines = [f"Nightly eval {'GREEN' if green else 'RED'} — {streak} consecutive green night(s)"]
    if keyless:
        lines.append("keyless smoke run: model-quality metrics were not evaluated")
    for outcome in report.gates.failed:
        operator = ">=" if outcome.direction == "min" else "<="
        lines.append(
            f"gate failed: {outcome.name} = {outcome.value:.4f} "
            f"(target {operator} {outcome.target})"
        )
    if regression is not None and regression.stale:
        lines.append(f"baseline stale: {regression.reason}")
    for delta in regressions:
        lines.append(f"regression vs last green: {format_regression(delta)}")
    if promoted_total:
        lines.append(f"promoted cases: {promoted_total - promoted_failed}/{promoted_total} passing")
    return "\n".join(lines)


async def post_alert(
    webhook_url: str, text: str, *, client: httpx.AsyncClient | None = None
) -> bool:
    """Post the alert; never raises, returns whether the webhook accepted it."""
    try:
        if client is not None:
            response = await client.post(webhook_url, json={"text": text})
        else:
            async with httpx.AsyncClient(timeout=10.0) as owned:
                response = await owned.post(webhook_url, json={"text": text})
    except Exception:  # noqa: BLE001 - an alert must never break the night
        logger.warning("eval alert could not be posted", exc_info=True)
        return False
    if not response.is_success:
        logger.warning("eval alert webhook returned %s", response.status_code)
    return response.is_success


def summarize_failures(
    checks: Sequence[tuple[str, bool | None]], *, error: str | None = None
) -> str | None:
    failed = [name for name, value in checks if value is False]
    if not failed and error is None:
        return None
    parts = [f"failed: {', '.join(failed)}"] if failed else []
    if error:
        parts.append(error)
    return "; ".join(parts)
