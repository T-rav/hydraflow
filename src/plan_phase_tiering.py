"""Size tiering and triage-hint gates of :class:`plan_phase.PlanPhase`.

Extracted VERBATIM from ``plan_phase.py`` (god-class decomposition, Refs
#11547) as a mixin; ``PlanPhase`` inherits :class:`PlanTieringMixin`.

One cohesive concern: the #11298 light lane. The label predicates and triage
hints that describe how big an issue is, the shared ``_tier_eligible`` guard
the three tier decisions share (skip adversarial review, force the lite plan
scale), and the light-lane route that sends a scored-simple issue straight to
``hydraflow-ready``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from flows import FlowState
from issue_cache import classification_complexity
from models import PlanResult, Task
from plan_constants import PlanScale
from plan_phase_common import _PRIORITY_LABELS

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from issue_cache import IssueCache
    from ports import PRPort
    from state import StateTracker

# Same logger as the host — the moved code's records keep their
# pre-extraction ``hydraflow.plan_phase`` origin.
logger = logging.getLogger("hydraflow.plan_phase")


class PlanTieringMixin:
    """Size tiering and triage-hint gates of :class:`plan_phase.PlanPhase`."""

    # ------------------------------------------------------------------
    # Collaborator seams — attributes and methods provided by PlanPhase or a
    # sibling mixin. The method declarations are TYPE_CHECKING-only on
    # purpose: a runtime ``...`` body would take precedence over the real
    # implementation whenever the declaring mixin precedes the implementing
    # one in the host's MRO (#11629).
    # ------------------------------------------------------------------
    _config: HydraFlowConfig
    _issue_cache: IssueCache | None
    _prs: PRPort
    _state: StateTracker

    def _has_escalation_label(self, issue: Task) -> bool:
        """True if *issue* carries one of ``config.research_escalation_labels``.

        Shared by :meth:`_should_research` and the ADR-0107 discover-helper
        gate (:meth:`_should_discover_helper`) — both treat an
        operator/loop-applied escalation label as a signal that the issue
        warrants deeper pre-planning work.
        """
        escalation_labels = {
            lbl.lower() for lbl in self._config.research_escalation_labels
        }
        return any(tag.lower() in escalation_labels for tag in issue.tags)

    def _is_memory_backlog_issue(self, issue: Task) -> bool:
        """True if *issue* carries a ``config.memory_backlog_label`` tag.

        Memory-backlog issues (ADR-0089) promote a captured *behavioral* memory
        to the find queue. When the shape gate can't pick one enforcement
        direction for one, it resolves as captured (closed) rather than a HITL
        escalation — the memory is already the rule (#10292).
        """
        backlog_labels = {lbl.lower() for lbl in self._config.memory_backlog_label}
        return any(tag.lower() in backlog_labels for tag in issue.tags)

    def _has_priority_label(self, issue: Task) -> bool:
        """True if *issue* carries a P0/P1/P2 priority label (#10311).

        Mirrors ``issue_refinement_loop._PRIORITY_LABELS`` (the labels
        ``IssueRefinementLoop`` manages). A shape fork on an issue WITHOUT one is
        deferred rather than HITL-escalated: HITL is for prioritized human
        direction choices, not unrefined/low-value forks.
        """
        priority = {lbl.lower() for lbl in _PRIORITY_LABELS}
        return any(tag.lower() in priority for tag in issue.tags)

    def _triage_hints(self, issue: Task) -> tuple[int, bool]:
        """Return ``(clarity_score, needs_discovery)`` triage HINTS for *issue*.

        ADR-0107: Triage no longer treats these as a routing verdict — it
        records them on the issue's ``IssueCache`` classification record and
        the planner's decision gate reads them back here. Missing cache / no
        classification record yet
        (e.g. ``issue_cache`` disabled, or the issue predates classification)
        reads as the well-specified default ``(10, False)`` — the gate's
        conservative "no helper needed" reading.
        """
        if self._issue_cache is None:
            return 10, False
        record = self._issue_cache.latest_classification(issue.id)
        if record is None:
            return 10, False
        return (
            int(record.payload.get("clarity_score", 10)),
            bool(record.payload.get("needs_discovery", False)),
        )

    def _issue_complexity(self, issue: Task) -> int | None:
        """Triage's complexity_score for *issue*; ``None`` when unknown.

        ``None`` (not a sentinel int) marks an unclassified/unreadable
        score so the tier guard can refuse eligibility at EVERY threshold.
        The prior sentinel-10 collapsed 'unknown' into 'confirmed maximal'
        at ``threshold=10`` (a valid config value), silently skipping the
        review for never-classified issues — found by the sampled re-audit
        on #11304 (#11314, audit-upheld).
        """
        return classification_complexity(self._issue_cache, issue.id)

    def _skip_plan_review(self, issue: Task) -> tuple[bool, int]:
        """#11298 size tiering: does this issue skip the adversarial review?

        Returns ``(skip, complexity)``. Skip only when ALL hold: tiering is
        enabled (threshold > 0), triage scored the issue at or below the
        threshold, the issue has never been routed back (a cycled plan is
        evidence the cheap path failed), and it carries no escalation label.
        The implement-side skill gauntlet still reviews the CODE either way —
        this trades plan-stage ceremony, not merge safety.
        """
        threshold = int(getattr(self._config, "plan_review_min_complexity", 0))
        return self._tier_eligible(issue, threshold)

    def _tier_eligible(self, issue: Task, threshold: int) -> tuple[bool, int]:
        """Shared #11298 tier guard: is *issue* simple enough for a light path?

        Returns ``(eligible, complexity)``. Eligible only when ALL hold:
        the threshold is enabled (> 0), triage actually scored the issue
        (an unknown score is ineligible at EVERY threshold — #11314) at or
        below it, the issue has never been routed back (a cycled plan is
        evidence the cheap path failed), and it carries no escalation
        label. An unknown score reports as 10 for logging.
        """
        complexity = self._issue_complexity(issue)
        if complexity is None:
            return False, 10
        if threshold <= 0:
            return False, complexity
        if complexity > threshold:
            return False, complexity
        if self._state.get_route_back_count(issue.id) > 0:
            return False, complexity
        if self._has_escalation_label(issue):
            return False, complexity
        return True, complexity

    def _forced_plan_scale(self, issue: Task) -> PlanScale | None:
        """#11298 size tiering, planner side: force the lite plan scale?

        Returns ``"lite"`` when the issue passes the shared tier guard
        against ``config.planner_lite_min_complexity``, else ``None`` (the
        planner falls back to its own heuristic scale detection). Rides the
        existing lite-plan prompt/validation machinery — no new prompt
        branch. Self-healing escape valve: a lite plan that fails review
        routes back, and the route-back count then disqualifies the issue
        from tiering, so the next round plans at full scale.
        """
        threshold = int(getattr(self._config, "planner_lite_min_complexity", 0))
        eligible, complexity = self._tier_eligible(issue, threshold)
        if eligible:
            logger.info(
                "Issue #%d complexity %d <= %d — forcing lite plan scale (#11298)",
                issue.id,
                complexity,
                threshold,
            )
            return "lite"
        return None

    # -- flow nodes ---------------------------------------------------------

    async def _route_light_lane(self, issue: Task, state: FlowState) -> bool:
        """#11298 light lane: route a triage-scored simple issue to the
        single-session auto-agent (one spawn: read issue -> implement ->
        test -> PR) instead of the staged plan/review pipeline.

        The claim-label swap removes the issue from every plan-stage
        queue; AutoAgentPreflightLoop polls the claim label for intake and
        crash recovery. Shared _tier_eligible guard: cycled, escalated, or
        unscored issues never route here, and an auto-agent exhaustion
        falls BACK to this pipeline (never to a human). Returns True when
        routed (the flow stops); mutates *state* accordingly.
        """
        if self._config.uses_issue_driver():
            # #11535: under ``issue_controller`` a fenced IssueDriver already
            # owns this issue. Routing it to the single-session auto-agent would
            # hand the same issue to a second owner the driver does not control
            # — the exact hazard the controller exists to remove. Inert under
            # Classic, where this returns False and the lane behaves as before.
            return False
        if not self._config.auto_agent_light_intake_enabled:
            return False
        if not self._config.auto_agent_preflight_enabled:
            # Stranding guard: routing claims the issue out of every queue,
            # so never route when the consuming loop is config-disabled —
            # the claim label has no TTL redrive of its own.
            return False
        eligible, complexity = self._tier_eligible(
            issue, self._config.auto_agent_light_max_complexity
        )
        if not eligible:
            return False
        logger.info(
            "Issue #%d complexity %d <= %d — routing to the "
            "auto-agent light lane (#11298)",
            issue.id,
            complexity,
            self._config.auto_agent_light_max_complexity,
        )
        await self._prs.swap_pipeline_labels(
            issue.id, self._config.light_autofix_label[0]
        )
        state["result"] = PlanResult(
            issue_number=issue.id,
            success=True,
            summary=(
                f"light-lane: routed to single-session auto-agent "
                f"(complexity {complexity}; #11298)"
            ),
        )
        state["_stop"] = True
        state["_skip_tail"] = True
        return True
