"""The serial merge phase and the two terminal dispositions of an item.

Merging is one-at-a-time by design, so every merge invalidates the rebase
of everything still queued — ``_re_rebase_remaining`` is part of the merge
step, not a separate concern. ``_finalize_resolved`` and
``_release_back_to_hitl`` are the only two ways an item leaves the run.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from approval_records import FACTORY_AUTONOMY_CLAUSE
from merge_policy import ROLE_OPERATOR, MergeApproval, enforce_merge_policy

if TYPE_CHECKING:
    import asyncio

    from config import HydraFlowConfig
    from issue_store import IssueStore
    from models import HITLItem
    from ports import PRPort, WorkspacePort
    from state import StateTracker


logger = logging.getLogger("hydraflow.pr_unsticker")


class PRUnstickerMergeMixin:
    """The serial merge phase and the two terminal dispositions of an item."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``PRUnsticker.__init__`` or by a sibling
    # mixin. The method declarations are TYPE_CHECKING-only on purpose: a
    # runtime ``...`` body is a real class attribute and would win the MRO
    # over the sibling that really implements it (#11629).
    # ------------------------------------------------------------------
    _config: HydraFlowConfig
    _prs: PRPort
    _state: StateTracker
    _stop_event: asyncio.Event
    _store: IssueStore | None
    _workspaces: WorkspacePort

    async def _merge_phase(self, fixed_items: list[HITLItem]) -> int:
        """Merge fixed items one at a time, re-rebasing remaining after each."""
        merged = 0
        remaining = list(fixed_items)

        while remaining:
            if self._stop_event.is_set():
                break

            item = remaining.pop(0)
            success = await self._wait_and_merge(item)

            if success:
                merged += 1
                # Pull main and re-rebase remaining items
                if remaining:
                    await self._prs.pull_main()
                    await self._re_rebase_remaining(remaining)
            # If merge failed, item already released back to HITL

        return merged

    async def _wait_and_merge(self, item: HITLItem) -> bool:
        """Wait for CI to pass, then squash-merge the PR.

        Returns *True* if the merge succeeded.
        """
        issue_number = item.issue
        pr_number = item.pr

        if not pr_number:
            logger.warning("No PR number for issue #%d — skipping merge", issue_number)
            # Still clean up state
            self._finalize_resolved(issue_number)
            return False

        # Wait for CI
        passed, summary = await self._prs.wait_for_ci(
            pr_number,
            self._config.ci_check_timeout,
            self._config.ci_poll_interval,
            self._stop_event,
        )

        if not passed:
            logger.warning(
                "CI failed for PR #%d (issue #%d): %s",
                pr_number,
                issue_number,
                summary,
            )
            await self._release_back_to_hitl(
                issue_number,
                f"CI failed after fix: {summary}",
                pr_number=pr_number,
            )
            return False

        # CH-3 (#9731): consult the factory-autonomy policy before the
        # autonomous merge. This lane's standing approval evidence is the
        # operator-enabled ``unstick_auto_merge`` config grant (we only get
        # here when it is on) — recorded as an operator-role approval with
        # the autonomy clause as its basis. GitHub review approvals are not
        # read here; tightening this lane is a policy.yaml edit.
        policy_verdict = await enforce_merge_policy(
            config=self._config,
            prs=self._prs,
            pr_number=pr_number,
            actor="hydraflow:pr_unsticker",
            approvals=[
                MergeApproval(
                    actor="operator-config:unstick_auto_merge",
                    role=ROLE_OPERATOR,
                    source="standing_config_grant",
                    basis=FACTORY_AUTONOMY_CLAUSE,
                )
            ],
            lane="pr_unsticker",
        )
        if not policy_verdict.allowed:
            await self._release_back_to_hitl(
                issue_number,
                f"Blocked by merge policy: {policy_verdict.reason} "
                "(approve the PR or add a `policy-override:<reason-slug>` "
                "label for an audited break-glass merge)",
                pr_number=pr_number,
            )
            return False

        # Squash merge with rebase-on-conflict recovery (ADR-0042 dark-factory pattern)
        success = await self._prs.merge_pr(pr_number, auto_rebase=True)
        if success:
            self._finalize_resolved(issue_number, merged=True)
            if self._store is not None:
                self._store.mark_merged(issue_number)
            await self._prs.post_comment(
                issue_number,
                "**PR Unsticker** merged PR successfully after fix.\n\n"
                "---\n*Automated by HydraFlow PR Unsticker*",
            )
            logger.info(
                "PR Unsticker merged PR #%d for issue #%d",
                pr_number,
                issue_number,
            )
            return True
        else:
            await self._release_back_to_hitl(
                issue_number,
                f"Merge failed for PR #{pr_number}",
                pr_number=pr_number,
            )
            return False

    async def _re_rebase_remaining(self, remaining: list[HITLItem]) -> None:
        """Rebase remaining fixed items on updated main after a merge.

        When a merge introduces conflicts, the merge is aborted and the
        item is flagged so the next unstick cycle can resolve it properly
        rather than silently losing the failure.
        """
        for item in remaining:
            issue_number = item.issue
            branch = self._config.branch_for_issue(issue_number)
            wt_path = self._config.workspace_path_for_issue(issue_number)

            if not wt_path.is_dir():
                continue

            try:
                clean = await self._workspaces.start_merge_main(wt_path, branch)
                if not clean:
                    await self._workspaces.abort_merge(wt_path)
                    logger.warning(
                        "Re-rebase for issue #%d hit conflicts after sibling "
                        "merge — will resolve on next unstick cycle",
                        issue_number,
                    )
                    self._state.set_hitl_cause(
                        issue_number,
                        "Cascade conflict: merge main after sibling PR merged",
                    )
            except (RuntimeError, OSError):
                logger.warning(
                    "Re-rebase failed for issue #%d after merge",
                    issue_number,
                    exc_info=True,
                )

    def _finalize_resolved(self, issue_number: int, *, merged: bool = False) -> None:
        """Clean up HITL state after successful resolution."""
        self._state.remove_hitl_origin(issue_number)
        self._state.remove_hitl_cause(issue_number)
        self._state.reset_issue_attempts(issue_number)
        if merged:
            self._state.record_pr_merged()

    async def _release_back_to_hitl(
        self, issue_number: int, reason: str, *, pr_number: int | None = None
    ) -> None:
        """Remove active label and re-add HITL label."""
        release_kwargs: dict[str, int] = {}
        if pr_number is not None and pr_number > 0:
            release_kwargs["pr_number"] = pr_number
        await self._prs.swap_pipeline_labels(
            issue_number,
            self._config.hitl_label[0],
            **release_kwargs,
        )
        await self._prs.post_comment(
            issue_number,
            f"**PR Unsticker** could not resolve: {reason}\n\n"
            "Returning to HITL for manual intervention."
            "\n\n---\n*Automated by HydraFlow PR Unsticker*",
        )
