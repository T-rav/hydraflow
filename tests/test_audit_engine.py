"""Unit tests for the sampled-adversarial-reaudit pure engine (#10370).

Covers the acceptance-criteria-bearing pure functions: stratified sampling
selection, Shewhart rate governance (widen/narrow within floor/ceiling against a
synthetic disagreement series), token-budget capping under a synthetic backlog,
the upheld→escape-ledger cross-link (reusing escape.models), refuted→false-alarm
accounting, no-verdict-contamination, and the additive report splice.
"""

from __future__ import annotations

import random

from audit.budget import estimate_audit_tokens, within_budget
from audit.crosslink import sample_to_escape_record
from audit.detect import parse_pr_number
from audit.disposition import reconcile_disposition
from audit.governance import (
    DEFAULT_BASE_RATE,
    DEFAULT_CEILING,
    DEFAULT_FLOOR,
    govern_rate,
    trim_history,
    upper_control_limit,
)
from audit.metrics import (
    disagreement_rate_ci,
    false_alarm_rate,
    per_gate_class_calibration,
    wilson_interval,
)
from audit.models import (
    AUDIT_INPUT_SOURCES,
    AuditSample,
    DisagreementObservation,
    MergedChange,
)
from audit.report import BEGIN_MARKER, END_MARKER, render_full_report, upsert_section
from audit.sampling import inclusion_probability, select_sample
from audit.stratify import classify_blast_radius, stratum_weight


def _change(
    *,
    pr: int = 1,
    sha: str = "abc123def456",
    paths: tuple[str, ...] = ("src/x.py",),
    subject: str = "feat: x (#1)",
) -> MergedChange:
    return MergedChange(
        pr_number=pr,
        merge_sha=sha,
        subject=subject,
        changed_paths=paths,
        merged_at="2026-07-23T00:00:00+00:00",
    )


def _sample(
    *,
    sid: str = "1:abc",
    verdict: str = "agree",
    cls: str = "routine",
    disposition: str = "n/a",
    rate: float = 0.05,
) -> AuditSample:
    return AuditSample(
        id=sid,
        audited_at="2026-07-23T00:00:00+00:00",
        pr_number=1,
        merge_sha="abc123def456",
        blast_radius_class=cls,
        verdict=verdict,
        findings="",
        input_sources=AUDIT_INPUT_SOURCES,
        auditor_model="sonnet",
        sample_rate=rate,
        disposition=disposition,
    )


# --- stratification --------------------------------------------------------


class TestStratification:
    def test_gauntlet_paths_win(self) -> None:
        assert (
            classify_blast_radius(_change(paths=("src/merge_policy.py",))) == "gauntlet"
        )
        assert (
            classify_blast_radius(_change(paths=(".github/workflows/ci.yml",)))
            == "gauntlet"
        )

    def test_security_migration_structural_routine(self) -> None:
        assert (
            classify_blast_radius(_change(paths=("src/auth/login.py",))) == "security"
        )
        assert (
            classify_blast_radius(_change(paths=("db/migrations/001.sql",)))
            == "migration"
        )
        assert (
            classify_blast_radius(_change(paths=("docs/adr/0099-x.md",)))
            == "structural"
        )
        assert classify_blast_radius(_change(paths=("src/util/plain.py",))) == "routine"

    def test_precedence_gauntlet_over_migration(self) -> None:
        change = _change(paths=("db/migrations/001.sql", "src/gauntlet/run.py"))
        assert classify_blast_radius(change) == "gauntlet"

    def test_adr_subject_signal_without_file(self) -> None:
        change = _change(
            paths=("src/plain.py",), subject="feat: promote (ADR-0042) (#7)"
        )
        assert classify_blast_radius(change) == "structural"

    def test_stratum_weights_ordered(self) -> None:
        assert stratum_weight("routine") == 1.0
        assert (
            stratum_weight("gauntlet")
            > stratum_weight("security")
            > stratum_weight("routine")
        )


# --- sampling --------------------------------------------------------------


class TestSampling:
    def test_inclusion_probability_elevated_and_capped(self) -> None:
        routine = inclusion_probability(_change(paths=("src/x.py",)), 0.05)
        gauntlet = inclusion_probability(_change(paths=("src/merge_policy.py",)), 0.05)
        assert routine == 0.05
        assert gauntlet > routine
        # capped at certainty even at a high base rate * weight
        assert (
            inclusion_probability(_change(paths=("src/merge_policy.py",)), 0.5) == 1.0
        )

    def test_select_sample_deterministic_for_seed(self) -> None:
        changes = [_change(pr=i, sha=f"sha{i:040d}") for i in range(50)]
        a = select_sample(changes, base_rate=0.2, rng=random.Random(7))
        b = select_sample(changes, base_rate=0.2, rng=random.Random(7))
        assert [c.id for c in a] == [c.id for c in b]

    def test_gauntlet_always_selected_at_certainty(self) -> None:
        changes = [_change(pr=1, sha="g" * 40, paths=("src/merge_policy.py",))]
        # base_rate * gauntlet weight (4) >= 1 → always selected
        selected = select_sample(changes, base_rate=0.25, rng=random.Random(1))
        assert len(selected) == 1

    def test_zero_rate_selects_nothing(self) -> None:
        changes = [_change(pr=i, sha=f"s{i:039d}") for i in range(20)]
        assert select_sample(changes, base_rate=0.0, rng=random.Random(1)) == []


# --- governance (Shewhart) -------------------------------------------------


class TestGovernance:
    def test_quiet_history_narrows_toward_floor(self) -> None:
        history = [DisagreementObservation(10, 0) for _ in range(3)]
        new = govern_rate(history, current_rate=0.05)
        assert new < 0.05
        assert new >= DEFAULT_FLOOR

    def test_disagreement_spike_widens_toward_ceiling(self) -> None:
        history = [DisagreementObservation(10, 0) for _ in range(5)]
        history.append(DisagreementObservation(10, 5))  # 50% special-cause spike
        new = govern_rate(history, current_rate=0.05)
        assert new > 0.05
        assert new <= DEFAULT_CEILING

    def test_insufficient_pooled_samples_holds(self) -> None:
        history = [DisagreementObservation(2, 0)]  # pooled 2 < min
        assert govern_rate(history, current_rate=0.05) == 0.05

    def test_clamped_to_ceiling(self) -> None:
        history = [DisagreementObservation(10, 0) for _ in range(5)]
        history.append(DisagreementObservation(10, 9))
        assert govern_rate(history, current_rate=0.19) == DEFAULT_CEILING

    def test_clamped_to_floor(self) -> None:
        history = [DisagreementObservation(10, 0) for _ in range(3)]
        assert govern_rate(history, current_rate=0.021) == DEFAULT_FLOOR

    def test_burst_above_control_limit_widens(self) -> None:
        history = [DisagreementObservation(10, 0) for _ in range(5)]
        history.append(DisagreementObservation(10, 4))  # 40% >> target UCL
        assert govern_rate(history, current_rate=0.05) > 0.05

    def test_mild_tick_within_band_holds(self) -> None:
        # A single 10% tick (n=10) sits below the 3-sigma UCL around the 5%
        # target but above the target itself → hold, neither widen nor narrow.
        history = [DisagreementObservation(10, 0) for _ in range(5)]
        history.append(DisagreementObservation(10, 1))
        assert govern_rate(history, current_rate=0.05) == 0.05

    def test_synthetic_series_climbs_then_falls_within_band(self) -> None:
        """Acceptance: the governed rate demonstrably widens then narrows,
        staying within [floor, ceiling], against a synthetic disagreement series."""
        rate = DEFAULT_BASE_RATE
        history: list[DisagreementObservation] = []
        # Rising disagreement pressure → rate should climb.
        for _ in range(12):
            history.append(DisagreementObservation(10, 6))
            history = trim_history(history)
            rate = govern_rate(history, current_rate=rate)
            assert DEFAULT_FLOOR <= rate <= DEFAULT_CEILING
        climbed = rate
        assert climbed > DEFAULT_BASE_RATE
        # Then quiet → rate should fall back toward the floor.
        for _ in range(20):
            history.append(DisagreementObservation(10, 0))
            history = trim_history(history)
            rate = govern_rate(history, current_rate=rate)
            assert DEFAULT_FLOOR <= rate <= DEFAULT_CEILING
        assert rate < climbed

    def test_upper_control_limit_defaults_to_target_when_no_samples(self) -> None:
        from audit.governance import TARGET_DISAGREEMENT_RATE

        assert upper_control_limit([]) == TARGET_DISAGREEMENT_RATE

    def test_trim_history_bounds_window(self) -> None:
        history = [DisagreementObservation(1, 0) for _ in range(100)]
        assert len(trim_history(history, window=10)) == 10


# --- budget ----------------------------------------------------------------


class TestBudget:
    def test_estimate_grows_with_paths(self) -> None:
        small = estimate_audit_tokens(_change(paths=("a.py",)))
        big = estimate_audit_tokens(_change(paths=tuple(f"f{i}.py" for i in range(20))))
        assert big > small

    def test_budget_caps_synthetic_backlog(self) -> None:
        backlog = [_change(pr=i, sha=f"s{i:039d}", paths=("a.py",)) for i in range(100)]
        per = estimate_audit_tokens(backlog[0])
        fitted = within_budget(backlog, token_budget=per * 3 + 1)
        assert len(fitted) == 3

    def test_zero_budget_audits_nothing(self) -> None:
        backlog = [_change(pr=i, sha=f"s{i:039d}") for i in range(5)]
        assert within_budget(backlog, token_budget=0) == []


# --- metrics ---------------------------------------------------------------


class TestMetrics:
    def test_wilson_interval_brackets_point_estimate(self) -> None:
        ci = wilson_interval(2, 10)
        assert ci.n == 10
        assert ci.lower <= ci.rate <= ci.upper
        assert ci.lower >= 0.0 and ci.upper <= 1.0

    def test_wilson_interval_empty(self) -> None:
        ci = wilson_interval(0, 0)
        assert ci.rate == 0.0 and ci.lower == 0.0 and ci.upper == 0.0 and ci.n == 0

    def test_disagreement_rate_ci(self) -> None:
        samples = [
            _sample(sid="1", verdict="disagree"),
            _sample(sid="2", verdict="agree"),
            _sample(sid="3", verdict="agree"),
            _sample(sid="4", verdict="agree"),
        ]
        ci = disagreement_rate_ci(samples)
        assert ci.n == 4
        assert abs(ci.rate - 0.25) < 1e-9

    def test_false_alarm_rate_only_counts_adjudicated(self) -> None:
        samples = [
            _sample(sid="1", verdict="disagree", disposition="upheld"),
            _sample(sid="2", verdict="disagree", disposition="refuted"),
            _sample(sid="3", verdict="disagree", disposition="refuted"),
            _sample(sid="4", verdict="disagree", disposition="pending"),  # not counted
        ]
        assert abs(false_alarm_rate(samples) - (2 / 3)) < 1e-9

    def test_false_alarm_rate_zero_when_none_adjudicated(self) -> None:
        assert (
            false_alarm_rate([_sample(verdict="disagree", disposition="pending")])
            == 0.0
        )

    def test_per_gate_class_calibration(self) -> None:
        samples = [
            _sample(sid="1", verdict="disagree", cls="gauntlet", disposition="upheld"),
            _sample(sid="2", verdict="agree", cls="gauntlet", disposition="n/a"),
            _sample(sid="3", verdict="agree", cls="routine", disposition="n/a"),
        ]
        rows = {r.blast_radius_class: r for r in per_gate_class_calibration(samples)}
        assert rows["gauntlet"].sampled == 2
        assert rows["gauntlet"].disagreements == 1
        assert rows["gauntlet"].upheld == 1
        assert rows["routine"].sampled == 1


# --- cross-link (reuses escape.models) -------------------------------------


class TestCrossLink:
    def test_upheld_sample_to_escape_record(self) -> None:
        sample = _sample(sid="42:deadbeefcafe", verdict="disagree", cls="security")
        sample = AuditSample(
            id="42:deadbeefcafe",
            audited_at="2026-07-23T00:00:00+00:00",
            pr_number=42,
            merge_sha="deadbeefcafe0000",
            blast_radius_class="security",
            verdict="disagree",
            findings="missing authz check",
            input_sources=AUDIT_INPUT_SOURCES,
            auditor_model="gpt",
            sample_rate=0.05,
            disposition="upheld",
        )
        record = sample_to_escape_record(sample)
        assert record.detection_source == "sampled-audit"
        assert record.id == "sampled-audit:42:deadbeefcafe"
        assert record.originating_pr == 42
        assert record.originating_merge_sha == "deadbeefcafe0000"
        assert record.attribution_method == "agent-research"

    def test_record_round_trips_through_escape_ledger_writer(self, tmp_path) -> None:
        """The cross-link REUSES the escape ledger writer/schema (not a fork)."""
        from escape.ledger import EscapeLedger

        sample = AuditSample(
            id="7:abcabcabcabc",
            audited_at="2026-07-23T00:00:00+00:00",
            pr_number=7,
            merge_sha="abcabcabcabc0000",
            blast_radius_class="gauntlet",
            verdict="disagree",
            findings="x",
            input_sources=AUDIT_INPUT_SOURCES,
            auditor_model="gpt",
            sample_rate=0.05,
            disposition="upheld",
        )
        ledger = EscapeLedger(tmp_path / "escape_ledger.jsonl")
        ledger.append(sample_to_escape_record(sample))
        rows = ledger.read_all()
        assert len(rows) == 1
        assert rows[0].detection_source == "sampled-audit"


# --- disposition -----------------------------------------------------------


class TestDisposition:
    def test_open_issue_is_pending(self) -> None:
        assert reconcile_disposition("OPEN", []) == "pending"

    def test_refuted_label_wins(self) -> None:
        assert reconcile_disposition("COMPLETED", ["audit-refuted"]) == "refuted"

    def test_upheld_label_wins(self) -> None:
        assert reconcile_disposition("OPEN", ["audit-upheld"]) == "upheld"

    def test_not_planned_close_is_refuted(self) -> None:
        assert reconcile_disposition("NOT_PLANNED", []) == "refuted"

    def test_completed_close_is_upheld(self) -> None:
        assert reconcile_disposition("COMPLETED", []) == "upheld"


# --- no-verdict-contamination ---------------------------------------------


class TestNoContamination:
    def test_default_input_sources_are_clean(self) -> None:
        assert _sample().no_verdict_contamination()
        assert "merged-diff" in AUDIT_INPUT_SOURCES
        assert not any("verdict" in s for s in AUDIT_INPUT_SOURCES)

    def test_verdict_source_is_flagged_as_contamination(self) -> None:
        contaminated = AuditSample(
            id="1",
            audited_at="t",
            pr_number=1,
            merge_sha="s",
            blast_radius_class="routine",
            verdict="agree",
            findings="",
            input_sources=("merged-diff", "original-review-verdicts"),
            auditor_model="sonnet",
            sample_rate=0.05,
        )
        assert not contaminated.no_verdict_contamination()


# --- report splice (additive with #10371) ---------------------------------


class TestReportSplice:
    def test_upsert_preserves_foreign_section(self) -> None:
        """A merge with #10371's section is a clean concatenation, not a clobber."""
        foreign = (
            "# Gauntlet calibration\n\n"
            "<!-- BEGIN judge-independence (#10371) -->\n"
            "## Judge independence\nsome content\n"
            "<!-- END judge-independence (#10371) -->\n"
        )
        merged = render_full_report(
            [_sample()], now=_now(), governed_rate=0.05, existing=foreign
        )
        assert "Judge independence" in merged
        assert "Sampled adversarial re-audit" in merged
        assert BEGIN_MARKER in merged and END_MARKER in merged

    def test_upsert_replaces_own_section_idempotently(self) -> None:
        first = render_full_report(
            [_sample()], now=_now(), governed_rate=0.05, existing=""
        )
        second = render_full_report(
            [_sample()], now=_now(), governed_rate=0.05, existing=first
        )
        assert second.count(BEGIN_MARKER) == 1
        assert second.count(END_MARKER) == 1

    def test_upsert_section_seeds_title_when_empty(self) -> None:
        out = upsert_section(
            "",
            "<!-- BEGIN sampled-adversarial-reaudit (#10370) -->\nx\n<!-- END sampled-adversarial-reaudit (#10370) -->",
        )
        assert "# Gauntlet calibration" in out


# --- detect PR parsing -----------------------------------------------------


class TestDetectParsing:
    def test_squash_subject(self) -> None:
        assert parse_pr_number("feat(x): do a thing (#10370)") == 10370

    def test_merge_subject(self) -> None:
        assert parse_pr_number("Merge pull request #123 from foo/bar") == 123

    def test_no_pr(self) -> None:
        assert parse_pr_number("just a commit") == 0


def _now():
    from datetime import UTC, datetime

    return datetime(2026, 7, 23, tzinfo=UTC)
