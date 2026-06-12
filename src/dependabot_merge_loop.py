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

# Markers in ``wait_for_ci``'s ``summary`` that identify an arch-staleness CI
# failure. ``wait_for_ci`` returns ``"Failed checks: <name>, ..."`` where each
# ``<name>`` is the GitHub check (job) name (see ``PRManager._evaluate_ci_checks``
# / ``get_pr_checks``). The two jobs that run the drift check + architecture
# tests (which include ``test_curated_generated_is_in_sync_with_source``) are
# ``arch-check`` (.github/workflows/arch-regen.yml) and ``Architecture Check``
# (.github/workflows/ci.yml job ``arch``). We also tolerate the deeper marker
# strings in case a caller threads richer failure context into ``summary``.
# Matching is lenient by design: the per-PR refresh cap (config
# ``dependabot_arch_autoheal_max_attempts``) is the real safety net — a false
# positive merely costs at most that many no-op regen pushes before the normal
# ``failure_strategy`` applies.
_ARCH_STALENESS_MARKERS = (
    "arch-check",
    "architecture check",
    "test_curated_generated_is_in_sync_with_source",
    "is stale relative to source",
    "make arch-regen",
)


def _is_arch_staleness_failure(summary: str) -> bool:
    """True when a CI-failure ``summary`` looks like stale-arch-artifact drift.

    Pure + case-insensitive so it is unit-testable in isolation. Returns False
    for an empty summary or a non-arch failure (e.g. ``"Failed checks: lint,
    test"``).
    """
    if not summary:
        return False
    lowered = summary.lower()
    return any(marker in lowered for marker in _ARCH_STALENESS_MARKERS)


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

            # CI truly failed. Before applying the failure strategy, try to
            # self-heal the common stuck-pile case: a bot PR red purely on
            # stale docs/arch/generated/ artifacts (another bot PR advanced the
            # base, so this PR's committed generated files went stale even on
            # files it never touched). Merge the base + regenerate + push so CI
            # re-runs; the next tick re-evaluates. Bounded by
            # ``dependabot_arch_autoheal_max_attempts`` (0 = disabled): if regen
            # does not make it green, the cap is hit and the normal
            # ``failure_strategy`` applies. Detection can be lenient — the cap
            # is the safety net.
            heal_cap = self._config.dependabot_arch_autoheal_max_attempts
            if (
                heal_cap > 0
                and _is_arch_staleness_failure(summary)
                and self._state.get_dependabot_arch_refresh_attempts(pr.pr) < heal_cap
            ):
                refreshed = await self._prs.refresh_pr_branch_with_arch_regen(
                    pr.pr, pr.branch
                )
                if refreshed:
                    self._state.bump_dependabot_arch_refresh_attempts(pr.pr)
                    skipped += 1
                    logger.info(
                        "Bot PR #%d CI failed on stale arch artifacts — "
                        "merged base + regenerated; CI will re-run (attempt %d/%d)",
                        pr.pr,
                        self._state.get_dependabot_arch_refresh_attempts(pr.pr),
                        heal_cap,
                    )
                    continue
                logger.info(
                    "Bot PR #%d arch self-heal did not push — applying "
                    "failure strategy",
                    pr.pr,
                )

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
