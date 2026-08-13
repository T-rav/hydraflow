"""Tests for the builder→outcome report runner (#11027 mechanism B / #10855)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from builder_outcome_pairing import IssueOutcome
from prompt_observatory import token_hashes

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from builder_outcome_report import (  # noqa: E402
    load_observations,
    outcomes_from_issue_states,
    render,
)


def test_load_observations_tolerates_corruption(tmp_path: Path) -> None:
    path = tmp_path / "observatory.jsonl"
    path.write_text(
        json.dumps({"shape": "s1", "issue_number": 7}) + '\nnot json\n"scalar"\n'
    )
    rows = load_observations(path)
    assert len(rows) == 1 and rows[0]["issue_number"] == 7
    assert load_observations(tmp_path / "absent.jsonl") == []


def test_outcomes_v1_resolution(tmp_path: Path) -> None:
    issues = tmp_path / "issues.json"
    issues.write_text(
        json.dumps(
            [
                {"number": 1, "state": "CLOSED", "stateReason": "COMPLETED"},
                {"number": 2, "state": "CLOSED", "stateReason": "NOT_PLANNED"},
                {"number": 3, "state": "OPEN", "stateReason": None},
                {"number": "x", "state": "CLOSED"},
            ]
        )
    )
    outcomes = outcomes_from_issue_states(issues)
    assert outcomes[1].passed and not outcomes[2].passed
    assert 3 not in outcomes  # open = unresolved, never assumed good
    assert set(outcomes) == {1, 2}
    # V1 placeholders stay at their honest zeros.
    assert outcomes[1] == IssueOutcome(passed=True, retries=0, escaped=False, cost=0.0)


def test_render_flips_outcome_paired_only_when_a_builder_paired() -> None:
    unpaired = render({}, {}, observations=0, outcomes=0)
    assert "outcome_paired=False" in unpaired
    assert "honest-False" in unpaired

    class _Snap:
        pass_rate = 0.75
        n_samples = 4

    paired = render(
        {"triage_builder": {1, 2}},
        {"triage_builder": _Snap()},
        observations=9,
        outcomes=4,
    )
    assert "outcome_paired=True" in paired
    assert "triage_builder" in paired and "75%" in paired
    assert "v1 coverage" in paired  # the honesty banner is always printed


def test_end_to_end_join_with_real_reconciler() -> None:
    """Observatory rows whose tokens match a registered builder pair for real.

    Uses the REAL registry + reconciler: we synthesize an observation whose
    token set is exactly a registered builder's fixture tokens (resemblance
    1.0 — unambiguous by construction), plus a garbage observation that must
    abstain.
    """
    from builder_outcome_pairing import builder_issue_links, pair_builders
    from prompt_observatory import registry_token_sets

    registry = registry_token_sets()
    if not registry:  # pragma: no cover - registry always populated in repo
        return
    builder, fixture_tokens = next(iter(sorted(registry.items())))
    rows = [
        {"tokens": sorted(fixture_tokens), "issue_number": 42},
        {"tokens": sorted(token_hashes("garbage prompt zz")), "issue_number": 43},
    ]
    links = builder_issue_links(rows)
    assert links.get(builder) == {42}
    paired = pair_builders(
        links,
        {42: IssueOutcome(passed=True, retries=0, escaped=False, cost=0.0)},
    )
    assert paired[builder].pass_rate == 1.0
    assert paired[builder].n_samples == 1
