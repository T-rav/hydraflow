"""Unit tests for the test-adequacy demand contract (#11644).

Two mechanisms, one module: the anchoring predicate (does a finding name
something locatable?) and the retry pin (is attempt N+1 judged against the
findings attempt N actually stated?).

The unanchored fixtures are the VERBATIM findings #11643's calibration pulled
out of the August implement corpus — they are what the gate really emits, so
they are what the predicate has to be right about.
"""

from __future__ import annotations

import pytest

from adequacy_demand import (
    MAX_PINNED_FINDINGS,
    DemandVerdict,
    cites_demonstration,
    demand_tokens,
    evaluate_demand,
    finding_tokens,
    is_anchored,
    names_referent,
    pin_findings,
)

# --- the corpus's real unanchored findings (#11643) ------------------------------

UNANCHORED_CORPUS = [
    pytest.param("missing-error-path-coverage", id="missing-error-path-coverage"),
    pytest.param("edge-case-coverage", id="edge-case-coverage"),
    pytest.param("unpinned-serial-list-sync", id="unpinned-serial-list-sync"),
    pytest.param(
        "boundary-condition gap in truncation logic", id="boundary-condition-gap"
    ),
    pytest.param(
        "untested-fallback-branch, untested-error-branch, untested-failure-degradation",
        id="untested-triple",
    ),
    pytest.param("missing-fallback-path-coverage", id="missing-fallback-path"),
    pytest.param(
        "missing edge case for merge-commit exclusion behavior", id="merge-commit-edge"
    ),
    pytest.param("makefile-wiring-untested", id="makefile-wiring-untested"),
    pytest.param("edge-case-empty-arg", id="edge-case-empty-arg"),
]

ANCHORED_CORPUS = [
    pytest.param("x.py:frob — no test", id="path-and-symbol"),
    pytest.param("src/skill_gate.py:120 — uncovered changed line", id="path-line"),
    pytest.param("`_run_skill_repair_pass` is untested", id="backticked-span"),
    pytest.param("run_skill_check never exercised on the retry path", id="snake-case"),
    pytest.param("AgentRunner boot wiring untested", id="camel-case"),
    pytest.param("--force-with-lease path untested", id="cli-flag"),
    pytest.param("/api/control/start error path untested", id="route"),
    pytest.param("MAX_REPAIR_FINDINGS boundary untested", id="allcaps-constant"),
]


@pytest.mark.parametrize("finding", UNANCHORED_CORPUS)
def test_corpus_unanchored_finding_names_no_referent(finding: str) -> None:
    assert names_referent(finding) is False


@pytest.mark.parametrize("finding", UNANCHORED_CORPUS)
def test_corpus_unanchored_finding_is_not_anchored(finding: str) -> None:
    assert is_anchored(finding) is False


@pytest.mark.parametrize("finding", ANCHORED_CORPUS)
def test_finding_with_a_referent_is_anchored(finding: str) -> None:
    assert is_anchored(finding) is True


@pytest.mark.parametrize(
    "finding",
    [
        pytest.param("a surviving mutant proves the branch is inert", id="mutant"),
        pytest.param("mutation of the guard is not caught", id="mutation"),
        pytest.param("the change is silently inert if reverted", id="revert"),
        pytest.param("demonstrated: the suite passes with the fix removed", id="shown"),
    ],
)
def test_demonstrated_survivability_counts_as_anchored(finding: str) -> None:
    """A falsifiable survivability claim anchors a demand even without a symbol."""
    assert is_anchored(finding) is True


def test_demonstration_is_recognised_without_a_referent() -> None:
    assert cites_demonstration("a surviving mutant lives here") is True


def test_plain_prose_cites_no_demonstration() -> None:
    assert cites_demonstration("missing-error-path-coverage") is False


def test_empty_finding_is_not_anchored() -> None:
    assert is_anchored("") is False


# --- tokenisation ----------------------------------------------------------------


def test_gate_vocabulary_is_stripped_from_tokens() -> None:
    """'edge', 'case' and 'coverage' say nothing about WHICH gap is demanded."""
    assert finding_tokens("edge-case-coverage") == frozenset()


def test_topical_tokens_survive_the_strip() -> None:
    assert finding_tokens("missing-error-path-coverage") == frozenset({"error", "path"})


def test_finding_tokens_keeps_the_discriminating_words() -> None:
    assert finding_tokens("the error path in a `_merge_base`") == frozenset(
        {"error", "path", "merge", "base"}
    )


@pytest.mark.parametrize(
    "filler", ["the", "in", "a", "with", "untested", "missing", "coverage", "tests"]
)
def test_finding_tokens_drops_filler_and_gate_vocabulary(filler: str) -> None:
    assert filler not in finding_tokens(f"{filler} error path")


def test_demand_tokens_unions_every_finding() -> None:
    assert demand_tokens(["missing-error-path-coverage", "wiring gap"]) == frozenset(
        {"error", "path", "wiring"}
    )


# --- pinning ---------------------------------------------------------------------


def test_pin_findings_drops_blank_entries() -> None:
    assert pin_findings(["a.py:f", "   ", ""]) == ("a.py:f",)


def test_pin_findings_deduplicates_preserving_order() -> None:
    assert pin_findings(["a.py:f", "b.py:g", "a.py:f"]) == ("a.py:f", "b.py:g")


def test_pin_findings_is_bounded() -> None:
    pinned = pin_findings([f"mod{i}.py:sym" for i in range(MAX_PINNED_FINDINGS + 5)])
    assert len(pinned) == MAX_PINNED_FINDINGS


# --- the demand contract ---------------------------------------------------------


def test_without_a_pin_every_finding_blocks() -> None:
    """First attempt: unchanged behaviour — the gate states the bar and holds it."""
    verdict = evaluate_demand(["edge-case-coverage"], pinned=(), pinned_enforced=True)
    assert verdict.blocking == ("edge-case-coverage",)


def test_without_a_pin_nothing_is_advisory() -> None:
    verdict = evaluate_demand(["edge-case-coverage"], pinned=(), pinned_enforced=True)
    assert verdict.advisory == ()


def test_pin_not_enforced_leaves_every_finding_blocking() -> None:
    """The kill switch restores the pre-#11644 shape even with a pin present."""
    verdict = evaluate_demand(
        ["totally unrelated prose"],
        pinned=("src/a.py:frob missing test",),
        pinned_enforced=False,
    )
    assert verdict.blocking == ("totally unrelated prose",)


def test_pin_not_enforced_records_no_pin_enforcement() -> None:
    verdict = evaluate_demand(
        ["totally unrelated prose"],
        pinned=("src/a.py:frob missing test",),
        pinned_enforced=False,
    )
    assert verdict.pinned_enforced is False


def test_a_restated_pinned_finding_still_blocks() -> None:
    verdict = evaluate_demand(
        ["src/a.py:frob still has no error-path test"],
        pinned=("src/a.py:frob missing error test",),
        pinned_enforced=True,
    )
    assert verdict.restated == ("src/a.py:frob still has no error-path test",)


def test_a_restated_pinned_finding_is_in_the_blocking_set() -> None:
    verdict = evaluate_demand(
        ["src/a.py:frob still has no error-path test"],
        pinned=("src/a.py:frob missing error test",),
        pinned_enforced=True,
    )
    assert verdict.blocks is True


def test_a_new_unanchored_finding_does_not_block_a_pinned_retry() -> None:
    """The 0.04-overlap pathology: a fresh, unlocatable bar cannot reject a retry."""
    verdict = evaluate_demand(
        ["edge-case-coverage of the truncation logic"],
        pinned=("src/a.py:frob missing error test",),
        pinned_enforced=True,
    )
    assert verdict.blocks is False


def test_a_new_unanchored_finding_is_recorded_as_advisory() -> None:
    verdict = evaluate_demand(
        ["boundary-condition gap in truncation logic"],
        pinned=("src/a.py:frob missing error test",),
        pinned_enforced=True,
    )
    assert verdict.advisory == ("boundary-condition gap in truncation logic",)


def test_a_new_unanchored_finding_is_still_recorded_as_new() -> None:
    """Non-stationarity stays visible in telemetry rather than being hidden."""
    verdict = evaluate_demand(
        ["boundary-condition gap in truncation logic"],
        pinned=("src/a.py:frob missing error test",),
        pinned_enforced=True,
    )
    assert verdict.new == ("boundary-condition gap in truncation logic",)


def test_a_genuinely_new_anchored_finding_still_blocks() -> None:
    """A retry may raise a new bar — but only one it can point at."""
    verdict = evaluate_demand(
        ["src/other.py:widget has no test"],
        pinned=("src/a.py:frob missing error test",),
        pinned_enforced=True,
    )
    assert verdict.blocks is True


def test_a_genuinely_new_anchored_finding_is_recorded_as_new() -> None:
    verdict = evaluate_demand(
        ["src/other.py:widget has no test"],
        pinned=("src/a.py:frob missing error test",),
        pinned_enforced=True,
    )
    assert verdict.new == ("src/other.py:widget has no test",)


def test_a_finding_with_no_topical_tokens_counts_as_restated() -> None:
    """Cannot be shown disjoint from the pin, so it is treated as the standing bar."""
    verdict = evaluate_demand(
        ["edge-case-coverage"],
        pinned=("src/a.py:frob missing error test",),
        pinned_enforced=True,
    )
    assert verdict.restated == ("edge-case-coverage",)


def test_mixed_verdict_blocks_on_the_restated_finding() -> None:
    verdict = evaluate_demand(
        [
            "src/a.py:frob still has no error test",
            "boundary-condition gap in truncation logic",
        ],
        pinned=("src/a.py:frob missing error test",),
        pinned_enforced=True,
    )
    assert verdict.blocking == ("src/a.py:frob still has no error test",)


def test_mixed_verdict_keeps_the_new_unanchored_finding_advisory() -> None:
    verdict = evaluate_demand(
        [
            "src/a.py:frob still has no error test",
            "boundary-condition gap in truncation logic",
        ],
        pinned=("src/a.py:frob missing error test",),
        pinned_enforced=True,
    )
    assert verdict.advisory == ("boundary-condition gap in truncation logic",)


def test_empty_findings_partition_to_an_empty_blocking_set() -> None:
    """Pure partition. The gate's own fail-closed guard keeps such a verdict
    rejecting — see ``skill_gate._apply_demand_contract``.
    """
    assert evaluate_demand([], pinned=(), pinned_enforced=True).blocking == ()


def test_a_pin_with_no_topical_tokens_degenerates_to_no_pin() -> None:
    """Not comparable ⇒ not waivable: every finding blocks, the safe direction."""
    verdict = evaluate_demand(
        ["boundary-condition gap in truncation logic"],
        pinned=("a.py:b — no test",),
        pinned_enforced=True,
    )
    assert verdict.blocking == ("boundary-condition gap in truncation logic",)


def test_a_degenerate_pin_is_reported_as_not_enforced() -> None:
    verdict = evaluate_demand(
        ["boundary-condition gap in truncation logic"],
        pinned=("a.py:b — no test",),
        pinned_enforced=True,
    )
    assert verdict.pinned_enforced is False


def test_anchored_findings_partition_reports_the_locatable_subset() -> None:
    verdict = evaluate_demand(
        ["src/a.py:frob has no test", "edge-case-coverage"],
        pinned=(),
        pinned_enforced=True,
    )
    assert verdict.anchored == ("src/a.py:frob has no test",)


def test_unanchored_findings_partition_reports_the_rest() -> None:
    verdict = evaluate_demand(
        ["src/a.py:frob has no test", "edge-case-coverage"],
        pinned=(),
        pinned_enforced=True,
    )
    assert verdict.unanchored == ("edge-case-coverage",)


def test_verdict_is_frozen() -> None:
    verdict = DemandVerdict()
    with pytest.raises(AttributeError):
        verdict.blocking = ("x",)  # type: ignore[misc]
