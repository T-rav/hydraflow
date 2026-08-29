"""Regression: plan phase over-produced detail that the pipeline discarded (#9955).

min_plan_words=200 FORCED verbosity while max_impl_plan_chars=6000 truncated
the plan before the implementer saw it — the pipeline required detail and
then threw it away (paid-for information loss). The prompt itself
manufactured the verbosity ("<your detailed implementation plan here>", a
9-point write-this rubric).

Pins (operator steering: prompt tuning is the lever, NO information loss):
- The enforced plan budget is ALWAYS at or below the implement boundary —
  nothing a planner writes is ever truncated away.
- Over-budget plans are rejected with condense guidance (retry feedback).
- A concise-but-complete execution brief passes validation.
- The planner prompt demands the brief shape + states the budget; the
  "detailed implementation plan" phrasing is gone.
- The Builder ensemble voter carries the anti-verbosity guard — brevity is
  never a finding.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config import HydraFlowConfig
from plan_ensemble_prompts import BUILDER_PROMPT
from plan_validation import validate_plan
from tests.conftest import TaskFactory
from tests.helpers import ConfigFactory

CONCISE_BRIEF = (
    "## Intent\n\n"
    "Cap the Pipeline Flow dot row so large queues cannot push later stages "
    "off-screen.\n\n"
    "## Approach\n\n"
    "Slice the issue list at a constant cap in StreamView and render the "
    "remainder as one +N overflow badge, mirroring the existing queued-count "
    "badge pattern.\n\n"
    "## Files to Modify\n\n"
    "- src/ui/src/components/StreamView.jsx — cap dots, add badge\n\n"
    "## New Files\n\n"
    "None\n\n"
    "## File Delta\n\n"
    "MODIFIED: src/ui/src/components/StreamView.jsx\n\n"
    "## Task Graph\n\n"
    "### P1 — Cap and badge\n"
    "**Files:** src/ui/src/components/StreamView.jsx\n"
    "**Tests:**\n"
    "- 67 queued issues render exactly 10 dots and a +57 badge\n"
    "- 10 or fewer issues render no badge\n"
    "**Depends on:** (none)\n\n"
    "## Implementation Steps\n\n"
    "1. Add FLOW_DOT_CAP constant and slice in StreamView.jsx\n"
    "2. Render overflow badge with data-testid per stage\n\n"
    "## Testing Strategy\n\n"
    "- Extend src/ui/src/components/__tests__/StreamView.test.jsx\n\n"
    "## Acceptance Criteria\n\n"
    "- No stage row ever renders more than 10 dots\n"
    "- Overflow count equals total minus rendered dots\n\n"
    "## Key Considerations\n\n"
    "- Keep the queued-count badge testids stable\n"
)


class TestBudgetInvariant:
    def test_default_budget_is_below_the_implement_boundary(self) -> None:
        """Nothing a planner writes within budget can ever be truncated."""
        config = HydraFlowConfig()
        assert config.max_plan_chars < config.max_impl_plan_chars

    def test_enforced_budget_clamps_to_implement_boundary(self, tmp_path) -> None:
        """Even a misconfigured max_plan_chars cannot re-enable truncation."""
        config = ConfigFactory.create(repo_root=tmp_path)
        object.__setattr__(config, "max_plan_chars", 40_000)
        object.__setattr__(config, "max_impl_plan_chars", 6_000)
        task = TaskFactory.create(id=1, title="Overlong plan")
        plan = CONCISE_BRIEF + ("x" * 7_000)

        errors = validate_plan(task, plan, "full", config=config)

        assert any("budget is 6000" in e for e in errors)

    def test_over_budget_plan_rejected_with_condense_guidance(self, tmp_path) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)
        task = TaskFactory.create(id=1, title="Overlong plan")
        plan = CONCISE_BRIEF + ("padding word " * 2_000)

        errors = validate_plan(task, plan, "full", config=config)

        assert any("condense" in e and "execution-brief" in e for e in errors)


class TestConciseBriefPasses:
    def test_real_short_plan_passes_full_validation(self, tmp_path) -> None:
        """A ~180-word complete brief clears every gate (min words is a floor
        against EMPTY plans, not a verbosity mandate)."""
        config = ConfigFactory.create(repo_root=tmp_path)
        task = TaskFactory.create(
            id=9863, title="Cap pipeline flow dots with overflow badge"
        )

        errors = validate_plan(task, CONCISE_BRIEF, "full", config=config)

        assert errors == []

    def test_min_words_floor_rejects_skeletal_plans(self, tmp_path) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)
        task = TaskFactory.create(id=1, title="Skeletal")
        skeletal = "\n\n".join(
            f"{s}\nx"
            for s in (
                "## Intent",
                "## Approach",
                "## Files to Modify",
                "## New Files",
                "## File Delta",
                "## Task Graph",
                "## Testing Strategy",
                "## Acceptance Criteria",
                "## Key Considerations",
            )
        )

        errors = validate_plan(task, skeletal, "full", config=config)

        assert any("words" in e for e in errors)


class TestPromptShape:
    @pytest.mark.asyncio
    async def test_planner_prompt_states_budget_and_brief_shape(
        self, config, event_bus
    ) -> None:
        from planner import PlannerRunner

        runner = PlannerRunner(config, event_bus)
        task = TaskFactory.create(id=7, title="Some feature", body="Do the thing")
        prompt, _stats = await runner._build_prompt_with_stats(task)

        assert "SHORT EXECUTION BRIEF" in prompt
        assert "HARD BUDGET" in prompt
        assert str(min(config.max_plan_chars, config.max_impl_plan_chars)) in prompt
        assert "<your detailed implementation plan here>" not in prompt
        assert "TASK granularity" in prompt

    def test_builder_voter_carries_anti_verbosity_guard(self) -> None:
        assert "Brevity is NOT a finding" in BUILDER_PROMPT
        assert '"Add more detail" is not a valid concern' in BUILDER_PROMPT


class TestKnobDefaults:
    def test_min_plan_words_default_is_a_floor_not_a_mandate(self) -> None:
        assert HydraFlowConfig().min_plan_words == 60
