"""Create an epic + child issues from a decomposition result and register it.

Extracted from ``TriagePhase._maybe_decompose`` (behavior-preserving, #ADR-0105
decompose-to-converge) so both the intake-triage decomposition path and a
later auto-agent decompose-on-stall path can share the same create/link/
register plumbing.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from escalation_reconcile import stamp_and_close

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from epic import EpicManager
    from models import EpicDecompResult, NewIssueSpec, Task
    from ports import PRPort
    from state import StateTracker

logger = logging.getLogger("hydraflow.issue_decomposer")

# Marker the DecompositionCouncil's direction pass uses to scope one child as
# "land the already-working slice" (see decomposition_council.py's direction
# prompt). Either a "salvage" label or a "[salvage]" title prefix counts --
# the council emits the former via NewIssueSpec.labels, but the title-prefix
# form is accepted too so a differently-shaped LLM reply still orders
# correctly instead of silently losing the safe-slice-first guarantee.
_SALVAGE_LABEL = "salvage"
_SALVAGE_TITLE_PREFIX = "[salvage]"


def _is_salvage_child(spec: NewIssueSpec) -> bool:
    """True if *spec* is marked as the "land the working slice" child."""
    if any(label.strip().lower() == _SALVAGE_LABEL for label in spec.labels):
        return True
    return spec.title.strip().lower().startswith(_SALVAGE_TITLE_PREFIX)


class IssueDecomposer:
    """Creates an epic + child issues from an ``EpicDecompResult`` and registers it."""

    def __init__(
        self,
        prs: PRPort,
        epic_manager: EpicManager,
        state: StateTracker,
        config: HydraFlowConfig,
    ) -> None:
        self._prs = prs
        self._epic_manager = epic_manager
        self._state = state
        self._config = config

    def _find_root_epic_number(self, task_id: int) -> int | None:
        """Walk the epic tree to find the root epic that owns *task_id*.

        Epics are not currently nested as children of other epics — a
        decomposed child's replacement epic has no persisted link back to
        the epic it was carved out of — so this resolves in a single hop
        today. The loop is defensive against future nesting (e.g. if an
        epic number is ever recorded as another epic's child) without
        requiring a new persisted parent-epic field for this task.
        """
        all_states = self._state.get_all_epic_states()
        current = task_id
        seen: set[int] = set()
        root: int | None = None
        while True:
            found: int | None = None
            for epic in all_states.values():
                if current in epic.child_issues:
                    found = epic.epic_number
                    break
            if found is None or found in seen:
                break
            root = found
            seen.add(found)
            current = found
        return root

    def _find_parent_epic(self, issue_number: int) -> int | None:
        """The epic that directly lists *issue_number* in its child_issues, or None.

        The direct parent (first hop), used to stamp epic-to-epic lineage on a
        replacement epic so nested rollup converges (#9757).
        """
        for epic in self._state.get_all_epic_states().values():
            if issue_number in epic.child_issues:
                return epic.epic_number
        return None

    async def create_epic_from_result(
        self,
        *,
        source_task: Task,
        result: EpicDecompResult,
        depth: int = 0,
        stall_context: str | None = None,
    ) -> int | None:
        """Create an epic + children from *result*, register it, close *source_task*.

        Returns the new epic issue number, or ``None`` when
        ``result.should_decompose`` is False, *depth* has hit
        ``config.max_decomposition_depth`` (the "depth-cap"), creating these
        children would push the decomposition's root epic to or past
        ``config.max_total_decomposition_children`` (the "fanout-cap"), or
        the epic issue failed to create. When *stall_context* is set, it is
        embedded into every child body (used by the auto-agent
        decompose-on-stall path to carry forward why the parent stalled, and
        to tell each child explicitly not to repeat that failure). Any child
        marked "salvage" (see :func:`_is_salvage_child`) -- a slice scoped to
        land the part of the parent's work that already works -- is created
        FIRST, ahead of the riskier children, so the safe slice ships before
        anything that might re-stall.
        *depth* is recorded on the new epic's ``EpicState.decomposition_depth``.
        """
        if not result.should_decompose:
            return None

        if depth >= self._config.max_decomposition_depth:
            logger.info(
                "Issue #%d decomposition blocked (depth-cap): depth=%d >= "
                "max_decomposition_depth=%d",
                source_task.id,
                depth,
                self._config.max_decomposition_depth,
            )
            return None

        root_epic_number = self._find_root_epic_number(source_task.id)
        existing_total = 0
        if root_epic_number is not None:
            root_state = self._state.get_epic_state(root_epic_number)
            if root_state is not None:
                existing_total = root_state.total_children
        new_child_count = len(result.children)
        if (
            existing_total + new_child_count
            >= self._config.max_total_decomposition_children
        ):
            logger.info(
                "Issue #%d decomposition blocked (fanout-cap): root #%s "
                "existing=%d + new=%d >= max_total_decomposition_children=%d",
                source_task.id,
                root_epic_number,
                existing_total,
                new_child_count,
                self._config.max_total_decomposition_children,
            )
            return None

        epic_label = self._config.epic_label[0]
        epic_child_label = self._config.epic_child_label[0]
        find_label = self._config.find_label[0]
        auto_child_label = self._config.auto_decomposed_child_label[0]

        # Create the epic issue
        epic_number = await self._prs.create_issue(
            result.epic_title,
            result.epic_body,
            [epic_label],
        )
        if epic_number <= 0:
            logger.warning(
                "Failed to create epic issue for decomposition of #%d",
                source_task.id,
            )
            return None

        # Create child issues. Salvage-marked children (the "land the
        # already-working slice" child a council may scope, see
        # DecompositionCouncil's direction prompt) go first so the safe
        # slice ships before the riskier follow-on children -- a stable
        # sort preserves relative order within each group.
        child_numbers: list[int] = []
        ordered_children = sorted(
            result.children, key=lambda spec: not _is_salvage_child(spec)
        )
        for child_spec in ordered_children:
            child_body = child_spec.body + f"\n\nParent Epic #{epic_number}"
            if stall_context:
                child_body += (
                    f"\n\nParent #{source_task.id} stalled on: {stall_context}. "
                    "This slice must not repeat that failure."
                )
            child_num = await self._prs.create_issue(
                child_spec.title,
                child_body,
                [epic_child_label, find_label, auto_child_label],
            )
            if child_num > 0:
                child_numbers.append(child_num)
                self._state.record_issue_created()

        # If not a single child issue was created, do NOT supersede the source.
        # Registering an empty epic + closing the source would silently drop the
        # stalled work AND skip the human-required escalation this terminal
        # replaced — strictly worse than paging a human. Leave the source open
        # (return None) so the caller falls through to human-required. (The
        # already-created epic issue is a rare orphan on this all-children-failed
        # path; preserving the source's work is what matters.)
        if not child_numbers:
            logger.warning(
                "Issue #%d decomposition produced 0 child issues (epic #%d) — "
                "leaving the source open for human-required rather than closing "
                "it behind an empty epic",
                source_task.id,
                epic_number,
            )
            # Close the just-created epic loudly (#9855): the 2026-07-18
            # label-registration failure orphaned 23 of these in one day —
            # "rare" only when child creation cannot systematically fail.
            await self._prs.post_comment(
                epic_number,
                "## Decomposition Aborted\n\n"
                "Every child-issue creation failed, so this epic has no "
                f"children. Source #{source_task.id} stays open for "
                "human-required escalation. Closing this orphan (#9855).",
            )
            await self._prs.close_issue(epic_number)
            return None

        # Register with EpicManager
        await self._epic_manager.register_epic(
            epic_number,
            result.epic_title,
            child_numbers,
            auto_decomposed=True,
        )

        # Record decomposition_depth and, when the source is itself a child of an
        # existing epic, the epic-to-epic lineage (#9757) so nested rollup can
        # converge: the parent epic only counts this superseded child as resolved
        # once THIS replacement epic closes.
        parent = self._find_parent_epic(source_task.id)
        if depth or parent is not None:
            epic_state = self._state.get_epic_state(epic_number)
            if epic_state is not None:
                if depth:
                    epic_state.decomposition_depth = depth
                if parent is not None:
                    epic_state.parent_epic = parent
                    epic_state.superseded_issue = source_task.id
                self._state.upsert_epic_state(epic_state)

        # Mark the source decomposed BEFORE the fallible GitHub comment/close.
        # This is the terminal's idempotency marker (decompose_or_escalate skips
        # an already-"decomposed" issue); writing it last meant a post_comment or
        # close_issue failure left the source un-marked and open, so the next
        # tick re-ran the council and created a DUPLICATE epic + children.
        self._state.mark_issue(source_task.id, "decomposed")

        # Close the original issue with a link to the epic (cosmetic cleanup —
        # the state transition above is what makes the decompose durable).
        await self._prs.post_comment(
            source_task.id,
            f"## Auto-Decomposed into Epic\n\n"
            f"This issue was automatically decomposed into epic #{epic_number} "
            f"with {len(child_numbers)} child issue(s).\n\n"
            f"**Reason:** {result.reasoning}\n\n"
            f"---\n*Generated by HydraFlow Triage*",
        )
        await stamp_and_close(self._prs, source_task.id)

        logger.info(
            "Issue #%d decomposed into epic #%d with %d children: %s",
            source_task.id,
            epic_number,
            len(child_numbers),
            child_numbers,
        )
        return epic_number
