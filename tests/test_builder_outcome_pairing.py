"""Unit tests for the builder -> outcome join (#11027, ruling mechanism B)."""

from __future__ import annotations

from builder_outcome_pairing import (
    IssueOutcome,
    builder_issue_links,
    builder_outcome_snapshot,
    pair_builders,
    resolve_builder,
)

# A tiny registry: builder name -> its fixture token digests.
_REGISTRY = {
    "planner_build_prompt": frozenset({"a", "b", "c", "d"}),
    "triage_build_prompt": frozenset({"x", "y", "z", "w"}),
}


def test_resolve_builder_attributes_a_clear_single_match() -> None:
    # Tokens overlapping planner well above the 0.5 resemblance threshold.
    assert (
        resolve_builder(frozenset({"a", "b", "c", "d"}), _REGISTRY)
        == "planner_build_prompt"
    )


def test_resolve_builder_abstains_when_nothing_matches() -> None:
    assert resolve_builder(frozenset({"q", "r", "s"}), _REGISTRY) is None


def test_resolve_builder_abstains_when_ambiguous() -> None:
    # A shape that resembles BOTH builders above threshold must not be guessed.
    reg = {
        "one": frozenset({"a", "b", "c", "d"}),
        "two": frozenset({"a", "b", "c", "e"}),
    }
    assert resolve_builder(frozenset({"a", "b", "c", "d"}), reg) is None


def test_builder_issue_links_joins_shape_to_issue_via_tokens() -> None:
    records = [
        {"issue_number": 101, "tokens": ["a", "b", "c", "d"]},  # -> planner
        {"issue_number": 202, "tokens": ["x", "y", "z", "w"]},  # -> triage
        {"issue_number": 303, "tokens": ["q", "r", "s"]},  # -> unattributed
    ]
    links = builder_issue_links(records, registry=_REGISTRY)
    assert links == {
        "planner_build_prompt": {101},
        "triage_build_prompt": {202},
    }


def test_builder_issue_links_skips_thin_or_untagged_rows() -> None:
    records = [
        {"tokens": ["a", "b", "c", "d"]},  # no issue_number
        {"issue_number": 101},  # no tokens (too thin to identify)
        {"issue_number": 102, "tokens": ["a", "b", "c", "d"]},  # good
    ]
    assert builder_issue_links(records, registry=_REGISTRY) == {
        "planner_build_prompt": {102}
    }


def test_builder_issue_links_skips_a_non_int_issue_tag() -> None:
    # A malformed issue tag (not an int) is skipped, not coerced — the
    # isinstance narrowing keeps the join honest rather than crashing.
    records = [
        {"issue_number": "not-an-int", "tokens": ["a", "b", "c", "d"]},
        {"issue_number": 42, "tokens": ["a", "b", "c", "d"]},
    ]
    assert builder_issue_links(records, registry=_REGISTRY) == {
        "planner_build_prompt": {42}
    }


def test_snapshot_aggregates_only_resolved_issues() -> None:
    outcomes = {
        1: IssueOutcome(passed=True, retries=0, escaped=False, cost=2.0),
        2: IssueOutcome(passed=False, retries=3, escaped=True, cost=4.0),
        # issue 3 has no outcome -> dropped, not assumed good
    }
    snap = builder_outcome_snapshot({1, 2, 3}, outcomes)
    assert snap is not None
    assert snap.n_samples == 2
    assert snap.pass_rate == 0.5
    assert snap.retry_rate == 1.5
    assert snap.escape_rate == 0.5
    assert snap.cost_per_success == 6.0 / 1  # total cost over the 1 success


def test_snapshot_is_none_when_no_issue_resolves() -> None:
    assert builder_outcome_snapshot({9, 10}, {}) is None


def test_pair_builders_drops_builders_with_no_resolved_outcomes() -> None:
    links = {"planner_build_prompt": {1}, "triage_build_prompt": {99}}
    outcomes = {1: IssueOutcome(passed=True, retries=1, escaped=False, cost=1.0)}
    paired = pair_builders(links, outcomes)
    assert set(paired) == {"planner_build_prompt"}  # triage's issue 99 unresolved
    assert paired["planner_build_prompt"].pass_rate == 1.0
