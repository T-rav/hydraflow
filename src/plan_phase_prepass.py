"""ADR-0107 research / discover / shape pre-pass helpers of :class:`plan_phase.PlanPhase`.

Extracted VERBATIM from ``plan_phase.py`` (god-class decomposition, Refs
#11547) as a mixin; ``PlanPhase`` inherits :class:`PlanPrepassMixin`.

One cohesive concern: the on-demand research the planner may run *before*
drafting. Each ADR-0107 decision gate sits next to the helper it admits —
``_should_research``, ``_should_discover_helper`` / ``_run_discover_helper``,
``_should_shape_helper`` / ``_run_shape_helper`` — plus the product-track
detection that suppresses them. The flow node that sequences these lives in
``plan_phase_flow``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from exception_classify import reraise_on_credit_or_bug
from models import (
    ConversationTurn,
    DiscoverResult,
    ShapeConversation,
    ShapeTurnResult,
    Task,
)

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from discover_runner import DiscoverRunner
    from ports import IssueStorePort, PRPort
    from research_runner import ResearchRunner
    from shape_runner import ShapeRunner
    from state import StateTracker

# Same logger as the host — the moved code's records keep their
# pre-extraction ``hydraflow.plan_phase`` origin.
logger = logging.getLogger("hydraflow.plan_phase")


class PlanPrepassMixin:
    """ADR-0107 research / discover / shape pre-pass helpers of :class:`plan_phase.PlanPhase`."""

    # ------------------------------------------------------------------
    # Collaborator seams — attributes and methods provided by PlanPhase or a
    # sibling mixin. The method declarations are TYPE_CHECKING-only on
    # purpose: a runtime ``...`` body would take precedence over the real
    # implementation whenever the declaring mixin precedes the implementing
    # one in the host's MRO (#11629).
    # ------------------------------------------------------------------
    _config: HydraFlowConfig
    _discover_runner: DiscoverRunner | None
    _prs: PRPort
    _research_runner: ResearchRunner | None
    _shape_runner: ShapeRunner | None
    _state: StateTracker
    _store: IssueStorePort

    if TYPE_CHECKING:

        def _has_escalation_label(
            self, issue: Task
        ) -> bool: ...  # provided by PlanTieringMixin

        def _is_epic_child(self, issue: Task) -> bool: ...  # provided by PlanEpicMixin

        def _triage_hints(
            self, issue: Task
        ) -> tuple[int, bool]: ...  # provided by PlanTieringMixin

    def _should_research(self, issue: Task) -> bool:
        """Return True if the research pre-pass should run before planning *issue*.

        Research spawns a full extra codebase-exploration subprocess on top of
        the planner's own exploration, so it is gated rather than run for every
        issue. With ``research_enabled`` on and a runner wired, research runs
        only for issues that need the depth:

        - **Escalated** — the issue carries one of
          ``config.research_escalation_labels``.
        - **Cycled / failing to land** — the issue has been routed back to
          planning at least once (route-back count > 0).

        The common first-pass issue skips research and lets the planner explore
        once.
        """
        if not getattr(self._config, "research_enabled", True):
            return False
        if self._research_runner is None:
            return False
        # Cycled / failing to land: routed back from a later stage at least once.
        if self._state.get_route_back_count(issue.id) > 0:
            return True
        # Escalated: operator/loop flagged the issue for deeper handling.
        return self._has_escalation_label(issue)

    def _should_discover_helper(self, issue: Task) -> bool:
        """ADR-0107 planner decision gate: run the discover helper before planning?

        Consulted only when a ``DiscoverRunner`` is wired — with no runner
        (e.g. tests that build PlanPhase directly), this always returns False
        and the planner plans without a discovery pre-pass.

        Conservative default (per ADR-0107): a well-specified issue plans
        directly with no helper. The gate fires when any of —

        - **needs_discovery hint** — Triage's LLM flagged the issue as vague.
        - **clarity_score hint** below ``config.clarity_threshold``.
        - **Cycled / failing to land** — routed back to plan at least once
          (``StateTracker.get_route_back_count``).
        - **Escalated** — issue carries a ``research_escalation_labels`` tag.

        Epic children are excluded outright: they are already-scoped
        decomposition output from a parent epic's planning pass, so
        re-running product discovery on them would be redundant.
        """
        if self._discover_runner is None:
            return False
        if self._is_epic_child(issue):
            return False
        clarity_score, needs_discovery = self._triage_hints(issue)
        return (
            needs_discovery
            or clarity_score < self._config.clarity_threshold
            or self._state.get_route_back_count(issue.id) > 0
            or self._has_escalation_label(issue)
        )

    async def _run_discover_helper(
        self, issue: Task, *, guidance: str
    ) -> DiscoverResult | None:
        """Invoke ``DiscoverRunner`` as an on-demand research pre-pass (ADR-0107).

        This is a synchronous in-process helper call, not a stage transition —
        the engine is reused unmodified; only the caller changes. Bounded
        internally by ``config.max_discover_attempts`` /
        ``max_discover_expansions`` (read by ``DiscoverRunner.discover``
        itself), the same knobs that bounded the standalone Discover phase —
        they now bound this planner-invoked sub-step instead. Returns
        ``None`` (never raises) on failure so planning proceeds without a
        research brief rather than being blocked by it.
        """
        assert self._discover_runner is not None  # guarded by caller
        try:
            result = await self._discover_runner.discover(issue, guidance=guidance)
        except Exception as exc:
            # Dark-factory contract: credit/auth/likely-bug exceptions must
            # propagate so the loop pauses on the billing signal instead of
            # silently planning without research.
            reraise_on_credit_or_bug(exc)
            logger.warning(
                "Discover helper failed for issue #%d — planning without a "
                "research brief",
                issue.id,
                exc_info=True,
            )
            return None
        try:
            await self._prs.post_comment(
                issue.id, self._format_discover_brief(issue, result)
            )
        except Exception:
            logger.warning(
                "Failed to post discover-helper brief for issue #%d",
                issue.id,
                exc_info=True,
            )
        return result

    @staticmethod
    def _format_discover_brief(issue: Task, result: DiscoverResult) -> str:
        """Format a ``DiscoverResult`` as a GitHub comment for the audit trail."""
        lines = [
            "## Discovery Research (planner-invoked helper)",
            "",
            f"*ADR-0107 — issue #{issue.id} routed Triage → Plan directly; "
            f"the planner's decision gate determined discovery research was "
            f"warranted before planning.*",
            "",
            result.research_brief,
        ]
        if result.opportunities:
            lines.extend(["", "### Opportunities", ""])
            lines.extend(f"- {o}" for o in result.opportunities)
        return "\n".join(lines)

    def _should_shape_helper(
        self, issue: Task, discover_result: DiscoverResult | None
    ) -> bool:
        """ADR-0107 planner decision gate: does discovery warrant a shaping turn?

        Only consulted after the discover helper has already run — shaping
        without a discovery brief has nothing to shape. Fires when the brief
        surfaced genuinely divergent opportunities (2+) that need a human
        choice, per ADR-0107's framing of shaping as direction-selection
        rather than open-ended exploration. Requires a ``ShapeRunner`` to be
        wired; with no runner this always returns False.
        """
        if self._shape_runner is None or discover_result is None:
            return False
        return len(discover_result.opportunities) >= 2

    async def _run_shape_helper(
        self, issue: Task, discover_result: DiscoverResult, *, guidance: str
    ) -> ShapeTurnResult | None:
        """Invoke ``ShapeRunner`` for one bounded conversation turn (ADR-0107).

        Reuses the same ``ShapeConversation`` state slot the standalone Shape
        phase used (``StateTracker.get/set_shape_conversation``) so this
        helper composes with that machinery rather than reimplementing it.
        Bounded by ``config.max_shape_turns`` (conversation-length ceiling —
        returns ``None`` once hit, same as the standalone phase forcing
        finalization) and ``config.max_shape_attempts`` (retried internally
        by ``ShapeRunner.run_turn`` against the shape-coherence evaluator).

        Because shaping is human-interactive, a non-final result is NOT
        waited on synchronously — the caller (``_plan_one``) escalates to
        HITL per ADR-0107's "yield to the existing human-steering channel"
        design rather than blocking the plan tick.
        """
        assert self._shape_runner is not None  # guarded by caller
        conv = self._state.get_shape_conversation(issue.id) or ShapeConversation(
            issue_number=issue.id,
            started_at=datetime.now(UTC).isoformat(),
        )
        if len(conv.turns) >= self._config.max_shape_turns:
            logger.warning(
                "Shape helper hit max_shape_turns (%d) for issue #%d without "
                "finalizing",
                self._config.max_shape_turns,
                issue.id,
            )
            return None
        try:
            result = await self._shape_runner.run_turn(
                issue,
                conv,
                research_brief=discover_result.research_brief,
                guidance=guidance,
            )
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning("Shape helper failed for issue #%d", issue.id, exc_info=True)
            return None
        conv.turns.append(
            ConversationTurn(
                role="agent",
                content=result.content,
                timestamp=datetime.now(UTC).isoformat(),
            )
        )
        conv.last_activity_at = datetime.now(UTC).isoformat()
        self._state.set_shape_conversation(issue.id, conv)
        return result

    async def _is_product_track_issue(self, issue: Task) -> bool:
        """Detect if an issue came through the product discovery/shape track."""
        enriched = await self._store.enrich_with_comments(issue)
        for comment in enriched.comments or []:
            if "DECOMPOSITION REQUIRED" in comment:
                return True
        return False
