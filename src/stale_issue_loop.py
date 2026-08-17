"""Background worker loop — auto-close stale *general* issues with no recent activity.

Scope: open issues that do NOT carry a HydraFlow lifecycle label
(``planner``, ``ready``, ``review``, ``hitl``). The complement —
stale HITL escalations — is owned by ``stale_issue_gc_loop``, which
posts a farewell comment and caps at 10 closes/cycle. The two loops
have effectively zero business-logic overlap; they share only the
``BaseBackgroundLoop`` scaffolding.

Also hosts the regression-rot check (#9597, no new loop — see
:meth:`StaleIssueLoop._scan_regression_rot`): StaleIssueLoop already runs a
daily, full-repo, issue-state-aware sweep, which is the same cadence and
issue-filing shape the regression-rot detector needs, so it rides along in
the same tick rather than spinning up a dedicated caretaker.

Also hosts the stale agent-branch GC + false "fix applied" comment
reconciler (#10011, no new loop — see :meth:`StaleIssueLoop._scan_branch_gc`):
same reasoning as regression-rot — a daily, issue-commenting sweep is exactly
the cadence/shape the branch reconciler needs, and it shares the same
"ride along in the existing tick" precedent rather than adding a sixth
caretaker with near-identical wiring. ``WorkspaceGCLoop`` was considered
(it already deletes orphaned *local* ``agent/issue-*`` branches) but that
loop has no issue-commenting surface and operates on local branches only,
whereas this feature inventories *remote* ``origin/*`` branches and posts a
truth comment on GitHub — StaleIssueLoop's existing ``post_comment`` +
``get_issue_state`` plumbing (built for regression-rot) is a closer fit.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from backlog_budget import (
    RETIREMENT_COMMENT,
    retirement_picks,
)
from base_background_loop import BaseBackgroundLoop, LoopDeps
from branch_gc_scan import (
    build_truth_comment,
    classify_branch,
    extract_issue_number,
    should_delete_branch,
)
from config import HydraFlowConfig
from dedup_store import DedupStore
from exception_classify import reraise_on_credit_or_bug
from regression_rot_scan import (
    build_rollup_body,
    classify_regression_rot,
    scan_regression_dir,
)
from regression_rot_timestamps import RegressionRotTimestamps
from rollup_issue_manager import RollupIssueManager

if TYPE_CHECKING:
    from ports import ObservabilityPort
    from pr_manager import PRManager
    from state import StateTracker

logger = logging.getLogger("hydraflow.stale_issue_loop")

# Regression-rot rollup (#9597) — one issue total, body-refreshed each tick.
_REGRESSION_ROT_NAMESPACE = "stale_issue_regression_rot"
_REGRESSION_ROT_SUBJECT = "regression_rot"
_REGRESSION_ROT_TITLE = (
    "Regression-test rot: RED pins on closed or long-stale-open issues"
)

# Branch-GC reconciler (#10011) — remote branch prefixes inventoried each
# tick, and a per-cycle budget so a repo with hundreds of stale branches
# can't turn one tick into a long-running gh-API marathon (mirrors
# WorkspaceGCLoop's _MAX_GC_PER_CYCLE).
_BRANCH_GC_PREFIXES = ("agent/issue-", "fix/")
_MAX_BRANCH_GC_PER_CYCLE = 20


class StaleIssueLoop(BaseBackgroundLoop):
    """Polls for stale issues and auto-closes them after configurable inactivity period."""

    def __init__(
        self,
        config: HydraFlowConfig,
        prs: PRManager,
        state: StateTracker,
        deps: LoopDeps,
        *,
        observability: ObservabilityPort | None = None,
    ) -> None:
        super().__init__(worker_name="stale_issue", config=config, deps=deps)
        self._prs = prs
        self._state = state
        self._obs: ObservabilityPort | None = observability
        self._regression_rot_timestamps = RegressionRotTimestamps(
            config.data_root / "dedup" / "stale_issue_regression_rot_ages.json"
        )
        self._branch_gc_dedup = DedupStore(
            "stale_branch_gc_commented",
            config.data_root / "dedup" / "branch_gc_commented.json",
        )

    def _get_default_interval(self) -> int:
        return self._config.stale_issue_interval

    def _regression_rot_rollup(self) -> RollupIssueManager:
        return RollupIssueManager(
            pr=self._prs,
            state=self._state,
            namespace=_REGRESSION_ROT_NAMESPACE,
            labels=list(self._config.find_label),
        )

    async def _scan_regression_rot(self) -> dict[str, int]:
        """Detect false-close rot and orphaned-RED regression pins (#9597).

        No-ops when this checkout has no ``tests/regressions/`` directory —
        most unit-test fixtures and MockWorld scenarios don't create one,
        and there is nothing to scan or reconcile in that case. RED-ness is
        inferred statically (xfail marker text) — no pytest invocation.
        """
        regressions_dir = self._config.repo_root / "tests" / "regressions"
        if not regressions_dir.is_dir():
            return {}

        files = scan_regression_dir(regressions_dir)

        candidate_numbers: set[int] = set()
        for f in files:
            if not f.is_xfail_red or f.blocked_on is not None:
                continue
            candidate_numbers.update(f.issue_numbers)

        issue_states: dict[int, str] = {}
        for number in candidate_numbers:
            try:
                issue_states[number] = await self._prs.get_issue_state(number)
            except Exception as exc:
                reraise_on_credit_or_bug(exc)
                logger.warning(
                    "regression-rot: could not resolve state of issue #%s",
                    number,
                    exc_info=True,
                )
                issue_states[number] = "UNKNOWN"

        now = datetime.now(UTC)
        open_numbers = {n for n, s in issue_states.items() if s == "OPEN"}
        ages_days: dict[int, int] = {}
        for number in open_numbers:
            first_seen = self._regression_rot_timestamps.set_if_absent(
                number, now.isoformat()
            )
            try:
                first_seen_dt = datetime.fromisoformat(first_seen)
            except ValueError:
                first_seen_dt = now
            ages_days[number] = (now - first_seen_dt).days
        # Stop tracking issues no longer RED-and-open so a fixed/closed/
        # blocked issue's clock resets instead of accumulating forever.
        self._regression_rot_timestamps.keep_only(open_numbers)

        findings = classify_regression_rot(
            files,
            issue_states,
            ages_days,
            stale_days=self._config.stale_issue_regression_rot_stale_days,
        )

        if findings:
            body = build_rollup_body(findings)
            await self._regression_rot_rollup().ensure(
                _REGRESSION_ROT_SUBJECT, title=_REGRESSION_ROT_TITLE, body=body
            )
        else:
            await self._regression_rot_rollup().resolve(_REGRESSION_ROT_SUBJECT)

        return {
            "regression_rot_scanned": len(files),
            "regression_rot_false_close": sum(
                1 for f in findings if f.kind == "false_close"
            ),
            "regression_rot_orphaned": sum(
                1 for f in findings if f.kind == "orphaned_red"
            ),
        }

    async def _branch_gc_candidate_branches(self) -> list[str]:
        """List remote branches under the tracked GC prefixes (#10011).

        Composes the existing ``PRManager._run_gh`` passthrough (already used
        above for ``gh issue list``) rather than adding a new PRPort method —
        the GitHub matching-refs read needs no port-level abstraction beyond
        what's already reachable here, and FakeGitHub's generic ``_run_gh``
        dispatcher safely no-ops unknown ``gh api`` shapes to ``"[]"``.
        """
        branches: list[str] = []
        for prefix in _BRANCH_GC_PREFIXES:
            try:
                raw = await self._prs._run_gh(
                    "gh",
                    "api",
                    f"repos/{self._prs._repo}/git/matching-refs/heads/{prefix}",
                    "--jq",
                    "[.[].ref]",
                )
                refs = json.loads(raw) if raw.strip() else []
            except Exception as exc:
                reraise_on_credit_or_bug(exc)
                logger.debug(
                    "branch-gc: could not list refs for prefix %r",
                    prefix,
                    exc_info=True,
                )
                continue
            branches.extend(
                str(ref).removeprefix("refs/heads/")
                for ref in refs
                if isinstance(ref, str)
            )
        return branches

    async def _branch_gc_commit_info(self, branch: str) -> tuple[str, list[str]] | None:
        """Return ``(last_commit_iso, commit_messages)`` for *branch*, newest first.

        One ``gh api .../commits`` call serves both the branch's age (the
        newest commit's date) and the full commit-message history needed to
        find a ``Fixes #N`` reference that isn't necessarily the tip commit.
        ``--method GET`` is required alongside ``--field`` — ``gh api``
        defaults to POST once any ``--field`` is present (matches
        ``find_open_pr_for_branch``'s call shape above).
        """
        try:
            raw = await self._prs._run_gh(
                "gh",
                "api",
                f"repos/{self._prs._repo}/commits",
                "--method",
                "GET",
                "--field",
                f"sha={branch}",
                "--field",
                "per_page=30",
                "--jq",
                "[.[] | {date: .commit.committer.date, message: .commit.message}]",
            )
            commits = json.loads(raw) if raw.strip() else []
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.debug(
                "branch-gc: could not fetch commits for %s", branch, exc_info=True
            )
            return None
        if not isinstance(commits, list) or not commits:
            return None
        messages = [c.get("message", "") for c in commits if isinstance(c, dict)]
        last_commit_iso = next(
            (
                c.get("date", "")
                for c in commits
                if isinstance(c, dict) and c.get("date")
            ),
            "",
        )
        return last_commit_iso, messages

    async def _scan_branch_gc(self) -> dict[str, int]:
        """Inventory stale agent/fix branches; reconcile false 'fix applied' claims.

        For each ``agent/issue-*`` / ``fix/*`` remote branch carrying a
        resolvable ``Fixes #N`` reference: if it's unmerged (no open PR),
        the referenced issue is still OPEN, and it's sat that way for
        ``branch_gc_stale_days`` — post ONE truth comment telling the issue
        that prior "fix applied" claims are unverified (deduped so each
        branch is only commented once), then separately consider
        delete-or-escalate once the branch clears
        ``branch_gc_min_delete_age_days`` (deletion stays report-only unless
        ``branch_gc_delete_enabled`` is set — see :mod:`branch_gc_scan`).

        Returns ``{}`` (no-op, mirroring :meth:`_scan_regression_rot`'s
        missing-directory short-circuit) when no candidate branches exist —
        most repos have zero stale ``agent/issue-*`` / ``fix/*`` branches on
        any given tick, and there's nothing to report.
        """
        stats = {
            "branch_gc_scanned": 0,
            "branch_gc_commented": 0,
            "branch_gc_deleted": 0,
            "branch_gc_escalated": 0,
        }
        try:
            branches = await self._branch_gc_candidate_branches()
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning("branch-gc: could not inventory branches", exc_info=True)
            return stats
        if not branches:
            return {}

        commented = self._branch_gc_dedup.get()
        now = datetime.now(UTC)

        for branch in branches[:_MAX_BRANCH_GC_PER_CYCLE]:
            stats["branch_gc_scanned"] += 1
            try:
                info = await self._branch_gc_commit_info(branch)
                if info is None:
                    continue
                last_commit_iso, messages = info
                issue_number = extract_issue_number(branch, messages)
                if issue_number <= 0:
                    continue

                try:
                    last_commit_dt = datetime.fromisoformat(
                        last_commit_iso.replace("Z", "+00:00")
                    )
                    if last_commit_dt.tzinfo is None:
                        last_commit_dt = last_commit_dt.replace(tzinfo=UTC)
                except (ValueError, AttributeError):
                    continue
                age_days = (now - last_commit_dt).days

                pr = await self._prs.find_open_pr_for_branch(
                    branch, issue_number=issue_number
                )
                has_open_pr = pr is not None and pr.number > 0
                issue_state = await self._prs.get_issue_state(issue_number)

                decision = classify_branch(
                    issue_number=issue_number,
                    age_days=age_days,
                    has_open_pr=has_open_pr,
                    issue_state=issue_state,
                    already_commented=branch in commented,
                    stale_days=self._config.branch_gc_stale_days,
                )

                if decision.should_comment:
                    await self._prs.post_comment(
                        issue_number, build_truth_comment(branch, age_days)
                    )
                    self._branch_gc_dedup.add(branch)
                    commented.add(branch)
                    stats["branch_gc_commented"] += 1
                    logger.info(
                        "branch-gc: posted truth comment on #%d for branch %s",
                        issue_number,
                        branch,
                    )

                if decision.eligible_for_delete_check:
                    min_age = self._config.branch_gc_min_delete_age_days
                    if should_delete_branch(
                        age_days=age_days,
                        min_delete_age_days=min_age,
                        delete_enabled=self._config.branch_gc_delete_enabled,
                    ):
                        if await self._prs.delete_branch(branch):
                            self._branch_gc_dedup.discard(branch)
                            commented.discard(branch)
                            stats["branch_gc_deleted"] += 1
                            logger.info("branch-gc: deleted stale branch %s", branch)
                    elif age_days >= min_age:
                        stats["branch_gc_escalated"] += 1
                        logger.warning(
                            "branch-gc: %s is %d days old and eligible for "
                            "deletion, but branch_gc_delete_enabled=False — "
                            "report-only",
                            branch,
                            age_days,
                        )
            except Exception as exc:
                reraise_on_credit_or_bug(exc)
                logger.warning(
                    "branch-gc: error processing branch %s — skipping",
                    branch,
                    exc_info=True,
                )

        return stats

    async def _do_work(self) -> dict[str, Any] | None:
        """Scan for stale issues and close them."""
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        if not self._config.stale_issue_loop_enabled:
            return {"status": "config_disabled"}
        settings = self._state.get_stale_issue_settings()
        already_closed = self._state.get_stale_issue_closed()

        # #11298 retirement valve — rides this loop per its own ride-along
        # precedent (regression-rot #9597, branch-GC #10011): a daily,
        # issue-closing sweep is exactly the shape the valve needs.
        budget_stats = await self._scan_backlog_budget()

        stats: dict[str, int] = {"scanned": 0, "closed": 0, "skipped": 0}

        # Fetch open issues that don't have HydraFlow lifecycle labels
        exclude_labels = [
            *self._config.planner_label,
            *self._config.ready_label,
            *self._config.review_label,
            *self._config.hitl_label,
            *settings.excluded_labels,
        ]

        try:
            raw = await self._prs._run_gh(
                "gh",
                "issue",
                "list",
                "--repo",
                self._prs._repo,
                "--state",
                "open",
                "--limit",
                "100",
                "--json",
                "number,title,updatedAt,labels",
            )
            issues = json.loads(raw) if raw else []
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning("Failed to fetch issues for stale check", exc_info=True)
            return stats

        cutoff = datetime.now(UTC) - timedelta(days=settings.staleness_days)

        for issue in issues:
            number = issue.get("number", 0)
            if number in already_closed:
                stats["skipped"] += 1
                continue

            # Skip issues with excluded labels
            issue_labels = [lbl.get("name", "") for lbl in issue.get("labels", [])]
            if any(el in issue_labels for el in exclude_labels):
                stats["skipped"] += 1
                continue

            stats["scanned"] += 1

            # Check last activity
            updated = issue.get("updatedAt", "")
            try:
                updated_dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                if updated_dt.tzinfo is None:
                    updated_dt = updated_dt.replace(tzinfo=UTC)
            except (ValueError, AttributeError):
                continue

            if updated_dt > cutoff:
                continue  # Not stale yet

            # Stale — close it
            if settings.dry_run:
                logger.info(
                    "[dry-run] Would close stale issue #%d: %s",
                    number,
                    issue.get("title", ""),
                )
                stats["closed"] += 1
                continue

            try:
                await self._prs.post_comment(
                    number,
                    "## Auto-closed: Stale Issue\n\n"
                    "This issue has been automatically closed due to inactivity "
                    f"(no updates for {settings.staleness_days} days). "
                    "If this is still relevant, please reopen it.\n\n"
                    "*Closed by HydraFlow Stale Issue Cleanup.*",
                )
                await self._prs._run_gh(
                    "gh",
                    "issue",
                    "close",
                    "--repo",
                    self._prs._repo,
                    str(number),
                )
                self._state.add_stale_issue_closed(number)
                stats["closed"] += 1
                logger.info(
                    "Closed stale issue #%d: %s", number, issue.get("title", "")
                )
            except Exception as exc:
                reraise_on_credit_or_bug(exc)
                logger.warning("Failed to close stale issue #%d", number, exc_info=True)

        stats.update(await self._scan_regression_rot())
        stats.update(await self._scan_branch_gc())

        if self._obs is not None:
            self._obs.breadcrumb(
                "stale_issue.cycle",
                f"Scanned {stats['scanned']} issues, closed {stats['closed']}",
                level="info",
                **dict(stats.items()),
            )

        stats["retired"] = budget_stats.get("retired", 0)
        return stats

    async def _scan_backlog_budget(self) -> dict[str, int]:
        """#11298 retirement valve: close the oldest advisory issues beyond
        ``config.backlog_budget``.

        Selection is delegated to the pure ``backlog_budget`` engine
        (advisory labels only, protected classes exempt, grace period,
        oldest-first, capped per cycle). Fail-soft: any fetch/close error
        logs and returns — the valve can only under-retire, never block
        the stale sweep.
        """
        stats = {"retired": 0}
        budget = self._config.backlog_budget
        # isinstance (not truthiness/comparison): MagicMock configs in the
        # test suite auto-attribute a truthy budget — the valve must only
        # arm on a real int (the MagicMock-truthy-guard incident class).
        if not isinstance(budget, int) or budget <= 0:
            return stats
        try:
            raw = await self._prs._run_gh(
                "gh",
                "issue",
                "list",
                "--repo",
                self._prs._repo,
                "--state",
                "open",
                "--limit",
                "200",
                "--json",
                "number,title,createdAt,labels",
            )
            issues = json.loads(raw) if raw else []
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning("Backlog-budget fetch failed", exc_info=True)
            return stats
        cfg = self._config
        picks = retirement_picks(
            issues,
            budget=budget,
            min_age_days=cfg.backlog_budget_min_age_days,
            now=datetime.now(UTC),
            # Config-sourced (never the module literals): an operator label
            # rename must keep protection intact — drifting the protected
            # set silently would retire LIVE work, the dangerous direction.
            advisory_labels=frozenset(
                [
                    *cfg.find_label,
                    *cfg.planner_label,
                    *cfg.diagnose_label,
                    *cfg.parked_label,
                ]
            ),
            protected_labels=frozenset(
                [
                    *cfg.ready_label,
                    *cfg.review_label,
                    *cfg.in_progress_label,
                    *cfg.hitl_label,
                    *cfg.hitl_active_label,
                    *cfg.hitl_autofix_label,
                    *cfg.light_autofix_label,
                    "human-required",
                    "hydraflow-epic",
                    "hydraflow-epic-child",
                    "hydraflow-refinement-digest",
                    "P1",
                    "P2",
                ]
            ),
        )
        settings = self._state.get_stale_issue_settings()
        dry_run = bool(self._config.dry_run) or bool(settings.dry_run)
        for pick in picks:
            if dry_run:
                # Mirrors the stale-close path 40 lines below: dry-run
                # logs the decision, closes nothing (review BLOCKING —
                # _run_gh has no dry-run awareness of its own).
                logger.info(
                    "[dry-run] Backlog valve would retire #%d (%.1fd): %s",
                    pick.number,
                    pick.age_days,
                    pick.title,
                )
                continue
            try:
                await self._prs.post_comment(pick.number, RETIREMENT_COMMENT)
                await self._prs._run_gh(
                    "gh",
                    "issue",
                    "close",
                    "--repo",
                    self._prs._repo,
                    str(pick.number),
                )
                stats["retired"] += 1
                logger.info(
                    "Backlog valve retired #%d (%.1fd old): %s",
                    pick.number,
                    pick.age_days,
                    pick.title,
                )
            except Exception as exc:
                reraise_on_credit_or_bug(exc)
                logger.warning(
                    "Backlog valve failed to retire #%d", pick.number, exc_info=True
                )
        return stats
