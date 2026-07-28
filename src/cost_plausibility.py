"""Cost-plausibility guard (#10775) — an aggregate net for mis-billing.

Motivation (the z.ai/GLM 6-8x lesson, #10761): ``ModelRate.estimate_cost``
correctness depends on each backend's usage semantics (does ``input_tokens``
include cached tokens?). A per-backend mismatch can silently over-report cost
6-8x before it reaches the operator's cost panel. The per-backend
*conformance tests* (``tests/regressions/test_issue_10775_cost_backend_conformance.py``)
pin each backend's usage semantics — that is the specific defense. This guard
is the complementary *aggregate net*: a cheap, model-agnostic check on the
already-aggregated cost surface that flags the broader class of gross
mis-billing (rate-scale typos, tokens billed but never counted) that no
single conformance test would catch.

The check: a model's **effective** per-token rate — total billed cost divided
by total tokens — is a token-weighted average of that model's own table
rates, so for ANY correctly billed record it can never exceed the model's
**peak** per-token rate (the largest of input / output / cache-write /
cache-read). An effective rate that exceeds the peak by more than a
configurable factor ``K`` means cost was billed against tokens that are NOT
represented in the token totals. Because the weighted-average <= peak identity
holds for every correct billing regardless of workload mix or backend
semantics, the guard has NO false positives from an expensive output-heavy run
— only a genuine over-bill can cross it.

It is a SOFT signal: :func:`check_cost_plausibility` returns a structured
anomaly (or ``None``); callers log a WARNING and surface it on the cost row.
It never raises and never zeroes a cost. ``K`` is operator-tunable via
``cost_plausibility_max_rate_multiple`` /
``HYDRAFLOW_COST_PLAUSIBILITY_MAX_RATE_MULTIPLE``.
"""

from __future__ import annotations

from dataclasses import dataclass

from model_pricing import ModelRate

#: Default ``K``. A correctly billed record's effective rate is always
#: <= peak (ratio <= 1.0), so any K >= 1.0 is false-positive-free on clean
#: data; 3.0 leaves generous headroom for buckets that mix real-token rows
#: with char-estimate fallback rows (which contribute cost but zero tokens),
#: so only a gross over-bill (>3x the most expensive table rate) is flagged.
DEFAULT_MAX_RATE_MULTIPLE = 3.0


@dataclass(frozen=True, slots=True)
class CostPlausibilityAnomaly:
    """A flagged divergence between a model's effective and peak table rate."""

    model: str
    effective_rate_per_million: float
    peak_rate_per_million: float
    ratio: float
    threshold: float
    cost_usd: float
    total_tokens: int

    def as_dict(self) -> dict[str, float | str | int]:
        """JSON-serializable form for surfacing on a cost row / in logs."""
        return {
            "model": self.model,
            "effective_rate_per_million": round(self.effective_rate_per_million, 6),
            "peak_rate_per_million": round(self.peak_rate_per_million, 6),
            "ratio": round(self.ratio, 4),
            "threshold": round(self.threshold, 4),
            "cost_usd": round(self.cost_usd, 6),
            "total_tokens": self.total_tokens,
        }


def check_cost_plausibility(
    *,
    model: str,
    cost_usd: float,
    total_tokens: int,
    rate: ModelRate | None,
    threshold: float = DEFAULT_MAX_RATE_MULTIPLE,
) -> CostPlausibilityAnomaly | None:
    """Flag a model whose effective $/token implausibly exceeds its peak rate.

    Returns a :class:`CostPlausibilityAnomaly` when
    ``effective_rate > threshold * peak_rate``, else ``None``. Skips silently
    (returns ``None``) when the model is unpriced, when there is no positive
    cost or token count to reason about, or when the threshold is non-positive
    — all cases where the ratio is undefined or meaningless rather than
    anomalous.

    ``total_tokens`` is the sum of the four token buckets (input + output +
    cache-read + cache-write) as recorded on the cost surface.
    """
    if rate is None or cost_usd <= 0 or total_tokens <= 0 or threshold <= 0:
        return None
    peak = rate.peak_rate_per_million()
    if peak <= 0:
        return None
    effective = cost_usd / total_tokens * 1_000_000
    if effective <= threshold * peak:
        return None
    return CostPlausibilityAnomaly(
        model=model,
        effective_rate_per_million=effective,
        peak_rate_per_million=peak,
        ratio=effective / peak,
        threshold=threshold,
        cost_usd=cost_usd,
        total_tokens=total_tokens,
    )
