"""Regression pins for the #11298 complexity-default audit.

The bug: ``_result_from_dict`` defaulted a missing/invalid
``complexity_score`` to **0** ("trivially simple") while the triage prompt
never requested the field — so every issue recorded complexity 0 and the
#11304/#11305 tier gates skipped plan review + full planning on
essentially everything (observed live: epic-scale #11298 scored 0).

Pins:
1. Absent or non-numeric complexity parses to ``None``, never 0.
2. A ``None`` score is conservative at BOTH consumers, whose safe
   directions are opposite: the plan-tier gate reads it as maximally
   complex (full review + full plan), while epic auto-decomposition
   skips it (absence is not evidence of epic scale).
3. The triage prompt actually requests the field — the root cause.
"""

from __future__ import annotations

from types import SimpleNamespace

from config import HydraFlowConfig
from models import TriageResult
from triage import TriageRunner


def _parse(data: dict) -> TriageResult:
    return TriageRunner._result_from_dict({"ready": True, **data}, issue_number=1)


def test_missing_complexity_is_none_not_zero() -> None:
    assert _parse({}).complexity_score is None


def test_non_numeric_complexity_is_none_not_zero() -> None:
    assert _parse({"complexity_score": "high"}).complexity_score is None


def test_present_complexity_is_clamped() -> None:
    assert _parse({"complexity_score": 7}).complexity_score == 7
    assert _parse({"complexity_score": 15}).complexity_score == 10


def test_none_reads_as_max_complexity_at_the_tier_gate() -> None:
    from plan_phase import PlanPhase

    phase = object.__new__(PlanPhase)
    phase._config = HydraFlowConfig()
    phase._issue_cache = SimpleNamespace(
        latest_classification=lambda _id: SimpleNamespace(
            payload={"complexity_score": None}
        )
    )
    phase._state = SimpleNamespace(get_route_back_count=lambda _id: 0)
    phase._has_escalation_label = lambda _issue: False
    skip, complexity = phase._skip_plan_review(SimpleNamespace(id=1))
    assert complexity == 10
    assert skip is False
    assert phase._forced_plan_scale(SimpleNamespace(id=1)) is None


def test_none_never_triggers_epic_decomposition() -> None:
    import asyncio

    from models import TriageResult
    from triage_phase import TriagePhase

    phase = object.__new__(TriagePhase)
    phase._config = HydraFlowConfig()
    phase._epic_manager = object()  # wired, so only the score gates
    result = TriageResult(issue_number=1, ready=True, complexity_score=None)
    issue = SimpleNamespace(id=1, tags=[])
    decided = asyncio.run(phase._maybe_decompose(issue, result))
    assert decided is False


def test_prompt_requests_complexity_score() -> None:
    import inspect

    source = inspect.getsource(TriageRunner)
    assert '"complexity_score"' in source
    assert (
        "complexity_score"
        in source[source.find("Complexity score") : source.find("## Instructions")]
    )
