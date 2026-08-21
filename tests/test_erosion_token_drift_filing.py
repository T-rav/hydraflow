"""Pure helpers behind ErosionMetricsLoop's token-drift actuator (#11442).

Candidate construction from a ``token_drift.DriftReport``, the
``token_drift:<source>:<window_key>`` fingerprint, and the rendered issue.
No I/O, no loop — the loop wiring lives in
``tests/test_erosion_metrics_loop_token_drift.py``.
"""

from __future__ import annotations

import pytest

from erosion.token_drift_filing import (
    TOKEN_DRIFT_KIND,
    render_token_drift,
    token_drift_candidates,
    token_drift_fingerprint,
    token_drift_summary,
)
from token_drift import (
    MEDIAN_TOKENS_SOURCE,
    DriftReport,
    DriftStatus,
    DriftVerdict,
    SourceDrift,
)

_WEEK = "2026-W33"


def _drift(
    source: str,
    before: float | None,
    after: float,
    sigma: float | None,
    verdict: DriftVerdict = DriftVerdict.DRIFTING,
) -> SourceDrift:
    return SourceDrift(
        source=source,
        before_share=before,
        after_share=after,
        sigma=sigma,
        verdict=verdict,
    )


def _report(
    *sources: SourceDrift,
    status: DriftStatus = DriftStatus.OK,
    window_key: str | None = _WEEK,
) -> DriftReport:
    return DriftReport(
        status=status, reason="test", sources=list(sources), window_key=window_key
    )


def _candidate(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "kind": TOKEN_DRIFT_KIND,
        "fingerprint": token_drift_fingerprint("implementer", _WEEK),
        "source": "implementer",
        "before_share": 0.41,
        "after_share": 0.60,
        "sigma": 10.716,
        "window_key": _WEEK,
    }
    base.update(overrides)
    return base


def test_fingerprint_is_source_plus_iso_week() -> None:
    assert token_drift_fingerprint("implementer", _WEEK) == (
        "token_drift:implementer:2026-W33"
    )


class TestCandidates:
    def test_one_regular_candidate_per_drifting_chart_only(self) -> None:
        report = _report(
            _drift("implementer", 0.41, 0.60, 10.7),
            _drift("planner", 0.21, 0.22, 0.5, verdict=DriftVerdict.OK),
            _drift("newcomer", None, 0.05, None, verdict=DriftVerdict.UNBASELINED),
            _drift(MEDIAN_TOKENS_SOURCE, 1e5, 1e5, 0.0, verdict=DriftVerdict.OK),
        )

        candidates = token_drift_candidates(report)

        assert candidates == [
            {
                "kind": TOKEN_DRIFT_KIND,
                "fingerprint": "token_drift:implementer:2026-W33",
                "source": "implementer",
                "before_share": 0.41,
                "after_share": 0.60,
                "sigma": 10.7,
                "window_key": _WEEK,
            }
        ]

    def test_two_drifting_sources_yield_two_distinct_fingerprints(self) -> None:
        report = _report(
            _drift("implementer", 0.41, 0.55, 7.9),
            _drift("planner", 0.21, 0.36, 8.5),
        )
        fingerprints = [c["fingerprint"] for c in token_drift_candidates(report)]
        assert fingerprints == [
            "token_drift:implementer:2026-W33",
            "token_drift:planner:2026-W33",
        ]

    @pytest.mark.parametrize(
        "status",
        [DriftStatus.NO_BASELINE, DriftStatus.INSUFFICIENT_DATA, DriftStatus.STALE],
    )
    def test_non_ok_status_yields_nothing_even_with_a_drifting_row(
        self, status: DriftStatus
    ) -> None:
        report = _report(_drift("implementer", 0.41, 0.60, 10.7), status=status)
        assert token_drift_candidates(report) == []

    def test_ok_report_with_no_drifting_chart_yields_nothing(self) -> None:
        report = _report(_drift("implementer", 0.41, 0.42, 0.6, DriftVerdict.OK))
        assert token_drift_candidates(report) == []

    def test_ok_report_without_window_key_yields_nothing(self) -> None:
        """No week → no fingerprint → nothing to dedup on; file nothing."""
        report = _report(_drift("implementer", 0.41, 0.60, 10.7), window_key=None)
        assert token_drift_candidates(report) == []


class TestRender:
    def test_title_names_source_shares_sigma_and_week(self) -> None:
        title, _body = render_token_drift(_candidate())
        assert title == (
            "Token drift: `implementer` share 41.0% → 60.0% (10.7σ) in week 2026-W33"
        )

    def test_body_carries_evidence_table_and_reading_guide(self) -> None:
        _title, body = render_token_drift(_candidate())
        assert body.startswith("## Evidence (ErosionMetricsLoop, automated)")
        for row in (
            "| chart | `implementer` |",
            "| ISO week | 2026-W33 |",
            "| baseline centre | 41.0% |",
            "| observed | 60.0% |",
            "| sigma | 10.7σ |",
            "| verdict | drifting |",
        ):
            assert row in body
        assert "## How to read this" in body
        assert "token_drift:<source>:<week>" in body
        assert "re-pin" in body

    def test_flat_baseline_sigma_none_renders_as_not_available(self) -> None:
        title, body = render_token_drift(_candidate(sigma=None))
        assert "(σ n/a)" in title
        assert "| sigma | σ n/a |" in body

    def test_median_chart_renders_token_counts_not_percentages(self) -> None:
        title, body = render_token_drift(
            _candidate(
                source=MEDIAN_TOKENS_SOURCE,
                fingerprint=token_drift_fingerprint(MEDIAN_TOKENS_SOURCE, _WEEK),
                before_share=100_000.0,
                after_share=150_000.0,
                sigma=4.2,
            )
        )
        assert title == (
            "Token drift: median tokens per issue 100,000 → 150,000 (4.2σ) "
            "in week 2026-W33"
        )
        assert "| baseline centre | 100,000 |" in body
        assert "%" not in title


def test_summary_lists_window_and_drifting_sources() -> None:
    candidates = token_drift_candidates(
        _report(
            _drift("planner", 0.21, 0.36, 8.5),
            _drift("implementer", 0.41, 0.55, 7.9),
        )
    )
    assert token_drift_summary(candidates) == {
        "window_key": _WEEK,
        "drifting": ["planner", "implementer"],
    }
