"""Background worker loop — auto-merge Dependabot and other configured bot PRs after CI passes."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from comment_formatter import SelfReviewError
from config import AUTO_AGENT_BRANCH_PREFIX, HydraFlowConfig
from dedup_store import DedupStore
from events import EventType, HydraFlowEvent
from merge_policy import (
    ROLE_ORCHESTRATOR_REVIEWER,
    MergeApproval,
    enforce_merge_policy,
    fetch_pr_labels,
)
from models import (
    PRListItem,
    ReviewVerdict,
    SystemAlertPayload,
)

if TYPE_CHECKING:
    from github_cache_loop import GitHubDataCache
    from models import DependabotMergeSettings
    from ports import PRPort
    from state import StateTracker

logger = logging.getLogger("hydraflow.dependabot_merge_loop")

# Auto-Agent (preflight) PRs are opened by the auto-agent subprocess under the
# ambient gh token (the owner account), so they are NOT in ``settings.authors``
# and the review→merge pipeline ignores them (it keys on ``hydraflow-review``
# + ``agent/issue-N``). Without this they never land — they only get rebased
# by MergeStateWatcher — and pile up. ``AUTO_AGENT_BRANCH_PREFIX`` (imported
# from ``config``, shared with the loop that mints it and the GC loop that
# reaps stale ones — #11182) is exact and never used by a human or by the
# normal pipeline (``agent/issue-N``), so matching on it is safe.

# Factory-owned branch prefixes for the UL + pricing maintenance loops. Like the
# auto-agent PRs above, these are opened under the ambient factory token
# (``HydraOps-T-rav`` for the UL loops, ``T-rav`` for pricing) — NOT a configured
# bot author — and they carry workflow labels (``hydraflow-ul-*`` /
# ``pricing-refresh``) rather than ``agent/issue-N``. So author-based selection
# misses them AND the review→merge pipeline ignores them, and they pile up
# unmerged (#9843). Matching on these exact factory-owned prefixes is safe: no
# human or normal-pipeline branch uses them. Once selected, the CI-green merge
# and the stale-arch self-heal path below handle the rest.
# Class 5 (#9889, operator-approved 2026-07-19): human-prefix branches get
# the same CI-green shepherd-to-merge path as factory branches. Before this,
# a human fix/ PR had NO merge path at all — the review→merge pipeline keys
# on agent/issue-N and this loop selected only bots/factory prefixes, so
# every green human PR sat until someone hand-merged it. Guardrails: the
# deploy-time kill-switch below, the existing draft exclusion, the CH-3
# merge policy (which reads fresh PR labels, so policy-override:*/deny
# still apply), and a per-PR ``no-auto-merge`` label opt-out.
#
# The set is the Conventional-Commit type family: every one names a class of
# real, mergeable work that otherwise has NO merge path off a human/agent
# branch (the exact gap the class-5 shepherd exists to close). ``perf/``,
# ``ci/`` and ``build/`` were added after a factory session hand-merged a
# batch of green ``perf/`` CI-speedup PRs one by one — they were green and
# non-conflicting but fell outside the prefix set, so the shepherd ignored
# them. GitHub branch protection (a merge with an unsatisfied required check
# is rejected server-side) plus the ``no-auto-merge`` opt-out remain the
# backstops for the CI-touching prefixes.
_HUMAN_SHEPHERD_BRANCH_PREFIXES = (
    "fix/",
    "feat/",
    "docs/",
    "test/",
    "chore/",
    "refactor/",
    "perf/",
    "ci/",
    "build/",
)
_HUMAN_SHEPHERD_OPT_OUT_LABEL = "no-auto-merge"

_FACTORY_MAINTENANCE_BRANCH_PREFIXES = (
    "ul-proposer/",  # term_proposer_loop
    "ul-evidence/",  # entry_evidence_loop
    "ul-edges/",  # edge_proposer_loop
    "ul-pruner/",  # term_pruner_loop
    "pricing-refresh-auto",  # pricing_refresh_loop (_REGEN_BRANCH)
    "hydraflow/wiki-maint-",  # repo_wiki_loop
)

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


def _normalize_author(login: str) -> str:
    """Normalize a PR-author login for bot matching.

    ``gh pr list --json author`` renders a GitHub App author as ``app/dependabot``
    (the GraphQL form) while the configured / REST form is ``dependabot[bot]``.
    Strip the ``app/`` prefix and the ``[bot]`` suffix so the two compare equal —
    otherwise even real Dependabot PRs never match ``settings.authors`` and the
    loop merges nothing. Pure + case-insensitive for unit-testing in isolation.
    """
    normalized = login.strip().lower()
    if normalized.startswith("app/"):
        normalized = normalized[len("app/") :]
    if normalized.endswith("[bot]"):
        normalized = normalized[: -len("[bot]")]
    return normalized


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
        # #9889 item 2: at most ONE conflict comment per human-shepherd PR,
        # ever — persisted so restarts don't re-comment (the
        # runs_gc_chain_alerts DedupStore precedent).
        self._conflict_comment_dedup = DedupStore(
            "dependabot_conflict_comments",
            config.data_root / "dedup" / "dependabot_conflict_comments.json",
        )

    def _get_default_interval(self) -> int:
        return self._config.dependabot_merge_interval

    def _is_human_shepherd_pr(self, pr: PRListItem) -> bool:
        """Class 5 (#9889): human-prefix branch eligible for shepherding."""
        return (
            self._config.human_branch_shepherd_enabled
            and not pr.is_bot
            and pr.branch.startswith(_HUMAN_SHEPHERD_BRANCH_PREFIXES)
        )

    async def _apply_failure_strategy(
        self, pr: PRListItem, strategy: str, cause: str, detail: str
    ) -> str:
        """Apply the configured ``failure_strategy`` to *pr*.

        Returns the counter the caller should bump: ``"skipped"`` for
        ``skip`` (PR left open, re-polled next cycle) or ``"failed"`` for
        ``hitl``/``close`` (PR escalated/closed and marked processed).
        """
        if strategy == "hitl":
            await self._prs.add_labels(pr.pr, self._config.hitl_label)
            await self._prs.post_comment(
                pr.pr, f"{cause} — escalating to HITL.\n\n{detail}"
            )
            self._state.add_dependabot_merge_processed(pr.pr)
            logger.info("Bot PR #%d: %s — escalated to HITL", pr.pr, cause)
            return "failed"
        if strategy == "close":
            await self._prs.post_comment(
                pr.pr, f"{cause} — closing per configured strategy.\n\n{detail}"
            )
            await self._prs.close_issue(pr.pr)
            self._state.add_dependabot_merge_processed(pr.pr)
            logger.info("Bot PR #%d: %s — closed", pr.pr, cause)
            return "failed"
        # "skip" (the default) and any unknown value: leave open.
        logger.info("Bot PR #%d: %s (strategy=skip) — leaving open", pr.pr, cause)
        return "skipped"

    async def _maybe_heal_merge_conflict(
        self, pr: PRListItem, settings: DependabotMergeSettings
    ) -> str | None:
        """Item 2 (#9889): DIRTY content-conflict auto-heal.

        Called after ``merge_pr`` returned False on a CI-green PR. The
        mergeable-state read (``get_pr_mergeable``) corroborates that the
        failure is a genuine content conflict — ``False`` maps to GitHub's
        CONFLICTING; ``True``/``None`` means transient/unknown, for which the
        caller keeps the legacy log-and-give-up path. Heal by PR class:

        * human shepherd-prefix → the author's to fix: one DedupStore-bounded
          conflict comment, never closed, never update-branched;
        * factory-maintenance prefix → close-supersede: the owning loop
          regenerates a fresh PR (single-flight #9939 prevents pile-up), so
          rebasing generated content is wasted work;
        * dependabot/other bot → one bounded update-branch (the #9884
          fresh-merge-ref lesson, sharing the class-2 attempt counter), then
          the configured ``failure_strategy``.

        Everything is bounded and idempotent: the dedup file caps comments at
        one per PR, close-supersede marks the PR processed, and update-branch
        rides ``dependabot_update_branch_max_attempts``. Returns the caller's
        counter to bump ("skipped"/"failed"), or None when no heal applies.
        """
        if not self._config.dependabot_conflict_heal_enabled:
            return None
        if await self._prs.get_pr_mergeable(pr.pr) is not False:
            return None

        if self._is_human_shepherd_pr(pr):
            dedup_key = str(pr.pr)
            if dedup_key not in self._conflict_comment_dedup.get():
                await self._prs.post_comment(
                    pr.pr,
                    "This PR has a merge conflict with its base branch, so "
                    "auto-merge is on hold. Please resolve the conflict — "
                    "the factory shepherds human-prefix PRs to merge once "
                    "they are conflict-free and CI-green (#9889).",
                )
                self._conflict_comment_dedup.add(dedup_key)
            logger.info("Human PR #%d is conflicting — left to its author", pr.pr)
            return "skipped"

        if pr.branch.startswith(_FACTORY_MAINTENANCE_BRANCH_PREFIXES):
            await self._prs.post_comment(
                pr.pr,
                "Closing: this factory-maintenance PR has a merge conflict "
                "with its base branch. Its generated content is cheap to "
                "rebuild, so the owning loop will regenerate and open a "
                "fresh conflict-free PR on its next cycle (single-flight "
                "#9939 guarantees no pile-up). No action needed (#9889).",
            )
            await self._prs.close_pr(pr.pr)
            self._state.add_dependabot_merge_processed(pr.pr)
            logger.info(
                "Factory-maintenance PR #%d (%s) conflicting — "
                "closed-superseded; owning loop will regenerate",
                pr.pr,
                pr.branch,
            )
            return "failed"

        # Dependabot / configured-bot / auto-agent PRs: one bounded
        # update-branch may clear a conflict against state the base already
        # fixed. Shares the class-2 counter so a PR never exceeds
        # ``dependabot_update_branch_max_attempts`` across both paths.
        ub_cap = self._config.dependabot_update_branch_max_attempts
        if (
            ub_cap > 0
            and self._state.get_dependabot_update_branch_attempts(pr.pr) < ub_cap
            and await self._prs.update_pr_branch(pr.pr, method="merge")
        ):
            self._state.bump_dependabot_update_branch_attempts(pr.pr)
            logger.info(
                "Bot PR #%d conflicting — updated branch for a fresh merge "
                "ref; re-evaluating next cycle (attempt %d/%d)",
                pr.pr,
                self._state.get_dependabot_update_branch_attempts(pr.pr),
                ub_cap,
            )
            return "skipped"
        return await self._apply_failure_strategy(
            pr,
            settings.failure_strategy,
            "Merge conflict on bot PR",
            "The PR is CONFLICTING with its base branch and the bounded "
            "update-branch heal did not clear it (#9889).",
        )

    async def _do_work(self) -> dict[str, Any] | None:
        """Check bot PRs and auto-merge if CI passes."""
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        if not self._config.dependabot_merge_loop_enabled:
            return {"status": "config_disabled"}
        settings = self._state.get_dependabot_merge_settings()
        processed = self._state.get_dependabot_merge_processed()
        bot_authors = {_normalize_author(a) for a in settings.authors}

        # Read the label-agnostic snapshot: bot PRs carry only GitHub-native
        # labels (e.g. ``dependencies``) and are absent from the workflow-label
        # filtered ``get_open_prs`` snapshot, so filtering that by author would
        # always be empty in production (the s09 bug).
        open_prs = self._cache.get_all_open_prs()
        bot_prs = [
            pr
            for pr in open_prs
            if pr.pr not in processed
            and not pr.draft  # never auto-merge a draft, even a bot's
            and (
                # GitHub's own bot flag — catches Dependabot/Renovate/any App
                # generically, the same way the UI tags them, without linking to
                # specific account logins (#9843).
                pr.is_bot
                # Explicit author allowlist (normalized so ``app/dependabot`` and
                # ``dependabot[bot]`` compare equal) — for configured non-App bots.
                or _normalize_author(pr.author) in bot_authors
                # Factory PRs opened under a *user* token (is_bot=False):
                # auto-agent preflight + the UL/pricing/wiki maintenance loops.
                or pr.branch.startswith(AUTO_AGENT_BRANCH_PREFIX)
                or pr.branch.startswith(_FACTORY_MAINTENANCE_BRANCH_PREFIXES)
                # Class 5 (#9889): human-prefix branches, kill-switch gated.
                or self._is_human_shepherd_pr(pr)
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
                # Class 5 opt-out: a fresh label read (not the cache — the
                # author may attach it at any time) so ``no-auto-merge``
                # reliably leaves the PR to its author.
                # Guarded by merge_policy_enabled: the label read is a raw
                # gh subprocess (#9754 — the sandbox air-gaps it by disabling
                # the policy, and this opt-out must not reopen that escape).
                if self._is_human_shepherd_pr(pr) and self._config.merge_policy_enabled:
                    labels = await fetch_pr_labels(self._config, pr.pr)
                    if _HUMAN_SHEPHERD_OPT_OUT_LABEL in labels:
                        skipped += 1
                        logger.info(
                            "Human PR #%d carries %s — leaving it to its author",
                            pr.pr,
                            _HUMAN_SHEPHERD_OPT_OUT_LABEL,
                        )
                        continue
                # CH-3 (#9731): consult the factory-autonomy policy before
                # approving+merging. This lane's approval evidence is its own
                # CI-green auto-approval (the submit_review below); a deny
                # skips both, alerts, and leaves the PR unprocessed so a
                # later approval or policy-override:* label can land it.
                policy_verdict = await enforce_merge_policy(
                    config=self._config,
                    prs=self._prs,
                    pr_number=pr.pr,
                    actor="hydraflow:dependabot_merge_loop",
                    approvals=[
                        MergeApproval(
                            actor="dependabot_merge_loop",
                            role=ROLE_ORCHESTRATOR_REVIEWER,
                            source=(
                                "ci_green_human_shepherd_auto_approval"
                                if self._is_human_shepherd_pr(pr)
                                else "ci_green_bot_pr_auto_approval"
                            ),
                        )
                    ],
                    lane="dependabot_merge_loop",
                )
                if not policy_verdict.allowed:
                    failed += 1
                    logger.warning(
                        "Bot PR #%d merge blocked by policy: %s",
                        pr.pr,
                        policy_verdict.reason,
                    )
                    await self._bus.publish(
                        HydraFlowEvent(
                            type=EventType.SYSTEM_ALERT,
                            data=SystemAlertPayload(
                                message=(
                                    f"Merge policy denied auto-merge of bot PR "
                                    f"#{pr.pr}: {policy_verdict.reason}"
                                ),
                                source="merge_policy",
                            ),
                        )
                    )
                    continue

                # CI green — approve (best-effort) and merge. The bot cannot
                # approve its OWN PR (GitHub blocks self-review), and the base
                # branch requires 0 approving reviews anyway, so a
                # ``SelfReviewError`` must never abort the merge — otherwise
                # every bot caretaker PR (wiki/UL/pricing) piles up unmerged
                # and the loop errors each cycle (#10526). Approving a *human*
                # shepherd's PR is not self-review and still records normally.
                try:
                    await self._prs.submit_review(
                        pr.pr,
                        ReviewVerdict.APPROVE,
                        (
                            "CI passed — auto-merging shepherded human-prefix PR "
                            "(#9889 class 5; add the no-auto-merge label to opt out)."
                            if self._is_human_shepherd_pr(pr)
                            else "CI passed — auto-merging bot PR."
                        ),
                    )
                except SelfReviewError:
                    logger.debug(
                        "Bot PR #%d: cannot self-approve; base requires 0 "
                        "approvals — proceeding to merge (#10526).",
                        pr.pr,
                    )
                merge_ok = await self._prs.merge_pr(pr.pr, auto_rebase=True)
                if merge_ok:
                    merged += 1
                    self._state.add_dependabot_merge_processed(pr.pr)
                    logger.info("Auto-merged bot PR #%d (%s)", pr.pr, pr.title)
                    continue
                # #9889 item 2: the merge failed — when the PR's mergeable
                # state corroborates a genuine content conflict (DIRTY), heal
                # it per PR class instead of log-and-give-up (the arch
                # self-heal below only fires on arch-staleness CI text, never
                # on mergeable-state conflicts, so it can't help here).
                heal_outcome = await self._maybe_heal_merge_conflict(pr, settings)
                if heal_outcome == "skipped":
                    skipped += 1
                elif heal_outcome == "failed":
                    failed += 1
                else:  # not a content conflict — legacy give-up
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

            # Shepherd heal class 2 (#9889): a CI-failed bot PR that is
            # BEHIND its base often fails on state the base already fixed
            # (baseline advances, sibling regens) — and re-running failed
            # jobs pins the OLD merge ref (the #9884 lesson). One bounded
            # update-branch forces a fresh merge ref + full CI re-run.
            # update_pr_branch returns False when already up to date or on
            # API refusal, so this never loops on an actually-broken PR.
            ub_cap = self._config.dependabot_update_branch_max_attempts
            if (
                ub_cap > 0
                and self._state.get_dependabot_update_branch_attempts(pr.pr) < ub_cap
                and await self._prs.update_pr_branch(pr.pr, method="merge")
            ):
                self._state.bump_dependabot_update_branch_attempts(pr.pr)
                skipped += 1
                logger.info(
                    "Bot PR #%d CI failed while behind base — updated branch "
                    "for a fresh merge ref; CI will re-run (attempt %d/%d)",
                    pr.pr,
                    self._state.get_dependabot_update_branch_attempts(pr.pr),
                    ub_cap,
                )
                continue

            # CI truly failed — apply failure strategy
            strategy_outcome = await self._apply_failure_strategy(
                pr, settings.failure_strategy, "CI failed on bot PR", summary
            )
            if strategy_outcome == "skipped":
                skipped += 1
            else:
                failed += 1

        return {"merged": merged, "skipped": skipped, "failed": failed}
