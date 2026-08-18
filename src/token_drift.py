"""Minimal token-share drift verdict engine — frozen entry point for #11441.

**v1, PROVISIONAL** (mirrors ``erosion_metrics_loop``'s framing) — #11442's
filing actuator needs a queryable verdict shape
``{source, before_share, after_share, sigma, verdict}`` before #11441 (the
salvage engine issue) lands; this module is that minimal, contract-conforming
entry point, so #11441 can EXTEND it (a real pinned baseline persisted across
ticks, the eventual replacement for the in-window split below) rather than
rewrite it.

No I/O here — mirrors ``token_report.py``'s "pure math over rows" discipline;
the actuator (``token_drift_filing.py``) owns loading.

Drift definition: split a trailing window of inference rows (oldest-first,
the ``PromptTelemetry.load_inferences`` contract) at its midpoint into an
older 'before' half and a newer 'after' half, roll each half up into a
per-source token share, and flag any source whose share GREW past the
ADR-0133 widened control band — adverse-when-high only, mirroring
``vitals``'s "only the upper limit matters" convention (a shrinking share is
never a drift signal here).

``sigma`` is a two-proportion z-score (pooled-proportion test statistic) for
how many standard errors ``after_share`` sits above ``before_share``. The
verdict boundary is ``vitals_methodology.widened_sigma_multiplier(n)`` —
NEVER a hardcoded ``3.0`` (the exact regression #11303/#11307 stalled on;
see ``docs/wiki/gotchas.md``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from vitals_methodology import widened_sigma_multiplier

VERDICT_STABLE = "stable"
VERDICT_DRIFT = "drift"

# Need at least one row on each side of the before/after split to compare.
_MIN_ROWS_FOR_COMPARISON = 2


@dataclass(frozen=True)
class TokenDriftVerdict:
    """One source's before/after token-share comparison (the frozen contract)."""

    source: str
    before_share: float
    after_share: float
    sigma: float
    verdict: str

    @property
    def is_drift(self) -> bool:
        return self.verdict == VERDICT_DRIFT


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _row_tokens(row: dict[str, Any]) -> int:
    """Billable-ish token weight for a row: actual when present, else estimate."""
    total = _as_int(row.get("total_tokens"))
    if total > 0:
        return total
    return _as_int(row.get("total_est_tokens"))


def _source_tokens(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Per-source token totals over *rows* — this module's own tally, not
    ``token_report.build_token_report``'s issue-capped/filtered rollup, which
    serves a different, dashboard-legibility purpose."""
    totals: dict[str, int] = {}
    for row in rows:
        source = str(row.get("source", "?"))
        totals[source] = totals.get(source, 0) + _row_tokens(row)
    return totals


def _two_proportion_sigma(x1: int, n1: int, x2: int, n2: int) -> float:
    """Two-proportion z-score for ``x2/n2`` sitting above ``x1/n1``.

    Standard pooled-proportion test statistic. ``0.0`` (no evidence) when the
    pooled proportion is degenerate (0 or 1 — no dispersion to divide by).
    """
    p_pool = (x1 + x2) / (n1 + n2)
    if p_pool <= 0.0 or p_pool >= 1.0:
        return 0.0
    se = (p_pool * (1.0 - p_pool) * (1.0 / n1 + 1.0 / n2)) ** 0.5
    if se <= 0.0:
        return 0.0
    return ((x2 / n2) - (x1 / n1)) / se


def compute_token_drift(
    rows: list[dict[str, Any]], *, n_instruments: int | None = None
) -> list[TokenDriftVerdict]:
    """Compare an older 'before' half of *rows* against the newer 'after' half.

    Returns one verdict per source seen in either half — a source present in
    one window and absent from the other reads as a 0.0 share there (a
    legitimate drift signal, not missing data). Returns ``[]`` when there
    isn't enough data to compare (fewer than two rows, or either half's total
    token count is zero).

    ``n_instruments`` is the count of registered drift instruments (charts)
    fed to ``widened_sigma_multiplier`` per ADR-0133 — defaults to the number
    of distinct sources observed, floored at 1.
    """
    if len(rows) < _MIN_ROWS_FOR_COMPARISON:
        return []
    midpoint = len(rows) // 2
    before_tokens = _source_tokens(rows[:midpoint])
    after_tokens = _source_tokens(rows[midpoint:])
    before_total = sum(before_tokens.values())
    after_total = sum(after_tokens.values())
    if before_total <= 0 or after_total <= 0:
        return []

    sources = sorted(set(before_tokens) | set(after_tokens))
    n = n_instruments if n_instruments is not None else max(len(sources), 1)
    multiplier = widened_sigma_multiplier(n)

    verdicts: list[TokenDriftVerdict] = []
    for source in sources:
        x1 = before_tokens.get(source, 0)
        x2 = after_tokens.get(source, 0)
        before_share = x1 / before_total
        after_share = x2 / after_total
        sigma = _two_proportion_sigma(x1, before_total, x2, after_total)
        verdict = VERDICT_DRIFT if sigma > multiplier else VERDICT_STABLE
        verdicts.append(
            TokenDriftVerdict(
                source=source,
                before_share=round(before_share, 4),
                after_share=round(after_share, 4),
                sigma=round(sigma, 3),
                verdict=verdict,
            )
        )
    return verdicts
