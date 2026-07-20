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
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
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

    async def _do_work(self) -> dict[str, Any] | None:
        """Scan for stale issues and close them."""
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        if not self._config.stale_issue_loop_enabled:
            return {"status": "config_disabled"}
        settings = self._state.get_stale_issue_settings()
        already_closed = self._state.get_stale_issue_closed()

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

        if self._obs is not None:
            self._obs.breadcrumb(
                "stale_issue.cycle",
                f"Scanned {stats['scanned']} issues, closed {stats['closed']}",
                level="info",
                **dict(stats.items()),
            )

        return stats
