"""Background worker loop — garbage-collect stale worktrees and branches."""

from __future__ import annotations

import contextlib
import logging
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import AUTO_AGENT_BRANCH_PREFIX, Credentials, HydraFlowConfig
from exception_classify import reraise_on_credit_or_bug
from issue_state import issue_state_is_resolved
from state import StateTracker
from subprocess_util import run_subprocess

if TYPE_CHECKING:
    from ports import PRPort, WorkspacePort

logger = logging.getLogger("hydraflow.workspace_gc_loop")

# Maximum worktrees to GC per cycle to avoid long-running passes.
_MAX_GC_PER_CYCLE = 20
_GIT_OID_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


class _WorktreeEntry(NamedTuple):
    """A single worktree parsed from ``git worktree list --porcelain``."""

    path: Path
    branch: str | None  # short name (``refs/heads/`` stripped); None if detached


class _ActiveWorkspaceSnapshot(NamedTuple):
    """Lossless, path-aware active-workspace state for one GC cycle."""

    workspaces: dict[int, str]
    path_owners: dict[Path, set[int]]


def _path_within(path: Path, root: Path) -> bool:
    """True when *path* is *root* itself or nested under it."""
    try:
        return path == root or path.is_relative_to(root)
    except (OSError, ValueError):  # pragma: no cover - defensive
        return False


class WorkspaceGCLoop(BaseBackgroundLoop):
    """Periodically garbage-collects stale worktrees and orphaned branches.

    Catches worktrees that leak when PRs are merged manually, via HITL,
    or when implementations fail/crash.
    """

    def __init__(
        self,
        config: HydraFlowConfig,
        workspaces: WorkspacePort,
        prs: PRPort,
        state: StateTracker,
        deps: LoopDeps,
        is_in_pipeline_cb: Callable[[int], bool] | None = None,
        credentials: Credentials | None = None,
    ) -> None:
        super().__init__(worker_name="workspace_gc", config=config, deps=deps)
        self._credentials = credentials or Credentials()
        self._workspaces = workspaces
        self._prs = prs
        self._state = state
        self._is_in_pipeline = is_in_pipeline_cb

    def _get_default_interval(self) -> int:
        return self._config.workspace_gc_interval

    async def _do_work(self) -> dict[str, Any] | None:
        """Run one GC cycle: state workspaces, orphan dirs, orphan branches."""
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        if not self._config.workspace_gc_loop_enabled:
            return {"status": "config_disabled"}
        collected = 0
        skipped = 0
        errors = 0

        # Phase 1: GC workspaces tracked in state
        active_snapshot = self._active_workspace_snapshot()
        if active_snapshot is None:
            logger.warning(
                "GC: active workspace state identity is malformed or ambiguous — skipping cycle"
            )
            return {"collected": 0, "skipped": 0, "errors": 1}
        active_workspaces = active_snapshot.workspaces
        active_branches = self._state.get_active_branches()
        for issue_number in list(active_workspaces.keys()):
            if self._stop_event.is_set() or collected >= _MAX_GC_PER_CYCLE:
                break
            try:
                if await self._is_safe_to_gc(issue_number):
                    destroy_path = self._config.workspace_path_for_issue(issue_number)
                    recorded_path = Path(active_workspaces[issue_number])
                    if not self._tracked_path_matches_destroy_target(
                        recorded_path, destroy_path
                    ):
                        skipped += 1
                        logger.warning(
                            "GC: tracked path %s for issue #%d does not match destroy target %s — skipping",
                            recorded_path,
                            issue_number,
                            destroy_path,
                        )
                        continue
                    if not await self._worktree_work_has_landed(
                        destroy_path,
                        expected_branch=active_branches.get(issue_number),
                        expected_issue=issue_number,
                    ):
                        skipped += 1
                        logger.debug(
                            "GC: tracked worktree %s for issue #%d has unlanded work — skipping",
                            destroy_path,
                            issue_number,
                        )
                        continue
                    # Remove from state first so a crash between steps
                    # leaves the entry gone (destroy is idempotent).
                    self._state.remove_workspace(issue_number)
                    self._state.remove_branch(issue_number)
                    await self._workspaces.destroy(issue_number)
                    collected += 1
                    logger.info("GC: collected workspace for issue #%d", issue_number)
                else:
                    skipped += 1
            except Exception as exc:  # noqa: BLE001
                reraise_on_credit_or_bug(exc)
                logger.warning(
                    "GC: failed to collect workspace for issue #%d",
                    issue_number,
                    exc_info=True,
                )
                errors += 1

        # Phase 2: scan filesystem for orphaned issue-* dirs not in state
        if not self._stop_event.is_set():
            orphan_count = await self._collect_orphaned_dirs(
                active_workspaces,
                _MAX_GC_PER_CYCLE - collected,
                active_path_owners=active_snapshot.path_owners,
            )
            collected += orphan_count

        # Phase 3: delete orphaned local branches across every issue-branch
        # namespace (agent/issue-*, agent/auto-agent-*, fix|feat|.../*-N)
        if not self._stop_event.is_set():
            branch_count = await self._collect_orphaned_branches(
                _MAX_GC_PER_CYCLE - collected
            )
            collected += branch_count

        # Phase 4: prune stale active_branches entries with no worktree
        if not self._stop_event.is_set():
            pruned = await self._prune_stale_branch_entries(
                _MAX_GC_PER_CYCLE - collected
            )
            collected += pruned

        # Phase 5: enumerate git worktrees on ALL roots + branch namespaces
        # (#10698). Authoritative discovery via `git worktree list`, not a
        # single-directory `issue-*` prefix scan — catches sub-agent, manual,
        # genpr, and factory-operational worktrees that leaked forever.
        if not self._stop_event.is_set() and self._config.worktree_gc_all_roots_enabled:
            reaped = await self._collect_orphaned_worktrees(
                _MAX_GC_PER_CYCLE - collected,
                active_snapshot=active_snapshot,
            )
            collected += reaped

        return {"collected": collected, "skipped": skipped, "errors": errors}

    async def _is_safe_to_gc(self, issue_number: int) -> bool:
        """Determine whether a worktree for *issue_number* can be safely GC'd.

        Returns False (skip) on any uncertainty.
        """
        safe_to_gc = False

        # Skip if active, HITL, or anywhere in the IssueStore pipeline
        # (queued, in-flight, or being processed).
        in_pipeline = self._is_in_pipeline and self._is_in_pipeline(issue_number)
        if (
            issue_number in self._state.get_active_issue_numbers()
            or self._state.get_hitl_cause(issue_number) is not None
            or in_pipeline
        ):
            logger.debug("GC: #%d is active/HITL/pipeline — skipping", issue_number)
            return safe_to_gc

        # Skip issues that still have retries remaining.  Between the moment
        # an attempt is bumped (before each run) and the moment it succeeds or
        # closes (which clears the counter), the issue is temporarily not in
        # any active set.  Without this guard the GC can destroy the worktree
        # in that window, causing the in-flight session to lose its unpushed
        # commits (implementation retry #6413; auto-agent session #10459).
        if self._in_retry_window(issue_number):
            logger.debug(
                "GC: #%d has an in-flight retry window — skipping", issue_number
            )
            return safe_to_gc

        # Check issue state via GitHub API
        try:
            issue_state = await self._get_issue_state(issue_number)
        except Exception as exc:  # noqa: BLE001
            reraise_on_credit_or_bug(exc)
            logger.debug(
                "GC: could not fetch issue #%d state — skipping",
                issue_number,
                exc_info=True,
            )
            return safe_to_gc

        if issue_state == "closed":
            safe_to_gc = True
        elif issue_state == "open":
            # Guard against startup/refresh races where IssueStore has not yet
            # observed pipeline membership. If GitHub labels indicate pipeline
            # ownership, do not GC.
            if await self._issue_has_pipeline_label(issue_number):
                logger.debug(
                    "GC: #%d still has pipeline labels on GitHub — skipping",
                    issue_number,
                )
            else:
                try:
                    safe_to_gc = not await self._has_open_pr(issue_number)
                except Exception as exc:  # noqa: BLE001
                    reraise_on_credit_or_bug(exc)
                    logger.debug(
                        "GC: could not check PR for issue #%d — skipping",
                        issue_number,
                        exc_info=True,
                    )

        return safe_to_gc

    def _in_retry_window(self, issue_number: int) -> bool:
        """True while any in-flight attempt may still be committing to the worktree.

        Two independent attempt counters can each hold an in-flight session:
        the *implementation* counter (``get_issue_attempts``) and the
        *auto_agent* convergence-ledger counter (``get_auto_agent_attempts``).
        Both are bumped *before* a run and cleared on success/close, so between
        those two moments the issue is absent from every active set even though
        a live session owns the worktree. GC must skip while either counter is
        in-window (``0 < attempts < max``); consulting only the implementation
        counter let the GC sweep an actively-running auto-agent worktree and
        lose its unpushed commits (#10459, the #10403 race).
        """
        impl_attempts = self._state.get_issue_attempts(issue_number)
        if 0 < impl_attempts < self._config.max_issue_attempts:
            return True
        aa_attempts = self._state.get_auto_agent_attempts(issue_number)
        return 0 < aa_attempts < self._config.auto_agent_max_attempts

    async def _issue_has_pipeline_label(self, issue_number: int) -> bool:
        pipeline_labels = {
            *(lbl.lower() for lbl in self._config.find_label),
            *(lbl.lower() for lbl in self._config.planner_label),
            *(lbl.lower() for lbl in self._config.ready_label),
            *(lbl.lower() for lbl in self._config.review_label),
            *(lbl.lower() for lbl in self._config.hitl_label),
            *(lbl.lower() for lbl in self._config.hitl_active_label),
        }
        if not pipeline_labels:
            return False
        # Route through PRPort so the air-gapped sandbox FakeGitHub can serve
        # the read; raw ``gh`` would escape the air-gap and fail-close every
        # cycle, making the open-issue GC path unreachable in scenarios (#9575).
        try:
            label_names = await self._prs.get_issue_labels(issue_number)
        except Exception as exc:  # noqa: BLE001
            reraise_on_credit_or_bug(exc)
            logger.debug(
                "GC: could not fetch labels for issue #%d — skipping GC",
                issue_number,
                exc_info=True,
            )
            return True
        labels = {name.strip().lower() for name in label_names if name.strip()}
        return bool(labels & pipeline_labels)

    async def _get_issue_state(self, issue_number: int) -> str:
        """Query the issue state ('open' / 'closed' / 'unknown') via PRPort.

        Routed through ``PRPort.get_issue_state`` so the air-gapped sandbox
        FakeGitHub can serve the read — the raw ``gh api`` call this replaces
        failed on every cycle there, fail-closing every GC decision to "skip"
        and making the closed-issue collect path unreachable in scenarios
        (#9543; same class as the #9575 open-issue-path port routing).

        The port speaks GitHub's GraphQL-style vocabulary
        (``COMPLETED``/``NOT_PLANNED``/``OPEN``/``UNKNOWN``/``""``); map it to
        the REST-style strings ``_is_safe_to_gc`` compares against. Anything
        unrecognized maps to ``"unknown"``, preserving the fail-closed-on-
        uncertainty contract (an unknown state is never collected).
        """
        port_state = await self._prs.get_issue_state(issue_number)
        if issue_state_is_resolved(port_state):
            return "closed"
        if port_state == "OPEN":
            return "open"
        return "unknown"

    async def _has_open_pr(self, issue_number: int) -> bool:
        """Check whether an open PR exists for the issue's branch (via PRPort).

        Routed through ``PRPort.find_open_pr_for_branch`` so the sandbox
        FakeGitHub can serve the read instead of a raw ``gh`` subprocess that
        escapes the air-gap (#9575). FakeGitHub signals "no open PR" with a
        ``PRInfo(number=0)`` sentinel, so ``number > 0`` is the real check.
        """
        branch = self._config.branch_for_issue(issue_number)
        try:
            pr = await self._prs.find_open_pr_for_branch(
                branch, issue_number=issue_number
            )
        except Exception as exc:  # noqa: BLE001
            reraise_on_credit_or_bug(exc)
            logger.debug(
                "GC: PR check failed for issue #%d",
                issue_number,
                exc_info=True,
            )
            return True  # Assume PR exists on error — don't GC
        return pr is not None and pr.number > 0

    async def _collect_orphaned_dirs(
        self,
        tracked: dict[int, str],
        budget: int,
        *,
        active_path_owners: dict[Path, set[int]] | None = None,
    ) -> int:
        """Scan filesystem for orphaned issue-* dirs not tracked in state."""
        if active_path_owners is None:
            active_path_owners = self._canonical_active_path_owners(tracked)
            if active_path_owners is None:
                logger.warning(
                    "GC: active workspace path identity is ambiguous — skipping orphan scan"
                )
                return 0
        collected = 0
        repo_wt_base = self._config.workspace_base / self._config.repo_slug
        if not repo_wt_base.exists():
            return 0

        try:
            entries = sorted(repo_wt_base.iterdir())
        except OSError:
            # Network mount unavailable, permission denied — skip this phase
            # so subsequent GC phases still run (issue #6413).
            logger.warning(
                "GC: iterdir failed on %s — skipping orphan scan",
                repo_wt_base,
                exc_info=True,
            )
            return 0

        tracked_issues = set(tracked.keys())
        for child in entries:
            if collected >= budget or self._stop_event.is_set():
                break
            if not child.is_dir() or not child.name.startswith("issue-"):
                continue
            try:
                canonical_child = child.expanduser().resolve()
            except (OSError, RuntimeError):
                logger.debug(
                    "GC: could not resolve orphan candidate %s — skipping", child
                )
                continue
            if canonical_child in active_path_owners:
                logger.debug(
                    "GC: orphan candidate %s is state-owned by issue(s) %s — skipping",
                    child,
                    sorted(active_path_owners[canonical_child]),
                )
                continue
            try:
                issue_number = int(child.name.split("-", 1)[1])
            except (ValueError, IndexError):
                continue
            if issue_number in tracked_issues:
                continue
            try:
                if await self._is_safe_to_gc(issue_number):
                    if not await self._worktree_work_has_landed(
                        child,
                        expected_branch=None,
                        expected_issue=issue_number,
                    ):
                        logger.debug(
                            "GC: orphaned worktree %s for issue #%d has unlanded work — skipping",
                            child,
                            issue_number,
                        )
                        continue
                    await self._workspaces.destroy(issue_number)
                    collected += 1
                    logger.info(
                        "GC: collected orphaned worktree dir for issue #%d",
                        issue_number,
                    )
            except Exception as exc:  # noqa: BLE001
                reraise_on_credit_or_bug(exc)
                logger.warning(
                    "GC: failed to collect orphaned dir for issue #%d",
                    issue_number,
                    exc_info=True,
                )
        return collected

    # Real branch namespaces the pipeline and sub-agents create. Matches
    # ``issue-<N>`` / ``agent/issue-<N>``, the trailing ``-<N>`` suffix on
    # ``fix|feat|refactor|chore|test|docs/<slug>-<N>`` branches (#10698), and
    # Auto-Agent (preflight) session branches, ``agent/auto-agent-<N>``
    # (#11182) — minted by ``AutoAgentPreflightLoop._resolve_worktree`` via
    # ``HydraFlowConfig.auto_agent_branch_for_issue``.
    _ISSUE_BRANCH_RES: tuple[re.Pattern[str], ...] = (
        re.compile(r"^(?:agent/)?issue-(\d+)$"),
        re.compile(r"^(?:fix|feat|refactor|chore|test|docs)/.*-(\d+)$"),
        re.compile(rf"^{re.escape(AUTO_AGENT_BRANCH_PREFIX)}(\d+)$"),
    )

    @classmethod
    def _parse_issue_from_branch(cls, branch: str | None) -> int | None:
        """Resolve the issue number a branch belongs to across all namespaces.

        Returns None (fail-closed) when the branch cannot be attributed to an
        issue — the caller must NOT guess an issue number for such branches.
        """
        if not branch:
            return None
        name = branch.strip().removeprefix("refs/heads/")
        for pattern in cls._ISSUE_BRANCH_RES:
            match = pattern.match(name)
            if match:
                return int(match.group(1))
        return None

    async def _collect_orphaned_branches(self, budget: int = _MAX_GC_PER_CYCLE) -> int:
        """Delete local orphaned branches with no corresponding worktree.

        Covers every real branch namespace (``agent/issue-<N>``,
        ``agent/auto-agent-<N>`` (#11182), and
        ``fix|feat|refactor|chore|test|docs/<slug>-<N>``) — not just
        ``agent/issue-*`` (#10698) — with the same skip guards as before.
        """
        collected = 0
        try:
            output = await run_subprocess(
                "git",
                "branch",
                "--list",
                cwd=self._config.repo_root,
                gh_token=self._credentials.gh_token,
            )
        except RuntimeError:
            logger.warning("GC: could not list local branches", exc_info=True)
            return 0

        active_workspaces = self._state.get_active_workspaces()
        active_issues = set(self._state.get_active_issue_numbers())
        active_branches = self._state.get_active_branches()

        for line in output.strip().splitlines():
            if collected >= budget:
                break
            branch = line.strip().removeprefix("* ").removeprefix("+ ")
            issue_number = self._parse_issue_from_branch(branch)
            if issue_number is None:
                continue
            try:
                # Skip if worktree exists, issue is active, in pipeline,
                # or still has retries remaining.
                if issue_number in active_workspaces or issue_number in active_issues:
                    continue
                if self._is_in_pipeline and self._is_in_pipeline(issue_number):
                    continue
                if self._in_retry_window(issue_number):
                    continue
                if await self._issue_has_pipeline_label(issue_number):
                    continue
                await run_subprocess(
                    "git",
                    "branch",
                    "-D",
                    branch,
                    cwd=self._config.repo_root,
                    gh_token=self._credentials.gh_token,
                )
                # Multiple branch namespaces (agent/issue-<N>,
                # agent/auto-agent-<N>, fix|feat|.../*-N) can share one issue
                # number (#11182). Only clear the tracked ``active_branches``
                # entry when the branch just deleted is the one it points at
                # — otherwise deleting a stale namespace's branch would evict
                # a live entry for a different, still-existing branch.
                if active_branches.get(issue_number) == branch:
                    self._state.remove_branch(issue_number)
                collected += 1
                logger.info("GC: deleted orphaned branch %s", branch)
            except Exception as exc:  # noqa: BLE001
                reraise_on_credit_or_bug(exc)
                logger.warning(
                    "GC: error processing branch %s — skipping",
                    branch,
                    exc_info=True,
                )
        return collected

    async def _prune_stale_branch_entries(self, budget: int = _MAX_GC_PER_CYCLE) -> int:
        """Remove ``active_branches`` entries whose issue has no worktree and is safe to GC."""
        active_workspaces = self._state.get_active_workspaces()
        active_branches = self._state.get_active_branches()
        pruned = 0
        for issue_number in list(active_branches.keys()):
            if self._stop_event.is_set() or pruned >= budget:
                break
            if issue_number in active_workspaces:
                continue  # worktree still exists — branch entry is valid
            try:
                if await self._is_safe_to_gc(issue_number):
                    self._state.remove_branch(issue_number)
                    pruned += 1
                    logger.info(
                        "GC: pruned stale branch entry for issue #%d", issue_number
                    )
            except Exception as exc:  # noqa: BLE001
                reraise_on_credit_or_bug(exc)
                logger.warning(
                    "GC: could not prune branch entry for issue #%d",
                    issue_number,
                    exc_info=True,
                )
        return pruned

    # ------------------------------------------------------------------
    # Phase 5: enumerate-and-reap orphan worktrees on ALL roots (#10698)
    # ------------------------------------------------------------------

    async def _collect_orphaned_worktrees(
        self,
        budget: int = _MAX_GC_PER_CYCLE,
        *,
        active_snapshot: _ActiveWorkspaceSnapshot | None = None,
    ) -> int:
        """Reap orphan worktrees discovered via ``git worktree list``.

        Authoritative enumeration across every registered worktree root — not
        a single ``issue-*`` directory scan — resolving each worktree's issue
        via all real branch namespaces and applying the unchanged
        ``_is_safe_to_gc`` policy. Fail-closed throughout: a worktree is only
        reaped when it is provably safe (see ``_reap_worktree_if_safe``).

        Worktrees on the standard factory ``issue-<N>`` path are left to the
        existing state/orphan-dir phases so their behaviour is unchanged.
        """
        if budget <= 0:
            return 0
        try:
            worktrees = await self._list_git_worktrees()
        except (RuntimeError, OSError):
            # RuntimeError = git non-zero exit; OSError = repo_root missing /
            # network mount unavailable (mirrors Phase 2's OSError guard, #6413).
            logger.warning("GC: could not list git worktrees", exc_info=True)
            return 0

        repo_root = self._config.repo_root.expanduser().resolve()
        roots = [
            root.expanduser().resolve()
            for root in self._config.worktree_gc_root_paths()
        ]
        if active_snapshot is None:
            active_snapshot = self._active_workspace_snapshot()
        if active_snapshot is None:
            logger.warning(
                "GC: active workspace state identity is malformed or ambiguous — skipping all-root sweep"
            )
            return 0
        active_workspaces = active_snapshot.workspaces
        active_path_owners = active_snapshot.path_owners

        collected = 0
        for entry in worktrees:
            if collected >= budget or self._stop_event.is_set():
                break
            path = entry.path
            # Never touch the primary worktree.
            if path == repo_root:
                continue
            # Blast-radius gate: only sweep configured/known factory roots.
            if not any(_path_within(path, root) for root in roots):
                continue
            # State owns paths independently of whichever branch happens to be
            # checked out there. Branch parsing must never relabel a live path
            # as orphaned (#11507 wrong/unparseable-branch safety).
            if path in active_path_owners:
                logger.debug(
                    "GC: worktree %s is state-owned by issue(s) %s — skipping",
                    path,
                    sorted(active_path_owners[path]),
                )
                continue
            issue_number = self._parse_issue_from_branch(entry.branch)
            # Leave the standard factory issue-<N> path to phases 1-2 so their
            # behaviour is unchanged; and skip anything a live worktree owns.
            if issue_number is not None:
                std_path = self._config.workspace_path_for_issue(
                    issue_number
                ).expanduser()
                with contextlib.suppress(OSError):
                    std_path = std_path.resolve()
                if path == std_path or issue_number in active_workspaces:
                    continue
            try:
                if await self._reap_worktree_if_safe(path, entry.branch, issue_number):
                    collected += 1
            except Exception as exc:  # noqa: BLE001
                reraise_on_credit_or_bug(exc)
                logger.warning(
                    "GC: error processing worktree %s — skipping",
                    path,
                    exc_info=True,
                )
        return collected

    @staticmethod
    def _canonical_active_path_owners(
        active_workspaces: dict[int, str],
    ) -> dict[Path, set[int]] | None:
        """Reverse active state into canonical path → owning issue IDs.

        A malformed state path makes ownership unknowable, so the whole cycle
        stops before any destructive phase rather than risk treating an owned
        path as an orphan. Multiple issue IDs may conservatively own one path.
        """
        owners: dict[Path, set[int]] = {}
        try:
            for issue_number, raw_path in active_workspaces.items():
                if (
                    type(raw_path) is not str
                    or not raw_path.strip()
                    or "\0" in raw_path
                ):
                    return None
                candidate = Path(raw_path)
                if not candidate.is_absolute():
                    return None
                canonical = candidate.resolve()
                owners.setdefault(canonical, set()).add(issue_number)
        except (OSError, RuntimeError, TypeError, ValueError):
            return None
        return owners

    def _active_workspace_snapshot(self) -> _ActiveWorkspaceSnapshot | None:
        """Validate active-workspace keys and paths once for a GC cycle.

        StateTracker's ordinary normalized accessor is intentionally lossy:
        malformed keys are dropped and int-equivalent spellings collapse.
        Destructive GC instead takes one raw-validated snapshot and reuses its
        reverse path ownership in phases 1, 2, and 5. Any ambiguous key or
        path disables the cycle before workspace, branch, or state mutation.
        """
        workspaces = self._state.get_active_workspaces_validated()
        if workspaces is None:
            return None
        path_owners = self._canonical_active_path_owners(workspaces)
        if path_owners is None:
            return None
        return _ActiveWorkspaceSnapshot(workspaces, path_owners)

    async def _reap_worktree_if_safe(
        self, path: Path, branch: str | None, issue_number: int | None
    ) -> bool:
        """Fail-closed decision + reap for a single enumerated worktree.

        Never reaps a worktree that: is younger than ``min_age``; has
        uncommitted changes; belongs to an active/HITL/in-pipeline/in-retry
        issue or an issue whose state is unknown (via ``_is_safe_to_gc``); or
        has work that cannot be proven landed by the canonical, HEAD-aware
        ``_worktree_work_has_landed`` predicate. Issue closure never bypasses
        that proof (#11503), and unattributable worktrees use the same proof.
        """
        # min_age guard — never reap a worktree created mid-run.
        if self._worktree_too_new(path):
            logger.debug("GC: worktree %s younger than min_age — skipping", path)
            return False

        if issue_number is not None and not await self._is_safe_to_gc(issue_number):
            return False

        if not await self._worktree_work_has_landed(
            path,
            expected_branch=branch,
            expected_issue=issue_number,
        ):
            logger.debug("GC: worktree %s has unlanded work — skipping", path)
            return False

        await self._reap_worktree(path, branch, issue_number)
        return True

    async def _list_git_worktrees(self) -> list[_WorktreeEntry]:
        """Parse ``git worktree list --porcelain`` into worktree entries.

        Skips ``bare`` and ``locked`` worktrees (an operator locked those
        deliberately). Raises ``RuntimeError`` if the git call fails so the
        caller can fail-closed to an empty sweep.
        """
        output = await run_subprocess(
            "git",
            "worktree",
            "list",
            "--porcelain",
            cwd=self._config.repo_root,
            gh_token=self._credentials.gh_token,
        )
        entries: list[_WorktreeEntry] = []
        path: Path | None = None
        branch: str | None = None
        locked = False
        is_bare = False

        def _flush() -> None:
            nonlocal path, branch, locked, is_bare
            if path is not None and not locked and not is_bare:
                entries.append(_WorktreeEntry(path=path, branch=branch))
            path, branch, locked, is_bare = None, None, False, False

        for raw_line in output.splitlines():
            line = raw_line.rstrip()
            if line.startswith("worktree "):
                _flush()
                with contextlib.suppress(OSError):
                    path = Path(line[len("worktree ") :]).expanduser().resolve()
            elif line.startswith("branch "):
                branch = line[len("branch ") :].strip().removeprefix("refs/heads/")
            elif line == "detached":
                branch = None
            elif line == "bare":
                is_bare = True
            elif line.startswith("locked"):
                locked = True
        _flush()
        return entries

    def _worktree_too_new(self, path: Path) -> bool:
        """True when *path* is younger than ``worktree_gc_min_age_seconds``.

        A stat failure fails closed (treated as too-new → skip).
        """
        min_age = self._config.worktree_gc_min_age_seconds
        if min_age <= 0:
            return False
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return True
        return (time.time() - mtime) < min_age

    @staticmethod
    def _tracked_path_matches_destroy_target(
        recorded_path: Path, destroy_path: Path
    ) -> bool:
        """True when phase 1 inspected the path ``WorkspacePort`` will delete.

        ``WorkspacePort.destroy(issue)`` derives its target from config, not
        the StateTracker value.  A stale/mismatched mapping must therefore
        fail closed rather than inspect one directory and delete another.
        """
        try:
            recorded = recorded_path.expanduser().resolve()
            target = destroy_path.expanduser().resolve()
            return recorded == target
        except OSError:
            return False

    @staticmethod
    def _parse_worktree_status(
        output: str,
    ) -> tuple[str, str | None, bool] | None:
        """Parse ``git status --porcelain=v2 --branch`` identity + dirtiness."""
        head_sha: str | None = None
        branch: str | None = None
        saw_branch = False
        dirty = False
        for line in output.splitlines():
            if line.startswith("# branch.oid "):
                if head_sha is not None:
                    return None
                head_sha = line.removeprefix("# branch.oid ").strip().lower()
            elif line.startswith("# branch.head "):
                if saw_branch:
                    return None
                raw_branch = line.removeprefix("# branch.head ").strip()
                if not raw_branch or (
                    raw_branch.startswith("(") and raw_branch != "(detached)"
                ):
                    return None
                branch = None if raw_branch == "(detached)" else raw_branch
                saw_branch = True
            elif line and not line.startswith("# "):
                dirty = True
        if (
            not saw_branch
            or head_sha is None
            or _GIT_OID_RE.fullmatch(head_sha) is None
        ):
            return None
        return head_sha, branch, dirty

    async def _worktree_work_has_landed(
        self,
        path: Path,
        *,
        expected_branch: str | None,
        expected_issue: int | None,
    ) -> bool:
        """Prove the exact clean worktree HEAD landed, or fail closed.

        The ladder is deliberately HEAD-aware and ordered cheapest-first:

        1. a HEAD already ancestral to ``origin/<base>`` is landed;
        2. an identical two-rev tree diff covers a fresh squash merge;
        3. after the base advances, GitHub must report one merged PR whose
           base, branch, and historical ``head.sha`` match this worktree.

        Branch name alone is never authoritative because names are reusable.
        Dirty worktrees, branch/issue/path identity mismatches, missing refs,
        malformed git output, GitHub errors, and ambiguous PR rows all return
        ``False``. Local comparisons use the initially captured OID, then
        status is re-read so a concurrent HEAD move cannot mix identities.
        An absent registered path is not landed proof: phase 5 could otherwise
        prune its registry entry and delete the only branch carrying the work.
        An attributed candidate must have a ``.git`` marker and must report
        its own canonical path from ``git rev-parse --show-toplevel`` before
        status is read, so parent-repository discovery or a misdirected
        gitfile cannot prove one tree while GC deletes another. Empty,
        existing, unattributed non-git directories are the sole non-git
        candidates considered provably empty.
        """
        if not path.exists():
            return False
        if not path.is_dir():
            return False
        git_marker = path / ".git"
        if not git_marker.exists():
            if expected_branch is not None or expected_issue is not None:
                return False
            empty = False
            with contextlib.suppress(OSError):
                empty = next(path.iterdir(), None) is None
            return empty

        try:
            candidate_root = path.expanduser().resolve()
        except (OSError, RuntimeError):
            return False

        base = self._config.base_branch()
        commands: list[tuple[str, tuple[str, ...]]] = [
            ("top-level", ("rev-parse", "--show-toplevel")),
        ]
        head_sha = ""
        actual_branch: str | None = None
        local_result: bool | None = None
        while commands and local_result is None:
            kind, args = commands.pop(0)
            if kind == "pr":
                if actual_branch is None:
                    local_result = False
                    continue
                pr_state = "UNKNOWN"
                try:
                    pr_state = await self._prs.get_branch_pr_state(
                        actual_branch,
                        head_sha,
                        base,
                    )
                except Exception as exc:  # noqa: BLE001
                    reraise_on_credit_or_bug(exc)
                if pr_state == "MERGED":
                    commands.append(
                        (
                            "verify-status",
                            ("status", "--porcelain=v2", "--branch"),
                        )
                    )
                else:
                    local_result = False
                continue

            try:
                output = await run_subprocess(
                    "git",
                    *args,
                    cwd=path,
                    gh_token=self._credentials.gh_token,
                )
            except (RuntimeError, OSError):
                local_result = False
                break

            if kind == "top-level":
                reported_root = output.strip()
                try:
                    reported_path = Path(reported_root)
                    if (
                        not reported_root
                        or "\0" in reported_root
                        or len(output.splitlines()) != 1
                        or not reported_path.is_absolute()
                        or reported_path.expanduser().resolve() != candidate_root
                    ):
                        local_result = False
                    else:
                        commands.append(
                            ("status", ("status", "--porcelain=v2", "--branch"))
                        )
                except (OSError, RuntimeError, ValueError):
                    local_result = False
                continue

            if kind in {"status", "verify-status"}:
                parsed = self._parse_worktree_status(output)
                if parsed is None:
                    local_result = False
                elif kind == "verify-status":
                    verified_head, verified_branch, verified_dirty = parsed
                    local_result = (
                        not verified_dirty
                        and verified_head == head_sha
                        and verified_branch == actual_branch
                    )
                else:
                    head_sha, actual_branch, dirty = parsed
                    normalized_expected = (
                        expected_branch.removeprefix("refs/heads/")
                        if expected_branch
                        else None
                    )
                    if (
                        dirty
                        or (
                            normalized_expected is not None
                            and actual_branch != normalized_expected
                        )
                        or (
                            expected_issue is not None
                            and self._parse_issue_from_branch(actual_branch)
                            != expected_issue
                        )
                    ):
                        local_result = False
                    else:
                        commands.append(
                            (
                                "rev-list",
                                (
                                    "rev-list",
                                    "--count",
                                    f"origin/{base}..{head_sha}",
                                ),
                            )
                        )
                continue

            if kind == "rev-list":
                try:
                    unique_commits = int(output.strip())
                except ValueError:
                    local_result = False
                else:
                    if unique_commits < 0:
                        local_result = False
                    elif unique_commits == 0:
                        commands.append(
                            (
                                "verify-status",
                                ("status", "--porcelain=v2", "--branch"),
                            )
                        )
                    else:
                        commands.append(
                            (
                                "diff",
                                (
                                    "diff",
                                    "--name-only",
                                    f"origin/{base}",
                                    head_sha,
                                ),
                            )
                        )
                continue

            if not output.strip():
                commands.append(
                    (
                        "verify-status",
                        ("status", "--porcelain=v2", "--branch"),
                    )
                )
            else:
                commands.append(("pr", ()))

        return local_result is True

    async def _reap_worktree(
        self, path: Path, branch: str | None, issue_number: int | None
    ) -> None:
        """Remove the worktree at *path* and delete its branch.

        Routed through local git (``git worktree remove --force`` +
        ``git branch -D``) mirroring ``_collect_orphaned_branches``. State
        entries for a resolved issue are cleared idempotently.
        """
        if self._config.dry_run:
            logger.info(
                "[dry-run] Would reap orphan worktree %s (branch %s)", path, branch
            )
            return
        await run_subprocess(
            "git",
            "worktree",
            "remove",
            "--force",
            str(path),
            cwd=self._config.repo_root,
            gh_token=self._credentials.gh_token,
        )
        if branch:
            with contextlib.suppress(RuntimeError):
                await run_subprocess(
                    "git",
                    "branch",
                    "-D",
                    branch,
                    cwd=self._config.repo_root,
                    gh_token=self._credentials.gh_token,
                )
        if issue_number is not None:
            self._state.remove_workspace(issue_number)
            # Cross-namespace aliasing guard (same as phase 3, #11182): the
            # tracked ``active_branches`` entry may name a *different*,
            # still-live branch for this issue — only evict it when it
            # matches the branch just deleted.
            if branch and (
                self._state.get_active_branches().get(issue_number) == branch
            ):
                self._state.remove_branch(issue_number)
        logger.info("GC: reaped orphan worktree %s (branch %s)", path, branch)
