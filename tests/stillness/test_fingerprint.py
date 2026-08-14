"""Unit tests for the oscillation-fingerprint pure computation (#10820)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from stillness.fingerprint import (
    Fingerprint,
    IssueRecord,
    LoopInfo,
    MergeRecord,
    Origin,
    classify_origin,
    fast_tick_loops,
    finder_activity,
    finder_key,
    rank_flux_carriers,
    render_report,
    rework_ratio,
    saturation_markers,
    trend_slope,
    verdict_flapping,
    weekly_self_sourced_fraction,
)

NOW = datetime(2026, 8, 1, tzinfo=UTC)


def _iss(
    n: int, days_ago: int, labels: tuple[str, ...], author: str = "bot"
) -> IssueRecord:
    return IssueRecord(
        number=n,
        created_at=NOW - timedelta(days=days_ago),
        labels=labels,
        author=author,
    )


# --- origin classification (label-based proxy) ------------------------------


def test_finder_label_is_self_even_when_human_authored() -> None:
    # The factory files under a human token; author must NOT decide origin.
    assert classify_origin(("hydraflow-find",)) is Origin.SELF


def test_hitl_escalation_is_self() -> None:
    assert classify_origin(("hitl-escalation",)) is Origin.SELF


def test_pipeline_label_is_pipeline() -> None:
    assert classify_origin(("hydraflow-plan",)) is Origin.PIPELINE


def test_unlabelled_is_external() -> None:
    assert classify_origin(()) is Origin.EXTERNAL


def test_finder_key_prefers_colabel() -> None:
    assert finder_key(("hydraflow-find", "sampled-audit")) == "sampled-audit"


def test_finder_key_falls_back_to_generic() -> None:
    assert finder_key(("hydraflow-find",)) == "hydraflow-find"


# --- series 1: self-sourced fraction ----------------------------------------


def test_weekly_self_fraction_buckets_and_ratio() -> None:
    issues = [
        _iss(1, 2, ("hydraflow-find",)),
        _iss(2, 3, ("hydraflow-plan",)),
        _iss(3, 4, ()),
    ]
    pts = weekly_self_sourced_fraction(issues, now=NOW, weeks=8)
    assert len(pts) == 1
    p = pts[0]
    assert (p.self_count, p.pipeline_count, p.external_count) == (1, 1, 1)
    assert abs(p.self_fraction - 1 / 3) < 1e-9


def test_weekly_excludes_out_of_window() -> None:
    issues = [_iss(1, 100, ("hydraflow-find",))]  # older than 8 weeks
    assert weekly_self_sourced_fraction(issues, now=NOW, weeks=8) == []


def test_trend_slope_rising() -> None:
    # Early week all-pipeline (0% self), recent week all-find (100% self).
    issues = [
        _iss(1, 50, ("hydraflow-plan",)),
        _iss(2, 3, ("hydraflow-find",)),
    ]
    pts = weekly_self_sourced_fraction(issues, now=NOW, weeks=8)
    assert trend_slope(pts) > 0


# --- series 2: rework ratio -------------------------------------------------


def test_rework_counts_overlap_within_14d() -> None:
    merges = [
        MergeRecord("a", NOW - timedelta(days=10), ("src/x.py",)),
        MergeRecord("b", NOW - timedelta(days=3), ("src/x.py", "src/y.py")),  # rework
        MergeRecord("c", NOW - timedelta(days=1), ("src/z.py",)),  # fresh
    ]
    r = rework_ratio(merges, now=NOW, weeks=8, window_days=14)
    assert r.total_merges == 3
    assert r.reworked_merges == 1
    assert ("src/x.py", 1) in r.hot_paths


def test_rework_excludes_regen_artifacts_by_default() -> None:
    # Two merges both touching only a regen artifact — must NOT count as rework.
    merges = [
        MergeRecord(
            "a", NOW - timedelta(days=5), ("docs/arch/generated/changelog.md",)
        ),
        MergeRecord(
            "b", NOW - timedelta(days=1), ("docs/arch/generated/changelog.md",)
        ),
    ]
    r = rework_ratio(merges, now=NOW, weeks=8)
    assert r.reworked_merges == 0
    # But with the exclusion off, they DO overlap (proves the artifact was the cause).
    r_raw = rework_ratio(merges, now=NOW, weeks=8, ignore_generated=False)
    assert r_raw.reworked_merges == 1


def test_rework_ignores_overlap_older_than_window() -> None:
    merges = [
        MergeRecord("a", NOW - timedelta(days=40), ("src/x.py",)),
        MergeRecord("b", NOW - timedelta(days=1), ("src/x.py",)),  # 39d apart > 14d
    ]
    r = rework_ratio(merges, now=NOW, weeks=8, window_days=14)
    assert r.reworked_merges == 0


def test_rework_counts_prior_merge_before_window_start() -> None:
    # A rework merge just INSIDE the window whose prior touch landed just BEFORE
    # window_start (within 14d). It must count — the caller supplies the lookback
    # merges — even though the prior merge is outside the report window.
    two_weeks = timedelta(weeks=2)
    window_start = NOW - two_weeks
    merges = [
        MergeRecord("prior", window_start - timedelta(days=3), ("src/hot.py",)),
        MergeRecord("report", window_start + timedelta(days=2), ("src/hot.py",)),
    ]
    r = rework_ratio(merges, now=NOW, weeks=2, window_days=14)
    assert r.total_merges == 1  # only the in-window merge counts toward totals
    assert r.reworked_merges == 1  # but it sees the pre-window prior touch


# --- series 3: verdict flapping ---------------------------------------------


def test_flapping_zero_is_fleet_level_evidence() -> None:
    r = verdict_flapping([], {}, probe_start=NOW - timedelta(days=20), probe_end=NOW)
    assert r.total_escalations == 0
    assert r.is_fleet_level_evidence is True


def test_flapping_parses_stages_and_probe_window() -> None:
    esc = [_iss(5, 10, ("convergence-oscillation",))]
    # Production format from ConvergenceOscillationLoop: backtick-wrapped stages
    # drawn from CONVERGENCE_BOUNDARY_STAGES = ("triage", "plan").
    bodies = {
        5: "**Laps completed:** 3\n\n**Oscillating boundary stages:** `plan`, `triage`"
    }
    r = verdict_flapping(
        esc, bodies, probe_start=NOW - timedelta(days=20), probe_end=NOW
    )
    assert r.total_escalations == 1
    assert r.fired_in_probe_window is True
    assert dict(r.per_stage) == {"plan": 1, "triage": 1}  # backticks stripped
    assert r.is_fleet_level_evidence is False


# --- series 4: flat finders -------------------------------------------------


def test_flat_finder_detected() -> None:
    # A finder emitting a steady ~3/week for 8 weeks == flat.
    issues = []
    n = 1
    for wk in range(8):
        for _ in range(3):
            issues.append(_iss(n, wk * 7 + 1, ("hydraflow-find", "sampled-audit")))
            n += 1
    series = finder_activity(issues, now=NOW, weeks=8)
    sampled = next(s for s in series if s.finder == "sampled-audit")
    assert sampled.is_flat is True


def test_bursty_finder_not_flat() -> None:
    issues = [_iss(i, 1, ("hydraflow-find", "cost-budget")) for i in range(20)]
    series = finder_activity(issues, now=NOW, weeks=8)
    assert series[0].is_flat is False  # all in one week — high variance


# --- series 5: saturation ---------------------------------------------------


def test_saturation_markers_sorted() -> None:
    issues = [
        _iss(1, 5, ("cost-budget",)),
        _iss(2, 20, ("cost-budget-exceeded",)),
        _iss(3, 1, ("hydraflow-find",)),  # not a saturation marker
    ]
    marks = saturation_markers(issues)
    assert len(marks) == 2
    assert marks == sorted(marks)


# --- classification + ranking + render --------------------------------------


def test_fast_tick_loops_flags_sub_hourly() -> None:
    loops = [
        LoopInfo("Fast", "src.fast", 300),
        LoopInfo("Slow", "src.slow", 86400),
        LoopInfo("Unknown", "src.u", None),
    ]
    fast = fast_tick_loops(loops)
    assert [lp.name for lp in fast] == ["Fast"]


def test_rank_flux_carriers_top_n_and_share() -> None:
    issues = [_iss(i, 1, ("hydraflow-find", "sampled-audit")) for i in range(6)] + [
        _iss(100 + i, 1, ("hydraflow-find", "cost-budget")) for i in range(2)
    ]
    finders = finder_activity(issues, now=NOW, weeks=8)
    flapping = verdict_flapping([], {}, probe_start=NOW, probe_end=NOW)
    carriers = rank_flux_carriers(finders, flapping, {}, top_n=2)
    assert carriers[0].finder == "sampled-audit"
    assert abs(carriers[0].share_of_self - 6 / 8) < 1e-9
    assert len(carriers) == 2


def test_render_report_smoke() -> None:
    fp = Fingerprint(
        generated_at=NOW,
        weeks=8,
        self_series=weekly_self_sourced_fraction(
            [_iss(1, 2, ("hydraflow-find",))], now=NOW, weeks=8
        ),
        rework=rework_ratio([], now=NOW, weeks=8),
        flapping=verdict_flapping([], {}, probe_start=NOW, probe_end=NOW),
        finders=[],
        saturation=[],
        fast_ticks=[],
        carriers=[],
        gaps=["credit-pause windows are not persisted to telemetry"],
    )
    report = render_report(fp)
    assert "# Oscillation Fingerprint (#10820)" in report
    assert "fleet-level" in report  # the zero-escalation finding
    assert "Known gaps" in report
