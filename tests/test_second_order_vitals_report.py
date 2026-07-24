"""Unit tests for the second-order vitals report + endpoint payloads (#10373).

Covers the deterministic Markdown render (verdict explainable from its inputs on
the same page — contributing series + residuals shown), the append-only
``vitals.jsonl`` record shape, and the endpoint's ``latest_verdict_payload``
(honest green default with no history).
"""

from __future__ import annotations

from datetime import UTC, datetime

from vitals.models import (
    SERIES_ESCAPES,
    SERIES_INTERVENTION_CORRECTIONS,
    VitalsThresholds,
)
from vitals.report import (
    latest_verdict_payload,
    render_second_order_vitals_markdown,
    verdict_payload,
    verdict_record,
)
from vitals.verdict import evaluate_vitals

_THRESHOLDS = VitalsThresholds(
    min_baseline_windows=3, sustained_windows=2, watch_k=2, diverging_k=3
)
_BREACHING = [0.0, 0.0, 0.0, 10.0, 10.0]
_FLAT = [0.0, 0.0, 0.0, 0.0, 0.0]


def _diverging_verdict():
    from vitals.models import (
        SERIES_AUDIT_DISAGREEMENT,
        SERIES_EROSION_DUPLICATION,
        SERIES_EROSION_SCATTER,
        SERIES_EROSION_SPREAD,
        SERIES_FAIL_OPEN,
        SERIES_INDEPENDENCE_UNAVAILABLE,
    )

    h = {
        name: list(_FLAT)
        for name in (
            SERIES_EROSION_SPREAD,
            SERIES_EROSION_SCATTER,
            SERIES_EROSION_DUPLICATION,
            SERIES_FAIL_OPEN,
            SERIES_INDEPENDENCE_UNAVAILABLE,
        )
    }
    h[SERIES_ESCAPES] = list(_BREACHING)
    h[SERIES_INTERVENTION_CORRECTIONS] = list(_BREACHING)
    h[SERIES_AUDIT_DISAGREEMENT] = list(_BREACHING)
    return evaluate_vitals(h, primary_health_green=True, thresholds=_THRESHOLDS)


class TestMarkdownRender:
    def test_deterministic_and_explainable(self) -> None:
        verdict = _diverging_verdict()
        now = datetime(2026, 7, 23, tzinfo=UTC)
        a = render_second_order_vitals_markdown(verdict, now=now, window_days=7)
        b = render_second_order_vitals_markdown(verdict, now=now, window_days=7)
        assert a == b  # same inputs → same bytes
        assert "Second-order vitals" in a
        assert "diverging" in a
        assert "5-of-5 reporting" in a
        # The contributing series + residual columns are present (explainable).
        assert "residual" in a
        assert "escapes per window" in a
        assert "UCL" in a


class TestVerdictRecord:
    def test_record_shape(self) -> None:
        verdict = _diverging_verdict()
        row = verdict_record(verdict, ts="2026-07-23T00:00:00+00:00")
        assert row["verdict"] == "diverging"
        assert row["k"] == 3
        assert row["reporting_families"] == 5
        assert row["total_families"] == 5
        assert set(row["breaching_families"]) == {"escapes", "intervention", "audit"}


class TestEndpointPayload:
    def test_full_payload_has_family_breakdown(self) -> None:
        payload = verdict_payload(_diverging_verdict())
        assert payload["verdict"] == "diverging"
        assert payload["coverage_label"] == "5-of-5 reporting"
        assert len(payload["families"]) == 5
        assert all("series" in fam for fam in payload["families"])

    def test_latest_payload_defaults_green_with_no_history(self) -> None:
        payload = latest_verdict_payload([])
        assert payload["verdict"] == "green"
        assert payload["reporting_families"] == 0
        assert payload["total_families"] == 5

    def test_latest_payload_returns_most_recent(self) -> None:
        records = [
            {"ts": "1", "verdict": "green"},
            {"ts": "2", "verdict": "watch"},
            {"ts": "3", "verdict": "diverging"},
        ]
        assert latest_verdict_payload(records)["verdict"] == "diverging"
