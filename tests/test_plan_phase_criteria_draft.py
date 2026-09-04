"""The pre-implementation criteria escape the plan phase (ADR-0149).

`_run_spec_ac_and_judge` drafted acceptance criteria before any code
existed, handed them to SpecJudge and dropped them on the floor. These
tests pin that they now come back, because that draft is what fills the
change chain's `criteria.md` — the one criteria artifact that exists early
enough to gate anything.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from models import Task
from pending_concerns import AdversarialState
from plan_phase_adversarial import CriteriaDraft, PlanAdversarialMixin


class _Phase(PlanAdversarialMixin):
    """Bare host for the mixin — PlanPhase's other concerns are not under test."""

    def __init__(self, *, ac_agent=None, judge_agent=None) -> None:
        self._spec_ac_agent = ac_agent
        self._spec_judge_agent = judge_agent
        self._adversarial_budget = 1
        self._bus = MagicMock()
        self._bus.publish = AsyncMock()
        self._state = MagicMock()
        self._ensemble_agents = None
        self._surfacer_agent = None

    def _persist_adversarial_state(self, issue, adv) -> None:
        return None


def _task() -> Task:
    return Task(id=7, title="Add a thing", body="Please add it.")


@pytest.fixture
def ac_agent() -> AsyncMock:
    agent = AsyncMock()
    agent.run = AsyncMock(
        return_value='{"acceptance_criteria": ["returns 404 for an unknown id"]}'
    )
    return agent


@pytest.fixture
def judge_agent() -> AsyncMock:
    agent = AsyncMock()
    agent.run = AsyncMock(return_value='{"verdict": "PASS", "concerns": []}')
    return agent


@pytest.mark.asyncio
async def test_returns_none_when_the_stage_is_unconfigured():
    phase = _Phase()

    result = await phase._run_spec_ac_and_judge(
        _task(), AdversarialState(phase="plan"), "a plan"
    )

    assert result is None


@pytest.mark.asyncio
async def test_returns_a_draft_when_the_stage_is_configured(ac_agent, judge_agent):
    phase = _Phase(ac_agent=ac_agent, judge_agent=judge_agent)

    result = await phase._run_spec_ac_and_judge(
        _task(), AdversarialState(phase="plan"), "a plan"
    )

    assert isinstance(result, CriteriaDraft)


@pytest.mark.asyncio
async def test_the_draft_carries_the_criteria_the_generator_produced(
    ac_agent, judge_agent
):
    phase = _Phase(ac_agent=ac_agent, judge_agent=judge_agent)

    result = await phase._run_spec_ac_and_judge(
        _task(), AdversarialState(phase="plan"), "a plan"
    )

    assert result is not None
    assert result.criteria == ("returns 404 for an unknown id",)


@pytest.mark.asyncio
async def test_a_clean_judge_run_reports_pass(ac_agent, judge_agent):
    phase = _Phase(ac_agent=ac_agent, judge_agent=judge_agent)

    result = await phase._run_spec_ac_and_judge(
        _task(), AdversarialState(phase="plan"), "a plan"
    )

    assert result is not None
    assert result.judge_verdict == "PASS"


@pytest.mark.asyncio
async def test_the_existing_side_effects_on_adversarial_state_still_happen(
    ac_agent, judge_agent
):
    phase = _Phase(ac_agent=ac_agent, judge_agent=judge_agent)
    adv = AdversarialState(phase="plan")

    await phase._run_spec_ac_and_judge(_task(), adv, "a plan")

    assert [run.stage for run in adv.stage_history] == [
        "spec_ac_generator",
        "spec_judge",
    ]


@pytest.mark.asyncio
async def test_the_stage_still_marks_itself_current(ac_agent, judge_agent):
    phase = _Phase(ac_agent=ac_agent, judge_agent=judge_agent)
    adv = AdversarialState(phase="plan")

    await phase._run_spec_ac_and_judge(_task(), adv, "a plan")

    assert adv.current_stage == "spec_judge"
