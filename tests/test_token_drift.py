"""Unit tests for src/token_drift.py — minimal drift verdict engine (#11442).

Frozen entry point for #11441 (salvage): {source, before_share, after_share,
sigma, verdict} per source, computed by splitting a trailing window of
inference rows into an older 'before' half and a newer 'after' half.
"""

from __future__ import annotations

import pytest

import token_drift
from token_drift import VERDICT_DRIFT, VERDICT_STABLE, compute_token_drift


def _row(source: str, tokens: int) -> dict:
    return {"issue_number": 1, "source": source, "total_tokens": tokens}


class TestComputeTokenDrift:
    def test_stable_when_shares_unchanged(self) -> None:
        rows = [_row("implementer", 1000), _row("planner", 1000)] * 20

        verdicts = compute_token_drift(rows)

        assert verdicts
        assert all(v.verdict == VERDICT_STABLE for v in verdicts)
        assert all(v.sigma == 0.0 for v in verdicts)

    def test_drift_when_share_grows_past_band(self) -> None:
        before = [_row("implementer", 100), _row("planner", 100)] * 50
        after = [_row("implementer", 900), _row("planner", 100)] * 50
        rows = before + after

        verdicts = {v.source: v for v in compute_token_drift(rows)}

        assert verdicts["implementer"].verdict == VERDICT_DRIFT
        assert verdicts["implementer"].before_share == 0.5
        assert verdicts["implementer"].after_share == 0.9
        assert verdicts["planner"].verdict == VERDICT_STABLE

    def test_too_few_rows_returns_empty_list(self) -> None:
        assert compute_token_drift([]) == []
        assert compute_token_drift([_row("implementer", 100)]) == []

    def test_zero_token_totals_returns_empty_list(self) -> None:
        rows = [_row("implementer", 0), _row("implementer", 0)]

        assert compute_token_drift(rows) == []

    def test_source_absent_from_before_half_reads_as_zero_share(self) -> None:
        before = [_row("planner", 100)] * 50
        after = [_row("planner", 100), _row("new_source", 900)] * 25
        rows = before + after

        verdicts = {v.source: v for v in compute_token_drift(rows)}

        assert verdicts["new_source"].before_share == 0.0
        assert verdicts["new_source"].after_share == pytest.approx(0.9)
        assert verdicts["new_source"].verdict == VERDICT_DRIFT

    def test_uses_widened_sigma_multiplier_not_hardcoded_three(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression pin (#11307/#11303 gotcha): the drift/stable boundary MUST
        come from vitals_methodology.widened_sigma_multiplier, never a bare 3.0.
        A case that drifts under the real multiplier must go stable once the
        multiplier is patched to something enormous."""
        before = [_row("implementer", 100), _row("planner", 100)] * 50
        after = [_row("implementer", 300), _row("planner", 100)] * 50
        rows = before + after

        drifted = {v.source: v for v in compute_token_drift(rows)}
        assert drifted["implementer"].verdict == VERDICT_DRIFT

        monkeypatch.setattr(token_drift, "widened_sigma_multiplier", lambda *_: 1000.0)
        stabilized = {v.source: v for v in compute_token_drift(rows)}
        assert stabilized["implementer"].verdict == VERDICT_STABLE
