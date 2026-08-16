"""Regression pins for the delta re-review contract (#11298 / PR #11301).

The token report measured plan_reviewer at 42% of all factory tokens —
every re-review round re-explored the repo blind to prior rounds. The
delta contract has three load-bearing properties pinned here:

1. Round-1 prompts are byte-free of re-review scaffolding (no behavior
   change for first reviews).
2. The round-N narrowing ALWAYS carries its escape valve — without it a
   restructured plan could smuggle new critical defects past a reviewer
   told not to look (the #11301 review finding).
3. The rendered block round-trips real findings verbatim so the reviewer
   verifies the actual complaints, not a paraphrase.
"""

from __future__ import annotations

from models import PlanFinding, PlanFindingSeverity, Task
from plan_reviewer import PlanReviewer, _render_prior_review


def _task() -> Task:
    return Task(id=11298, title="t", body="b", tags=[], comments=[])


def test_round_one_prompt_has_no_reredview_scaffolding() -> None:
    prompt = PlanReviewer._build_prompt(_task(), "the plan")
    assert "RE-REVIEW" not in prompt
    assert "Prior review" not in prompt


def test_narrowing_always_carries_the_escape_valve() -> None:
    block = _render_prior_review("1 finding", None)
    assert block is not None
    assert "RESTRUCTURED" in block
    assert "never licenses missing a real defect" in block
    assert "Reason first" in block


def test_findings_round_trip_verbatim() -> None:
    finding = PlanFinding(
        severity=PlanFindingSeverity.CRITICAL,
        dimension="correctness",
        description="claims Foo.bar exists",
        suggestion="grep Foo",
    )
    block = _render_prior_review(None, [finding])
    assert block is not None
    assert "[critical] correctness: claims Foo.bar exists" in block
    assert "Suggestion: grep Foo" in block
