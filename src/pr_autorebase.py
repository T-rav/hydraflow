"""Auto-rebase actuator for the factory's own dirty PRs (#11595 option 3).

At the 20-merged-PRs/day cadence every squash to ``staging`` re-touches the
committed ``docs/arch/generated/`` artifacts, which marks every OTHER open
PR ``mergeable_state=dirty`` (CONFLICTING) — and GitHub dispatches no CI on
a dirty PR, so without an actuator the line stalls on by-hand rebases (the
operator ran that loop five times on 2026-08-21 alone).

This actuator rides :class:`merge_state_watcher.MergeStateWatcher`
(ADR-0075) rather than adding a new loop: after the watcher's cheap
``gh pr update-branch`` fails (it always does for a genuinely CONFLICTING
PR) and before the HITL escalation, the actuator re-runs the exact loop the
operator performs by hand via the existing
:func:`auto_pr.refresh_branch_with_arch_regen` engine — ephemeral worktree,
``git merge origin/<staging>`` (a merge commit, NOT a literal rebase: the
pre-push hook blocks force-pushes, squash-merge collapses the merge commit,
and a plain fast-forward push is strictly safer than ``--force-with-lease``
— the same house convention as the DependabotMergeLoop arch heal, #9475),
deterministic arch-regen when only generated artifacts conflict, commit,
plain push. The push re-dispatches CI without an operator.

Safety rails:

- **Default OFF.** ``pr_autorebase_enabled`` / ``HYDRAFLOW_PR_AUTOREBASE_
  ENABLED`` ships False; the operator arms it deliberately (it rewrites
  PR branches, even though it never force-pushes).
- **Factory-owned PRs only.** Head branches under the ``agent/`` namespace
  (``config.branch_for_issue`` → ``agent/issue-N``; Auto-Agent preflight →
  ``agent/auto-agent-N``). Operator/human branches are never touched;
  ``ul-*`` factory-maintenance PRs stay with DependabotMergeLoop's
  close-supersede heal (#9889).
- **One attempt per (pr, staging head).** The dedup key ``{pr}@{sha}`` is
  persisted to disk BEFORE the attempt runs, so a crash mid-rebase cannot
  loop against the same staging head.
- **Source conflicts are never half-resolved.** A non-generated-file
  conflict aborts the merge inside the engine, leaves the PR untouched,
  and surfaces exactly one PR comment; the watcher then escalates to HITL
  as before.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

# Module-object imports (not ``from``-imports) so tests can monkeypatch
# ``subprocess_util.run_subprocess`` / the auto_pr engine at the module
# boundary — the same seam the arch-heal regression tests use.
import auto_pr
import subprocess_util
from config import Credentials
from dedup_store import DedupStore
from exception_classify import reraise_on_credit_or_bug

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from auto_pr import ArchRefreshResult
    from config import HydraFlowConfig
    from merge_state_watcher import ConflictingPR
    from ports import PRPort

logger = logging.getLogger("hydraflow.pr_autorebase")

# The factory's own head-branch namespace. Deliberately narrow: manual
# dispatch mints ``agent/issue-N`` and Auto-Agent preflight mints
# ``agent/auto-agent-N`` (see ``config.AUTO_AGENT_BRANCH_PREFIX``).
# Operator branches (``feat/*``, ``fix/*``), RC promotion (``rc/*``), and
# factory-maintenance regen PRs (``ul-*`` — close-superseded by
# DependabotMergeLoop, #9889) are all excluded on purpose.
FACTORY_BRANCH_PREFIXES: tuple[str, ...] = ("agent/",)

DecisionAction = Literal[
    "attempt",
    "skipped_disabled",
    "skipped_not_factory",
    "skipped_no_staging_sha",
    "skipped_already_attempted",
]

AutoRebaseOutcome = Literal[
    "autorebased",
    "real_conflict",
    "failed",
    "no_op",
    "skipped_disabled",
    "skipped_not_factory",
    "skipped_no_staging_sha",
    "skipped_already_attempted",
    "skipped_dry_run",
]


def is_factory_branch(branch: str) -> bool:
    """True when *branch* lives in the factory's own head-branch namespace."""
    return branch.startswith(FACTORY_BRANCH_PREFIXES)


@dataclass(frozen=True)
class AutoRebaseDecision:
    """Outcome of the pure gate: attempt the rebase, or why not."""

    action: DecisionAction
    dedup_key: str = ""


def decide_autorebase(
    *,
    enabled: bool,
    branch: str,
    pr_number: int,
    staging_sha: str,
    attempted: set[str],
) -> AutoRebaseDecision:
    """Pure decision core: dirty + own-PR + not-yet-tried-at-this-head → attempt.

    The caller established "dirty" (the PR came from
    ``list_conflicting_prs`` and the cheap update-branch failed); this gate
    layers the actuator's own rails: kill-switch, factory-owned head branch,
    a known staging head to key the attempt on, and the one-attempt-per-
    (pr, staging head) dedup.
    """
    if not enabled:
        return AutoRebaseDecision(action="skipped_disabled")
    if not is_factory_branch(branch):
        return AutoRebaseDecision(action="skipped_not_factory")
    if not staging_sha:
        return AutoRebaseDecision(action="skipped_no_staging_sha")
    key = f"{pr_number}@{staging_sha}"
    if key in attempted:
        return AutoRebaseDecision(action="skipped_already_attempted", dedup_key=key)
    return AutoRebaseDecision(action="attempt", dedup_key=key)


class PRAutoRebase:
    """Executor around :func:`decide_autorebase` — one bounded heal per PR.

    Wired into ``MergeStateWatcher``; every non-``autorebased`` outcome
    falls through to the watcher's existing HITL escalation, so the
    actuator can only ever *reduce* operator toil, never hide a stuck PR.
    """

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        prs: PRPort,
        refresh_fn: Callable[..., Awaitable[ArchRefreshResult]] | None = None,
        dedup: DedupStore | None = None,
        credentials: Credentials | None = None,
    ) -> None:
        self._config = config
        self._prs = prs
        self._refresh_fn = refresh_fn
        self._credentials = credentials or Credentials()
        self._dedup = dedup or DedupStore(
            "pr_autorebase_attempts",
            config.data_root / "dedup" / "pr_autorebase_attempts.json",
        )

    async def try_autorebase(self, pr: ConflictingPR) -> AutoRebaseOutcome:
        """One bounded merge+regen+push attempt for a CONFLICTING factory PR.

        Returns the outcome key; only ``"autorebased"`` means a new head was
        pushed (CI re-dispatches). Everything else leaves the PR for the
        caller's escalation path.
        """
        precheck = self._precheck(pr)
        if precheck is not None:
            return precheck

        staging_sha = await self._staging_head_sha()
        decision = decide_autorebase(
            enabled=True,
            branch=pr.branch,
            pr_number=pr.number,
            staging_sha=staging_sha,
            attempted=self._dedup.get(),
        )
        if decision.action != "attempt":
            logger.info(
                "pr_autorebase: PR #%d (%s) not attempted: %s",
                pr.number,
                pr.branch,
                decision.action,
            )
            return decision.action

        if self._config.dry_run:
            logger.info(
                "[dry-run] Would auto-rebase PR #%d (%s) onto %s@%s",
                pr.number,
                pr.branch,
                self._config.base_branch(),
                staging_sha[:12],
            )
            return "skipped_dry_run"

        # Persist the attempt BEFORE running it: a crash mid-rebase must not
        # re-attempt at the same staging head on restart.
        self._record_attempt(decision.dedup_key, staging_sha)

        try:
            result = await self._refresh(branch=pr.branch)
        except (OSError, RuntimeError, TimeoutError) as exc:
            # CreditExhaustedError subclasses RuntimeError — reraise it (plus
            # auth/likely-bug) so the owning loop pauses instead of burning
            # the escalation path against an exhausted billing signal.
            reraise_on_credit_or_bug(exc)
            logger.warning(
                "pr_autorebase: refresh engine raised for PR #%d (%s)",
                pr.number,
                pr.branch,
                exc_info=True,
            )
            return "failed"

        return await self._apply_result(pr, result, staging_sha)

    def _precheck(self, pr: ConflictingPR) -> AutoRebaseOutcome | None:
        """Cheap gates before any network I/O: kill-switch, factory namespace."""
        if not self._config.pr_autorebase_enabled:
            return "skipped_disabled"
        if not is_factory_branch(pr.branch):
            return "skipped_not_factory"
        return None

    async def _apply_result(
        self, pr: ConflictingPR, result: ArchRefreshResult, staging_sha: str
    ) -> AutoRebaseOutcome:
        """Map the engine's :class:`ArchRefreshResult` onto an outcome key."""
        if result.status == "refreshed":
            logger.info(
                "pr_autorebase: PR #%d (%s) merged %s@%s + regenerated + "
                "pushed — CI re-dispatches",
                pr.number,
                pr.branch,
                self._config.base_branch(),
                staging_sha[:12],
            )
            return "autorebased"
        if result.status == "real-conflict":
            await self._surface_real_conflict(pr, error=result.error or "")
            return "real_conflict"
        if result.status == "no-diff":
            # Clean merge with nothing to push — the branch already contains
            # the base, so GitHub's mergeable recompute should clear the PR
            # on its own. Fall through to escalation for honesty: nothing
            # was pushed, so no CI re-dispatch happened.
            logger.info(
                "pr_autorebase: PR #%d (%s) had nothing to push (no-diff)",
                pr.number,
                pr.branch,
            )
            return "no_op"
        logger.warning(
            "pr_autorebase: PR #%d (%s) refresh failed: %s",
            pr.number,
            pr.branch,
            result.error or result.status,
        )
        return "failed"

    async def _refresh(self, *, branch: str) -> ArchRefreshResult:
        """Run the shared merge+regen+push engine for *branch*.

        Defaults to :func:`auto_pr.refresh_branch_with_arch_regen` — the
        same ephemeral-worktree engine behind the DependabotMergeLoop arch
        heal (never the primary checkout, never a force-push). Tests inject
        ``refresh_fn`` to run it against a tiny real repo or a stub.
        """
        fn = self._refresh_fn
        if fn is None:
            fn = auto_pr.refresh_branch_with_arch_regen
        return await fn(
            repo_root=self._config.repo_root,
            branch=branch,
            base=self._config.base_branch(),
            gh_token=self._credentials.gh_token,
            worktree_parent=self._config.workspace_base,
            commit_author_name=self._config.git_user_name,
            commit_author_email=self._config.git_user_email,
        )

    async def _staging_head_sha(self) -> str:
        """Current remote head SHA of the base branch — the dedup key half.

        A single read-only ``git ls-remote`` against origin; returns ``""``
        on any failure, which the decision maps to ``skipped_no_staging_sha``
        (fail-closed: no attempt we cannot key and bound).
        """
        base = self._config.base_branch()
        try:
            out = await subprocess_util.run_subprocess(
                "git",
                "ls-remote",
                "origin",
                f"refs/heads/{base}",
                cwd=self._config.repo_root,
                gh_token=self._credentials.gh_token,
                timeout=30.0,
            )
        except (OSError, RuntimeError, TimeoutError) as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning("pr_autorebase: ls-remote origin %s failed: %s", base, exc)
            return ""
        parts = out.split()
        return parts[0] if parts else ""

    def _record_attempt(self, key: str, staging_sha: str) -> None:
        """Persist *key*, pruning keys for superseded staging heads.

        A superseded head's key can never be consulted again (the decision
        keys on the CURRENT head), so pruning keeps the dedup file bounded
        at one head's worth of PRs without weakening the guarantee.
        """
        suffix = f"@{staging_sha}"
        current = {k for k in self._dedup.get() if k.endswith(suffix)}
        current.add(key)
        self._dedup.set_all(current)

    async def _surface_real_conflict(self, pr: ConflictingPR, *, error: str) -> None:
        """One PR comment for a source-file conflict the actuator refused.

        Runs at most once per (pr, staging head) — it sits inside the deduped
        attempt — and the caller's HITL escalation then labels the PR, which
        the watcher skips on later ticks.
        """
        detail = f"\n\n```\n{error}\n```" if error else ""
        body = (
            "**PR AutoRebase** (#11595): the base branch advanced under this "
            "PR, but bringing the branch up to date hit a merge conflict in "
            "non-generated files, which this actuator never half-resolves."
            f"{detail}\n\n"
            "The merge was aborted and the branch was left untouched — a "
            "source conflict needs a real resolution, so this PR is being "
            "escalated to HITL.\n\n"
            "---\n*Automated by HydraFlow MergeStateWatcher*"
        )
        try:
            await self._prs.post_comment(pr.number, body)
        except (OSError, RuntimeError, TimeoutError) as exc:
            reraise_on_credit_or_bug(exc)
            # Handled surface failure: the HITL escalation still lands, so
            # the PR is not silently stuck — log at warning per house rule.
            logger.warning(
                "pr_autorebase: could not post conflict comment on PR #%d: %s",
                pr.number,
                exc,
            )
