"""Goal-driven PR unsticker — resolves ALL HITL causes autonomously."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from dedup_store import DedupStore
from exception_classify import reraise_on_credit_or_bug
from models import HITLUpdatePayload
from phase_utils import MemorySuggester

from ._causes import _CAUSE_PRIORITY, PRUnstickerCauseMixin, _classify_cause
from ._merge import PRUnstickerMergeMixin
from ._prompts import PRUnstickerPromptMixin
from ._reflection import PRUnstickerReflectionMixin
from ._resolve import PRUnstickerResolveMixin
from ._timeout import PRUnstickerTimeoutMixin

if TYPE_CHECKING:
    from agent import AgentRunner
    from config import Credentials, HydraFlowConfig
    from events import EventBus
    from hitl_runner import HITLRunner
    from issue_store import IssueStore
    from merge_conflict_resolver import MergeConflictResolver
    from models import HITLItem, UnstickResult
    from ports import IssueFetcherPort, PRPort, WorkspacePort
    from state import StateTracker
    from troubleshooting_store import (
        TroubleshootingPatternStore,
    )


logger = logging.getLogger("hydraflow.pr_unsticker")


class PRUnsticker(
    PRUnstickerCauseMixin,
    PRUnstickerMergeMixin,
    PRUnstickerPromptMixin,
    PRUnstickerReflectionMixin,
    PRUnstickerResolveMixin,
    PRUnstickerTimeoutMixin,
):
    """Goal-driven system that resolves ALL HITL causes autonomously.

    Processing flow:
    1. Fetch and classify HITL items by cause
    2. Fix in parallel (semaphore-limited)
    3. Merge sequentially (one at a time)
    4. Re-rebase remaining items after each merge
    5. Repeat until done or all remaining are stuck
    """

    def __init__(
        self,
        config: HydraFlowConfig,
        state: StateTracker,
        event_bus: EventBus,
        pr_manager: PRPort,
        agents: AgentRunner,
        workspaces: WorkspacePort,
        fetcher: IssueFetcherPort,
        hitl_runner: HITLRunner | None = None,
        stop_event: asyncio.Event | None = None,
        resolver: MergeConflictResolver | None = None,
        troubleshooting_store: TroubleshootingPatternStore | None = None,
        store: IssueStore | None = None,
        credentials: Credentials | None = None,
        gate_block_dedup: DedupStore | None = None,
    ) -> None:
        from config import Credentials as _Credentials  # noqa: PLC0415

        self._config = config
        self._state = state
        self._bus = event_bus
        self._prs = pr_manager
        self._agents = agents
        self._workspaces = workspaces
        self._fetcher = fetcher
        self._hitl_runner = hitl_runner
        self._stop_event = stop_event or asyncio.Event()
        self._resolver = resolver
        self._troubleshooting_store = troubleshooting_store
        self._store = store
        self._credentials = credentials or _Credentials()
        self._suggest_memory = MemorySuggester(
            config,
        )
        # Prompt-gate block escalation (#9734 review finding 3).
        self._gate_block_dedup = gate_block_dedup or DedupStore(
            "prompt_gate_blocked",
            config.data_root / "dedup" / "prompt_gate_blocked.json",
        )

    async def unstick(self, hitl_items: list[HITLItem]) -> UnstickResult:
        """Process HITL items and return stats.

        Returns a dict with keys: ``processed``, ``resolved``, ``failed``,
        ``skipped``, ``merged``.
        """
        from events import EventType, HydraFlowEvent

        stats: UnstickResult = {
            "processed": 0,
            "resolved": 0,
            "failed": 0,
            "skipped": 0,
            "merged": 0,
        }

        if not hitl_items:
            return stats

        # Filter by cause mode
        if self._config.unstick_all_causes:
            candidates = list(hitl_items)
        else:
            candidates = [
                item
                for item in hitl_items
                if self._is_merge_conflict(self._state.get_hitl_cause(item.issue) or "")
            ]

        # Sort by cause priority (merge conflicts first)
        candidates.sort(
            key=lambda item: _CAUSE_PRIORITY.get(
                _classify_cause(self._state.get_hitl_cause(item.issue) or ""),
                99,
            )
        )

        # Apply batch size limit
        batch_size = self._config.pr_unstick_batch_size
        batch = candidates[:batch_size]
        stats["skipped"] = len(hitl_items) - len(batch)

        # --- PARALLEL FIX PHASE ---
        semaphore = asyncio.Semaphore(batch_size)
        fixed: list[HITLItem] = []
        stuck: list[HITLItem] = []

        async def _fix_one(item: HITLItem) -> tuple[HITLItem, bool]:
            async with semaphore:
                if self._stop_event.is_set():
                    return item, False
                return item, await self._process_item(item)

        tasks = [asyncio.create_task(_fix_one(item)) for item in batch]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Dark-factory contract: ``return_exceptions=True`` collects fatal
        # billing/auth signals alongside ordinary unstick failures. A
        # CreditExhaustedError (or AuthenticationError) must NOT be folded
        # into ``stats["failed"]`` — it has to propagate out of ``unstick``
        # so BaseBackgroundLoop._execute_cycle's dedicated handler can pause
        # the loop instead of burning attempt budget against an exhausted
        # signal.
        from subprocess_util import (  # noqa: PLC0415
            AuthenticationError,
            CreditExhaustedError,
        )

        for result in results:
            if isinstance(result, AuthenticationError | CreditExhaustedError):
                raise result

        for result in results:
            stats["processed"] += 1
            if isinstance(result, BaseException):
                stats["failed"] += 1
                continue
            item, success = result
            if success:
                fixed.append(item)
                stats["resolved"] += 1
            else:
                stuck.append(item)
                stats["failed"] += 1

            action = "unstick_resolved" if success else "unstick_failed"
            issue_number = item.issue if not isinstance(result, BaseException) else 0
            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.HITL_UPDATE,
                    data=HITLUpdatePayload(
                        issue=issue_number,
                        action=action,
                        source="pr_unsticker",
                    ),
                )
            )

        # --- SEQUENTIAL MERGE PHASE ---
        if self._config.unstick_auto_merge and fixed:
            merged_count = await self._merge_phase(fixed)
            stats["merged"] = merged_count

        return stats

    async def _process_item(self, item: HITLItem) -> bool:
        """Attempt to resolve issues for a single HITL item.

        Returns *True* if the fix was successful and branch was pushed.
        """
        issue_number = item.issue
        branch = self._config.branch_for_issue(issue_number)
        cause_str = self._state.get_hitl_cause(issue_number) or ""
        cause = await self._effective_cause(_classify_cause(cause_str), item.pr)

        # Claim: swap labels
        claim_kwargs: dict[str, int] = {}
        if item.pr is not None and item.pr > 0:
            claim_kwargs["pr_number"] = item.pr
        await self._prs.swap_pipeline_labels(
            issue_number, self._config.hitl_active_label[0], **claim_kwargs
        )

        cause_desc = cause.value.replace("_", " ")
        await self._prs.post_comment(
            issue_number,
            f"**PR Unsticker** attempting to resolve {cause_desc}...\n\n"
            "---\n*Automated by HydraFlow PR Unsticker*",
        )

        try:
            # Fetch full issue for prompt context
            issue = await self._fetcher.fetch_issue_by_number(issue_number)
            if not issue:
                logger.warning("Could not fetch issue #%d for unsticker", issue_number)
                await self._release_back_to_hitl(
                    issue_number,
                    "Could not fetch issue",
                    pr_number=item.pr,
                )
                return False

            # Get or create worktree
            wt_path = self._config.workspace_path_for_issue(issue_number)
            if not wt_path.is_dir():
                wt_path = await self._workspaces.create(issue_number, branch)
            self._state.set_workspace(issue_number, str(wt_path))

            # Dispatch to cause-specific resolver
            resolution = await self._resolve_by_cause(
                cause,
                issue_number,
                issue,
                wt_path,
                branch,
                item.pr_url,
                pr_number=item.pr,
            )

            if resolution.success:
                # Push the fixed branch
                if resolution.used_rebuild:
                    new_wt = self._config.workspace_path_for_issue(issue_number)
                    await self._prs.push_branch(new_wt, branch, force=True)
                else:
                    await self._prs.push_branch(wt_path, branch)

                if not self._config.unstick_auto_merge:
                    # Restore origin label when not auto-merging
                    origin = self._state.get_hitl_origin(issue_number)
                    # Fall back to HITL label so the issue stays visible
                    issue_target = origin or self._config.hitl_label[0]
                    # Issue goes back to its pre-HITL stage. The PR — if one
                    # exists with commits — belongs at hydraflow-review (PR-
                    # stage label), regardless of where the issue origin sits.
                    # Calling swap_pipeline_labels with the same label for both
                    # produces PR-side drift (PR labeled hydraflow-ready) when
                    # the issue origin is pre-PR.
                    await self._prs.swap_pipeline_labels(issue_number, issue_target)
                    if item.pr is not None and item.pr > 0:
                        await self._prs.swap_pipeline_labels(
                            item.pr, self._config.review_label[0]
                        )

                    self._state.remove_hitl_origin(issue_number)
                    self._state.remove_hitl_cause(issue_number)
                    self._state.reset_issue_attempts(issue_number)

                    await self._prs.post_comment(
                        issue_number,
                        f"**PR Unsticker** resolved {cause_desc} successfully.\n\n"
                        f"Returning issue to `{origin or 'pipeline'}` stage."
                        "\n\n---\n*Automated by HydraFlow PR Unsticker*",
                    )
                # When auto-merge is on, state cleanup happens after merge

                logger.info(
                    "PR Unsticker resolved %s for issue #%d",
                    cause_desc,
                    issue_number,
                )
                return True
            else:
                await self._release_back_to_hitl(
                    issue_number,
                    f"All {cause_desc} resolution attempts exhausted",
                    pr_number=item.pr,
                )
                return False

        except (OSError, RuntimeError, ValueError, asyncio.CancelledError) as exc:
            # Dark-factory contract: CreditExhaustedError is a RuntimeError and
            # would otherwise be swallowed here as a recoverable unstick failure,
            # burning attempt budget against an exhausted billing signal. Reraise
            # credit/auth/likely-bug so the outer loop can pause.
            reraise_on_credit_or_bug(exc)
            logger.exception("PR Unsticker failed for issue #%d", issue_number)
            await self._release_back_to_hitl(
                issue_number,
                "Unexpected error during resolution",
                pr_number=item.pr,
            )
            return False
