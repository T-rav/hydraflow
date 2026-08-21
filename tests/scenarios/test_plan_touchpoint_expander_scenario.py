"""MockWorld scenarios for the plan touchpoint-expander (ADR-0063 W3b).

Drives ``PlanPhase`` end-to-end against the harness fakes to assert the
load-bearing transitions:

* First PlanReviewer review returns blocking findings → expander
  dispatched → second review against the enriched plan reaches READY.
* Expander surfaces zero touchpoints → no second review fires;
  existing route-back path runs unchanged.
* Second review still blocking → expander runs once only; the cache
  records the still-blocking verdict so the READY-stage gate routes
  back to plan (dark-factory contract: never deadlock on expansion).

Pattern mirrors ``test_adversarial_pipeline.py`` — attach stubs to
``world.harness.plan_phase`` before invoking ``plan_issues``.
"""

from __future__ import annotations

from typing import Any

import pytest

from models import (
    PlanFinding,
    PlanFindingSeverity,
    PlanResult,
    PlanReview,
    Task,
)
from plan_touchpoint_expander import (
    ExpandedTouchpoints,
    Touchpoint,
)
from tests.conftest import PlanResultFactory, TaskFactory
from tests.helpers import supply_once

pytestmark = pytest.mark.scenario


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class _ScriptedReviewer:
    """Returns a scripted sequence of ``PlanReview`` objects per call."""

    def __init__(self, reviews: list[PlanReview]) -> None:
        self._reviews = list(reviews)
        self.calls: list[tuple[Task, PlanResult]] = []

    async def review(
        self,
        task: Task,
        plan_result: PlanResult,
        *,
        plan_version: int = 1,
        prior_summary: str | None = None,
        prior_findings: list | None = None,
    ) -> PlanReview:
        self.calls.append((task, plan_result))
        self.prior_contexts = getattr(self, "prior_contexts", [])
        self.prior_contexts.append((prior_summary, prior_findings))
        if not self._reviews:
            raise AssertionError("ran out of scripted reviews")
        return self._reviews.pop(0)


class _ScriptedExpander:
    """Returns a scripted ``ExpandedTouchpoints`` and records calls."""

    def __init__(self, output: ExpandedTouchpoints) -> None:
        self.output = output
        self.calls: list[tuple[str, PlanReview]] = []

    async def expand_touchpoints(
        self,
        *,
        original_plan: str,
        reviewer_failure: PlanReview,
    ) -> ExpandedTouchpoints:
        self.calls.append((original_plan, reviewer_failure))
        return self.output


def _blocking(
    issue_id: int, *, description: str = "missed ADR cross-ref"
) -> PlanReview:
    return PlanReview(
        issue_number=issue_id,
        plan_version=1,
        success=True,
        findings=[
            PlanFinding(
                severity=PlanFindingSeverity.HIGH,
                dimension="correctness",
                description=description,
            ),
        ],
        summary="1 high finding",
    )


def _clean(issue_id: int) -> PlanReview:
    return PlanReview(
        issue_number=issue_id,
        plan_version=1,
        success=True,
        findings=[],
        summary="clean",
    )


def _setup_planner(harness: Any, issue_id: int) -> None:
    """Wire a planner that returns a successful, simple plan."""

    async def _planner_plan(*_args: Any, **_kwargs: Any) -> PlanResult:
        return PlanResultFactory.create(
            issue_number=issue_id,
            success=True,
            plan="Step 1: change schema\nStep 2: update tests",
            summary="Done",
            use_defaults=True,
        )

    harness.planners.plan = _planner_plan


def _wire_issue_cache(plan_phase: Any) -> dict[str, Any]:
    """Replace plan_phase._issue_cache with a record-capturing stub.

    Returns the dict that captures the final ``review_stored`` payload
    so scenarios can assert against the cached verdict.
    """
    captured: dict[str, Any] = {}

    class _Cache:
        def record_plan_stored(self, _issue_id: int, **_kw: Any) -> int:
            return 1

        def record_review_stored(
            self,
            issue_id: int,
            *,
            review_text: str,
            has_blocking: bool,
            findings: list[dict],
        ) -> None:
            captured["issue_id"] = issue_id
            captured["review_text"] = review_text
            captured["has_blocking"] = has_blocking
            captured["findings"] = findings

    plan_phase._issue_cache = _Cache()
    return captured


# ---------------------------------------------------------------------------
# Scenario 1: blocking → expander → re-review clean → READY.
# ---------------------------------------------------------------------------


class TestS1ExpanderUnblocksReview:
    """First review blocks; expander surfaces touchpoints; re-review clean."""

    async def test_blocking_then_expander_then_clean(self, mock_world) -> None:
        world = mock_world
        world.add_issue(
            301,
            "Touch ADR-0021 schema",
            "Plan touches StateData and requires schema migration.",
            labels=["hydraflow-plan"],
        )
        harness = world.harness
        phase = harness.plan_phase

        reviewer = _ScriptedReviewer([_blocking(301), _clean(301)])
        expander = _ScriptedExpander(
            ExpandedTouchpoints(
                touchpoints=[
                    Touchpoint(
                        kind="adr",
                        ref="ADR-0021",
                        title="Persistence architecture",
                        why="Plan changes StateData schema",
                    ),
                    Touchpoint(
                        kind="wiki",
                        ref="architecture-state-persistence.md",
                        title="Pydantic schema evolution",
                        why="Plan touches Pydantic models",
                    ),
                ]
            )
        )
        phase._plan_reviewer = reviewer
        phase._touchpoint_expander = expander
        captured = _wire_issue_cache(phase)

        _setup_planner(harness, 301)
        issue = TaskFactory.create(id=301, tags=["hydraflow-plan"])
        harness.store.get_plannable = supply_once([issue])

        await phase.plan_issues()

        # Expander dispatched once; reviewer ran twice (initial + re-review).
        assert len(expander.calls) == 1
        assert len(reviewer.calls) == 2

        # Re-review saw the enriched plan with the touchpoints block.
        second_plan = reviewer.calls[1][1].plan
        assert "ADR-0021" in second_plan
        assert "EXPANDED_TOUCHPOINTS" in second_plan

        # Cache reflects the SECOND review's verdict.
        assert captured["has_blocking"] is False
        assert captured["findings"] == []

        # READY-stage transition fired (label flipped on the FakeGitHub side).
        labels = world.github.issue(301).labels
        assert "hydraflow-ready" in labels, (
            f"expected ready label after expanded re-review; got {labels}"
        )


# ---------------------------------------------------------------------------
# Scenario 2: blocking → expander → no touchpoints → fall through.
# ---------------------------------------------------------------------------


class TestS2EmptyExpansionFallsThrough:
    """Expander surfaces zero touchpoints → no re-review; route-back path runs."""

    async def test_empty_expansion_records_first_review(self, mock_world) -> None:
        world = mock_world
        world.add_issue(
            302,
            "Touch nothing important",
            "Plan body.",
            labels=["hydraflow-plan"],
        )
        harness = world.harness
        phase = harness.plan_phase

        reviewer = _ScriptedReviewer([_blocking(302)])
        expander = _ScriptedExpander(ExpandedTouchpoints(touchpoints=[]))
        phase._plan_reviewer = reviewer
        phase._touchpoint_expander = expander
        captured = _wire_issue_cache(phase)

        _setup_planner(harness, 302)
        issue = TaskFactory.create(id=302, tags=["hydraflow-plan"])
        harness.store.get_plannable = supply_once([issue])

        await phase.plan_issues()

        # Expander ran but no re-review fired.
        assert len(expander.calls) == 1
        assert len(reviewer.calls) == 1

        # The cached record reflects the original blocking verdict so the
        # READY-stage gate will route back via the existing path.
        assert captured["has_blocking"] is True


# ---------------------------------------------------------------------------
# Scenario 3: blocking → expander → still blocking → no third try.
# ---------------------------------------------------------------------------


class TestS3StillBlockingAfterExpansion:
    """Re-review still blocking → expander runs once only; cache the second verdict.

    Per ADR-0063 W3b: bounded to one expansion attempt. A still-blocking
    second review means the issue routes back via the existing READY-stage
    gate (dark-factory contract: never deadlock on expansion).
    """

    async def test_still_blocking_routes_back_via_gate(self, mock_world) -> None:
        world = mock_world
        world.add_issue(
            303,
            "Stubborn plan",
            "Plan body.",
            labels=["hydraflow-plan"],
        )
        harness = world.harness
        phase = harness.plan_phase

        reviewer = _ScriptedReviewer(
            [
                _blocking(303, description="first failure"),
                _blocking(303, description="still failing after enrichment"),
            ]
        )
        expander = _ScriptedExpander(
            ExpandedTouchpoints(
                touchpoints=[
                    Touchpoint(
                        kind="adr",
                        ref="ADR-0001",
                        title="Async loops",
                        why="touched module",
                    ),
                ]
            )
        )
        phase._plan_reviewer = reviewer
        phase._touchpoint_expander = expander
        captured = _wire_issue_cache(phase)

        _setup_planner(harness, 303)
        issue = TaskFactory.create(id=303, tags=["hydraflow-plan"])
        harness.store.get_plannable = supply_once([issue])

        await phase.plan_issues()

        # Expander runs exactly once even though the re-review still blocks.
        assert len(expander.calls) == 1
        assert len(reviewer.calls) == 2

        # Cache reflects the second (still-blocking) verdict so the
        # existing READY-stage gate routes the issue back to plan.
        assert captured["has_blocking"] is True
        # Description from the second blocking review wins.
        assert any(
            f["description"] == "still failing after enrichment"
            for f in captured["findings"]
        )


# ---------------------------------------------------------------------------
# Scenario 4: #11298 size tiering — low-complexity issue skips the review
# spawn entirely but still writes the review_stored record the READY-stage
# gate requires.
# ---------------------------------------------------------------------------


class TestS4LightTierSkipsReview:
    """Triage-scored simple issue plans to READY with zero reviewer spawns."""

    async def test_low_complexity_skips_review_spawn(self, mock_world) -> None:
        world = mock_world
        world.add_issue(
            304,
            "Fix typo in operator panel label",
            "One-line copy fix.",
            labels=["hydraflow-plan"],
        )
        harness = world.harness
        phase = harness.plan_phase
        # Light lane is ON by default since #11590; this scenario exercises the
        # planner-side light *tier* fallback (lane off / preflight disabled), so
        # pin the lane off explicitly. S6 covers the lane-on routing.
        phase._config = phase._config.model_copy(
            update={"auto_agent_light_intake_enabled": False}
        )

        reviewer = _ScriptedReviewer([])  # any call would raise: no scripts
        phase._plan_reviewer = reviewer
        captured = _wire_issue_cache(phase)

        class _Classified:
            payload = {"complexity_score": 2}

        phase._issue_cache.latest_classification = lambda _id: _Classified()

        _setup_planner(harness, 304)
        issue = TaskFactory.create(id=304, tags=["hydraflow-plan"])
        harness.store.get_plannable = supply_once([issue])

        await phase.plan_issues()

        # No reviewer spawn — the whole point of the tier gate.
        assert reviewer.calls == []
        # READY-gate invariant: a review_stored record still lands, clean.
        assert captured["issue_id"] == 304
        assert captured["has_blocking"] is False
        assert "light-tier" in captured["review_text"]
        assert captured["findings"] == []


# ---------------------------------------------------------------------------
# Scenario 5: #11298 planner-side tiering — a triage-scored simple issue
# plans at forced-lite scale AND skips the review spawn (both tiers firing
# on the same light path).
# ---------------------------------------------------------------------------


class TestS5LightTierForcesLitePlan:
    """Simple issue: planner receives force_scale='lite', reviewer never spawns."""

    async def test_lite_scale_forced_and_review_skipped(self, mock_world) -> None:
        world = mock_world
        world.add_issue(
            305,
            "Fix typo in operator panel label",
            "One-line copy fix.",
            labels=["hydraflow-plan"],
        )
        harness = world.harness
        phase = harness.plan_phase
        # Light lane is ON by default since #11590; this scenario exercises the
        # planner-side light *tier* fallback (lane off / preflight disabled), so
        # pin the lane off explicitly. S6 covers the lane-on routing.
        phase._config = phase._config.model_copy(
            update={"auto_agent_light_intake_enabled": False}
        )

        reviewer = _ScriptedReviewer([])  # any call would raise: no scripts
        phase._plan_reviewer = reviewer
        captured = _wire_issue_cache(phase)

        class _Classified:
            payload = {"complexity_score": 2}

        phase._issue_cache.latest_classification = lambda _id: _Classified()

        plan_kwargs: list[dict] = []

        async def _planner_plan(*_args: Any, **kwargs: Any) -> PlanResult:
            plan_kwargs.append(kwargs)
            return PlanResultFactory.create(
                issue_number=305,
                success=True,
                plan="Step 1: fix the label",
                summary="Done",
                use_defaults=True,
            )

        harness.planners.plan = _planner_plan
        issue = TaskFactory.create(id=305, tags=["hydraflow-plan"])
        harness.store.get_plannable = supply_once([issue])

        await phase.plan_issues()

        # Planner-side tier: the spawn was asked for a lite-scale plan.
        assert plan_kwargs and plan_kwargs[0].get("force_scale") == "lite"
        # Review-side tier: no reviewer spawn, READY-gate record intact.
        assert reviewer.calls == []
        assert captured["has_blocking"] is False


# ---------------------------------------------------------------------------
# Scenario 6: #11298 light lane — a triage-scored simple issue routes to the
# single-session auto-agent claim label without any planner/reviewer spawn.
# ---------------------------------------------------------------------------


class TestS6LightLaneRoutesToAutoAgent:
    """Flag on + simple issue: claim-label swap, zero plan-stage spawns."""

    async def test_light_lane_swaps_claim_label(self, mock_world) -> None:
        world = mock_world
        world.add_issue(
            306,
            "Fix typo in operator panel label",
            "One-line copy fix.",
            labels=["hydraflow-plan"],
        )
        harness = world.harness
        phase = harness.plan_phase
        phase._config = phase._config.model_copy(
            update={"auto_agent_light_intake_enabled": True}
        )

        planned: list[int] = []

        async def _planner_plan(task: Task, *_args: Any, **_kw: Any) -> PlanResult:
            planned.append(task.id)
            return PlanResultFactory.create(issue_number=task.id, use_defaults=True)

        harness.planners.plan = _planner_plan
        reviewer = _ScriptedReviewer([])
        phase._plan_reviewer = reviewer

        class _Classified:
            payload = {"complexity_score": 2}

        _wire_issue_cache(phase)
        phase._issue_cache.latest_classification = lambda _id: _Classified()

        swaps: list[tuple[int, str]] = []
        original_swap = phase._prs.swap_pipeline_labels

        async def _record_swap(issue_id: int, label: str, *a: Any, **kw: Any):
            swaps.append((issue_id, label))
            return await original_swap(issue_id, label, *a, **kw)

        phase._prs.swap_pipeline_labels = _record_swap

        issue = TaskFactory.create(id=306, tags=["hydraflow-plan"])
        harness.store.get_plannable = supply_once([issue])

        await phase.plan_issues()

        # Routed: claim label swapped, no planner spawn, no reviewer spawn.
        assert (306, "hydraflow-auto-light") in swaps
        assert planned == []
        assert reviewer.calls == []
