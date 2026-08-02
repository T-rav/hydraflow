"""Unit tests for the judge-independence budget + fail-visible dispatch policy (#10371).

Covers: blast-radius class detection (structural/security/migration/self-mod),
independent-verdict-required, model-family/roster resolution, the fail-open and
independence dispositions (self-mod fail-closed; degraded same-family / HITL),
append-only ledger IO, the Shewhart c-chart control limit, and the aggregate
calibration metrics (percent independent, fail-open rate, disagreement-by-family).
"""

from __future__ import annotations

from pathlib import Path

import pytest

import judge_independence as ji
from judge_independence import (
    BlastRadiusClass,
    FailOpenDisposition,
    IndependenceDisposition,
)

# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def _diff_touching(path: str) -> str:
    return (
        f"diff --git a/{path} b/{path}\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )


def test_unclassed_change_has_no_classes():
    diff = _diff_touching("src/comment_formatter.py")
    assert ji.classify_diff(diff) == frozenset()
    assert ji.requires_independent_verdict(ji.classify_diff(diff)) is False


def test_structural_adr_change_is_classed():
    diff = _diff_touching("docs/adr/0042-two-tier-branch-release-promotion.md")
    classes = ji.classify_diff(diff)
    assert BlastRadiusClass.STRUCTURAL in classes
    assert ji.requires_independent_verdict(classes) is True


def test_structural_module_graph_change_is_classed():
    assert BlastRadiusClass.STRUCTURAL in ji.classify_diff(
        _diff_touching("src/orchestrator.py")
    )


def test_security_adjacent_change_is_classed():
    assert BlastRadiusClass.SECURITY in ji.classify_diff(_diff_touching("src/auth.py"))


def test_migration_change_is_classed():
    assert BlastRadiusClass.MIGRATION in ji.classify_diff(
        _diff_touching("src/data_migration.py")
    )


def test_self_modification_gate_change_is_classed():
    classes = ji.classify_diff(_diff_touching("src/convergence_gate.py"))
    assert BlastRadiusClass.SELF_MODIFICATION in classes
    assert ji.is_self_modification(classes) is True


def test_classifier_itself_is_self_modification():
    """Acceptance: the classifier is covered by the self-modification class."""
    classes = ji.classify_diff(_diff_touching("src/judge_independence.py"))
    assert ji.is_self_modification(classes) is True


def test_10851_broadened_self_mod_covers_provider_dials():
    """#10851: the class was under-inclusive. Judge routing / provider dials — a
    failover re-dial changes verdict *provenance* (#10844) — are self-modification.
    (Kept surgical to avoid the over-reach the #10851 counter-metric warns of:
    routine ratchet baselines like suppressions.yaml are NOT self-mod.)"""
    classes = ji.classify_diff(_diff_touching("src/credit_failover.py"))
    assert ji.is_self_modification(classes) is True, (
        "credit_failover not classed self-mod"
    )


def test_10851_routine_ratchet_baseline_is_not_over_classed():
    """Guard against over-reach: bumping the suppressions noqa ledger is a routine
    mechanical change, not a gate-weakening one, and must NOT trip fail-closed
    self-mod (else it gets routed around — the #10851 counter-metric)."""
    classes = ji.classify_diff(
        _diff_touching("disturbance/baselines/suppressions.yaml")
    )
    assert ji.is_self_modification(classes) is False


def test_pure_deletion_diff_classified_via_git_header():
    diff = (
        "diff --git a/src/pr_manager.py b/src/pr_manager.py\n"
        "deleted file mode 100644\n"
        "--- a/src/pr_manager.py\n"
        "+++ /dev/null\n"
    )
    assert ji.is_self_modification(ji.classify_diff(diff)) is True


# ---------------------------------------------------------------------------
# Model family / roster
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "model,family",
    [
        ("opus", "claude"),
        ("sonnet", "claude"),
        ("claude-opus-4-8", "claude"),
        ("gpt-4o", "openai"),
        ("o3-mini", "openai"),
        ("gemini-2.5-pro", "google"),
        ("grok-2", "xai"),
        ("openrouter/anthropic/claude-3", "claude"),
    ],
)
def test_model_family(model, family):
    assert ji.model_family(model) == family


class _Cfg:
    """Minimal duck-typed config for roster/independence resolution."""

    def __init__(
        self,
        model="opus",
        review_model="sonnet",
        background="haiku",
        judge_independent_model="",
        diagnostics_dir=Path("/tmp/x"),
    ):
        self.model = model
        self.review_model = review_model
        self.background_model = background
        self.judge_independent_model = judge_independent_model
        self.diagnostics_dir = diagnostics_dir


def test_roster_all_claude_by_default():
    assert ji.roster_families(_Cfg()) == frozenset({"claude"})


def test_no_independent_family_when_unset():
    assert ji.independent_family_available(_Cfg()) is False
    assert ji.independent_judge_model(_Cfg()) == ""


def test_same_family_judge_does_not_count_as_independent():
    cfg = _Cfg(judge_independent_model="opus")
    assert ji.independent_family_available(cfg) is False


def test_cross_family_judge_is_independent():
    cfg = _Cfg(judge_independent_model="gpt-4o")
    assert ji.independent_family_available(cfg) is True
    assert ji.independent_judge_model(cfg) == "gpt-4o"


# ---------------------------------------------------------------------------
# Dispositions
# ---------------------------------------------------------------------------


def test_fail_open_non_self_mod_is_ledgered_pass():
    classes = frozenset({BlastRadiusClass.STRUCTURAL})
    assert (
        ji.disposition_for_fail_open(classes, self_mod_fail_closed_enabled=True)
        == FailOpenDisposition.FAIL_OPEN_LEDGERED
    )


def test_fail_open_self_mod_is_fail_closed_when_flag_on():
    classes = frozenset({BlastRadiusClass.SELF_MODIFICATION})
    assert (
        ji.disposition_for_fail_open(classes, self_mod_fail_closed_enabled=True)
        == FailOpenDisposition.FAIL_CLOSED_STOP
    )


def test_fail_open_self_mod_stays_open_when_flag_off():
    """Feature-flagged: the merge-outcome-changing STOP is opt-in."""
    classes = frozenset({BlastRadiusClass.SELF_MODIFICATION})
    assert (
        ji.disposition_for_fail_open(classes, self_mod_fail_closed_enabled=False)
        == FailOpenDisposition.FAIL_OPEN_LEDGERED
    )


def test_independence_routes_when_available():
    classes = frozenset({BlastRadiusClass.STRUCTURAL})
    assert (
        ji.disposition_for_independence(classes, independent_available=True)
        == IndependenceDisposition.INDEPENDENT_AVAILABLE
    )


def test_independence_degraded_same_family_non_self_mod():
    classes = frozenset({BlastRadiusClass.SECURITY})
    assert (
        ji.disposition_for_independence(classes, independent_available=False)
        == IndependenceDisposition.DEGRADED_SAME_FAMILY
    )


def test_independence_degraded_self_mod_escalates_hitl():
    classes = frozenset({BlastRadiusClass.SELF_MODIFICATION})
    assert (
        ji.disposition_for_independence(classes, independent_available=False)
        == IndependenceDisposition.DEGRADED_SELF_MOD_HITL
    )


# ---------------------------------------------------------------------------
# Ledger IO
# ---------------------------------------------------------------------------


def test_fail_open_record_round_trips(tmp_path: Path):
    p = tmp_path / "fail_open_ledger.jsonl"
    ok = ji.record_fail_open(
        p,
        lens="security",
        pr=123,
        surface="pr_review",
        classes=frozenset({BlastRadiusClass.SECURITY}),
        disposition=FailOpenDisposition.FAIL_OPEN_LEDGERED,
        reason="runner-error: boom",
    )
    assert ok is True
    records = ji.read_records(p)
    assert len(records) == 1
    r = records[0]
    assert r["kind"] == ji.KIND_FAIL_OPEN
    assert r["pr"] == 123
    assert r["failure_class"] == ["security"]
    assert r["self_modification"] is False
    assert r["disposition"] == "fail_open_ledgered"


def test_independence_unavailable_record_ledgered(tmp_path: Path):
    p = tmp_path / "l.jsonl"
    ji.record_independence_unavailable(
        p,
        lens=None,
        pr=7,
        surface="pr_review",
        classes=frozenset({BlastRadiusClass.MIGRATION}),
        disposition=IndependenceDisposition.DEGRADED_SAME_FAMILY,
    )
    r = ji.read_records(p)[0]
    assert r["kind"] == ji.KIND_INDEPENDENCE_UNAVAILABLE
    assert r["disposition"] == "degraded_same_family"


def test_read_records_tolerates_missing_and_malformed(tmp_path: Path):
    missing = tmp_path / "nope.jsonl"
    assert ji.read_records(missing) == []
    p = tmp_path / "l.jsonl"
    p.write_text('{"kind":"fail_open"}\nnot json\n\n{"kind":"x"}\n')
    assert len(ji.read_records(p)) == 2


# ---------------------------------------------------------------------------
# Shewhart control limit
# ---------------------------------------------------------------------------


def test_c_chart_ucl_formula():
    # cbar = 4 -> ucl = 4 + 3*2 = 10
    assert ji.shewhart_c_chart_ucl([4, 4, 4]) == pytest.approx(10.0)
    assert ji.shewhart_c_chart_ucl([]) == 0.0


def test_fail_open_rate_breach_requires_min_history(tmp_path: Path):
    p = tmp_path / "l.jsonl"
    # Only two days of data -> below min_days, cannot fire.
    ji.record_fail_open(
        p,
        lens=None,
        pr=1,
        surface="s",
        classes=frozenset(),
        disposition=FailOpenDisposition.FAIL_OPEN_LEDGERED,
        reason="x",
        ts="2026-07-01T00:00:00+00:00",
    )
    ji.record_fail_open(
        p,
        lens=None,
        pr=2,
        surface="s",
        classes=frozenset(),
        disposition=FailOpenDisposition.FAIL_OPEN_LEDGERED,
        reason="x",
        ts="2026-07-02T00:00:00+00:00",
    )
    breached, _ucl, _latest = ji.fail_open_rate_breach(ji.read_records(p))
    assert breached is False


def test_fail_open_rate_breach_fires_on_spike(tmp_path: Path):
    p = tmp_path / "l.jsonl"
    # Three quiet days (1 each) then a spike day (10) -> breach.
    days = ["2026-07-01", "2026-07-02", "2026-07-03"]
    for i, d in enumerate(days):
        ji.record_fail_open(
            p,
            lens=None,
            pr=i,
            surface="s",
            classes=frozenset(),
            disposition=FailOpenDisposition.FAIL_OPEN_LEDGERED,
            reason="x",
            ts=f"{d}T00:00:00+00:00",
        )
    for i in range(10):
        ji.record_fail_open(
            p,
            lens=None,
            pr=100 + i,
            surface="s",
            classes=frozenset(),
            disposition=FailOpenDisposition.FAIL_OPEN_LEDGERED,
            reason="x",
            ts="2026-07-04T00:00:00+00:00",
        )
    breached, ucl, latest = ji.fail_open_rate_breach(ji.read_records(p))
    assert breached is True
    assert latest == 10
    assert ucl < 10


# ---------------------------------------------------------------------------
# Calibration metrics (report / dashboard)
# ---------------------------------------------------------------------------


def test_calibration_metrics_pct_and_disagreement_by_family(tmp_path: Path):
    p = tmp_path / "l.jsonl"
    classes = frozenset({BlastRadiusClass.STRUCTURAL})
    # Two independent verdicts (openai family), one dissenting; one same-family.
    ji.record_classed_verdict(
        p,
        lens=None,
        pr=1,
        surface="s",
        classes=classes,
        independent=True,
        judge_family="openai",
        verdict="VETO",
        dissent=True,
    )
    ji.record_classed_verdict(
        p,
        lens=None,
        pr=2,
        surface="s",
        classes=classes,
        independent=True,
        judge_family="openai",
        verdict="APPROVE",
        dissent=False,
    )
    ji.record_classed_verdict(
        p,
        lens=None,
        pr=3,
        surface="s",
        classes=classes,
        independent=False,
        judge_family="claude",
        verdict="APPROVE",
        dissent=False,
    )
    m = ji.calibration_metrics(ji.read_records(p))
    assert m["classed_verdicts"] == 3
    assert m["independent_verdicts"] == 2
    assert m["pct_independent"] == pytest.approx(66.7)
    assert m["disagreement_by_family"]["openai"] == {"verdicts": 2, "dissents": 1}


def test_calibration_metrics_empty_is_zeroed():
    m = ji.calibration_metrics([])
    assert m["classed_verdicts"] == 0
    assert m["pct_independent"] == 0.0
    assert m["fail_open_total"] == 0
    assert m["disagreement_by_family"] == {}


# --- ADR-0123 Binds: factory mechanical backstop (#10851) -------------------


def _adr(binds: str, files: set[str]):
    from types import SimpleNamespace

    return SimpleNamespace(binds=binds, source_files=frozenset(files))


def test_factory_bound_source_files_collects_factory_and_both_only() -> None:
    adrs = [
        _adr("factory", {"src/config.py"}),
        _adr("both", {"src/gate_x.py"}),
        _adr("work", {"src/widget.py"}),
        _adr("unknown", {"src/legacy.py"}),
    ]
    assert ji.factory_bound_source_files(adrs) == frozenset(
        {"src/config.py", "src/gate_x.py"}
    )


def test_backstop_classes_adr_governed_config_as_self_mod() -> None:
    """A file an ADR governs with Binds: factory is self-mod even though it is
    NOT in the substring enumeration — the direction axis catches what the
    enumeration under-includes (the #10846 gate-enablement flip in config.py)."""
    fb = frozenset({"src/config.py"})
    diff = _diff_touching("src/config.py")
    # Without the backstop config.py is unclassed — proves the backstop is why.
    assert ji.is_self_modification(ji.classify_diff(diff)) is False
    assert (
        ji.is_self_modification(ji.classify_diff(diff, factory_bound_files=fb)) is True
    )


def test_backstop_respects_declared_direction() -> None:
    """A file governed only by a Binds: work ADR contributes nothing — direction
    is honored, so the backstop does not over-reach."""
    fb = ji.factory_bound_source_files([_adr("work", {"src/widget.py"})])
    classes = ji.classify_diff(_diff_touching("src/widget.py"), factory_bound_files=fb)
    assert ji.is_self_modification(classes) is False
