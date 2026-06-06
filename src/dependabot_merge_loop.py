"""Background worker loop — auto-merge Dependabot and other configured bot PRs after CI passes."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from models import ReviewVerdict

if TYPE_CHECKING:
    from github_cache_loop import GitHubDataCache
    from ports import PRPort
    from state import StateTracker

logger = logging.getLogger("hydraflow.dependabot_merge_loop")

# Factory-owned branch prefix for Auto-Agent (preflight) PRs. These are opened
# by the auto-agent subprocess under the ambient gh token (the owner account),
# so they are NOT in ``settings.authors`` and the review→merge pipeline ignores
# them (it keys on ``hydraflow-review`` + ``agent/issue-N``). Without this they
# never land — they only get rebased by MergeStateWatcher — and pile up. The
# prefix is exact and never used by a human or by the normal pipeline
# (``agent/issue-N``), so matching on it is safe.
_AUTO_AGENT_BRANCH_PREFIX = "agent/auto-agent-"


class DependabotMergeLoop(BaseBackgroundLoop):
    """Polls open PRs and auto-merges configured bot PRs + Auto-Agent PRs after CI passes."""

    def __init__(
        self,
        config: HydraFlowConfig,
        cache: GitHubDataCache,
        prs: PRPort,
        state: StateTracker,
        deps: LoopDeps,
    ) -> None:
        super().__init__(worker_name="dependabot_merge", config=config, deps=deps)
        self._cache = cache
        self._prs = prs
        self._state = state

    def _get_default_interval(self) -> int:
        return self._config.dependabot_merge_interval

    async def _do_work(self) -> dict[str, Any] | None:
        """Check bot PRs and auto-merge if CI passes."""
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        if not self._config.dependabot_merge_loop_enabled:
            return {"status": "config_disabled"}
        settings = self._state.get_dependabot_merge_settings()
        processed = self._state.get_dependabot_merge_processed()
        bot_authors = {a.lower() for a in settings.authors}

        # Read the label-agnostic snapshot: bot PRs carry only GitHub-native
        # labels (e.g. ``dependencies``) and are absent from the workflow-label
        # filtered ``get_open_prs`` snapshot, so filtering that by author would
        # always be empty in production (the s09 bug).
        open_prs = self._cache.get_all_open_prs()
        bot_prs = [
            pr
            for pr in open_prs
            if pr.pr not in processed
            and (
                pr.author.lower() in bot_authors
                or pr.branch.startswith(_AUTO_AGENT_BRANCH_PREFIX)
            )
        ]

        merged = 0
        skipped = 0
        failed = 0

        for pr in bot_prs:
            passed, summary = await self._prs.wait_for_ci(
                pr.pr,
                timeout=60,
                poll_interval=15,
                stop_event=self._stop_event,
            )

            if self._stop_event.is_set():
                break

            if passed:
                # CI green — approve and merge
                await self._prs.submit_review(
                    pr.pr, ReviewVerdict.APPROVE, "CI passed — auto-merging bot PR."
                )
                merge_ok = await self._prs.merge_pr(pr.pr, auto_rebase=True)
                if merge_ok:
                    merged += 1
                    self._state.add_dependabot_merge_processed(pr.pr)
                    logger.info("Auto-merged bot PR #%d (%s)", pr.pr, pr.title)
                else:
                    failed += 1
                    logger.warning("Failed to merge bot PR #%d", pr.pr)
                continue

            # CI not passed — check if still pending or truly failed
            if "timed out" in summary.lower():
                # CI still pending — skip for now, retry next cycle
                skipped += 1
                logger.debug(
                    "Bot PR #%d CI still pending — will retry next cycle", pr.pr
                )
                continue

            # CI truly failed — apply failure strategy
            strategy = settings.failure_strategy
            if strategy == "skip":
                skipped += 1
                logger.info(
                    "Bot PR #%d CI failed (strategy=skip) — leaving open", pr.pr
                )
            elif strategy == "hitl":
                await self._prs.add_labels(pr.pr, self._config.hitl_label)
                await self._prs.post_comment(
                    pr.pr,
                    f"CI failed on bot PR — escalating to HITL.\n\n{summary}",
                )
                self._state.add_dependabot_merge_processed(pr.pr)
                failed += 1
                logger.info("Bot PR #%d CI failed — escalated to HITL", pr.pr)
            elif strategy == "close":
                await self._prs.post_comment(
                    pr.pr,
                    f"CI failed on bot PR — closing per configured strategy.\n\n{summary}",
                )
                await self._prs.close_issue(pr.pr)
                self._state.add_dependabot_merge_processed(pr.pr)
                failed += 1
                logger.info("Bot PR #%d CI failed — closed", pr.pr)

        return {"merged": merged, "skipped": skipped, "failed": failed}
