"""Background worker loop — monitor CI health and create issues for failures."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from subprocess_util import run_subprocess_with_retry

if TYPE_CHECKING:
    from pr_manager import PRManager
    from state import StateTracker

logger = logging.getLogger("hydraflow.ci_monitor_loop")

_CI_FIX_PREFIX = "[CI Fix]"


class CIMonitorLoop(BaseBackgroundLoop):
    """Polls GitHub Actions workflow runs and creates issues for failures."""

    def __init__(
        self,
        config: HydraFlowConfig,
        prs: PRManager,
        state: StateTracker,
        deps: LoopDeps,
    ) -> None:
        super().__init__(worker_name="ci_monitor", config=config, deps=deps)
        self._prs = prs
        self._state = state

    def _get_default_interval(self) -> int:
        return self._config.ci_monitor_interval

    async def _fetch_runs(self, branch: str) -> list[dict[str, Any]]:
        """Fetch recent workflow runs for the given branch."""
        repo = self._config.repo
        raw = await run_subprocess_with_retry(
            "gh",
            "api",
            f"repos/{repo}/actions/runs?branch={branch}&per_page=5",
        )
        data = json.loads(raw)
        return data.get("workflow_runs", [])

    async def _has_open_ci_fix_issue(self, workflow: str, branch: str) -> bool:
        """Check whether an open issue with the [CI Fix] prefix already exists."""
        repo = self._config.repo
        title_query = f"{_CI_FIX_PREFIX} {workflow} failing on {branch}"
        try:
            raw = await run_subprocess_with_retry(
                "gh",
                "issue",
                "list",
                "--repo",
                repo,
                "--state",
                "open",
                "--search",
                title_query,
                "--json",
                "number,title",
            )
            issues = json.loads(raw)
            return any(
                issue.get("title", "").startswith(f"{_CI_FIX_PREFIX} {workflow}")
                for issue in issues
            )
        except Exception:
            logger.debug("Failed to search for existing CI fix issues", exc_info=True)
            return False

    async def _do_work(self) -> dict[str, Any] | None:
        """Check CI workflows and create issues for failures."""
        settings = self._state.get_ci_monitor_settings()
        tracked = self._state.get_ci_monitor_tracked_failures()
        branch = settings.branch
        filter_workflows = set(settings.workflows) if settings.workflows else None

        runs = await self._fetch_runs(branch)

        # Group by workflow name, keep most recent per workflow
        latest_by_workflow: dict[str, dict[str, Any]] = {}
        for run in runs:
            wf_name = run.get("name", "")
            if not wf_name:
                continue
            if filter_workflows and wf_name not in filter_workflows:
                continue
            if wf_name not in latest_by_workflow:
                latest_by_workflow[wf_name] = run

        workflows_checked = len(latest_by_workflow)
        failures_detected = 0
        issues_created = 0
        recovered = 0

        for wf_name, run in latest_by_workflow.items():
            conclusion = run.get("conclusion")
            run_id = str(run.get("id", ""))
            html_url = run.get("html_url", "")

            if conclusion == "failure":
                if wf_name in tracked:
                    # Already tracked — dedup
                    continue
                failures_detected += 1

                if settings.create_issue:
                    # Check for existing open issue before creating
                    if await self._has_open_ci_fix_issue(wf_name, branch):
                        logger.info(
                            "Open [CI Fix] issue already exists for %s — skipping",
                            wf_name,
                        )
                        # Still track it so we don't re-check next cycle
                        tracked[wf_name] = run_id
                        continue

                    title = f"{_CI_FIX_PREFIX} {wf_name} failing on {branch}"
                    body = (
                        f"## CI Failure Detected\n\n"
                        f"**Workflow:** {wf_name}\n"
                        f"**Branch:** {branch}\n"
                        f"**Run ID:** {run_id}\n"
                        f"**Link:** {html_url}\n\n"
                        f"This issue was automatically created by the CI monitor."
                    )
                    find_label = (self._config.find_label or ["hydraflow-find"])[0]
                    await self._prs.create_issue(title, body, [find_label])
                    issues_created += 1
                    logger.info(
                        "Created CI fix issue for workflow %s (run %s)",
                        wf_name,
                        run_id,
                    )
                else:
                    logger.info(
                        "CI failure detected for %s but create_issue disabled — skipping issue creation",
                        wf_name,
                    )

                tracked[wf_name] = run_id

            elif conclusion == "success" and wf_name in tracked:
                # Workflow recovered
                del tracked[wf_name]
                recovered += 1
                logger.info("Workflow %s recovered on %s", wf_name, branch)

        self._state.set_ci_monitor_tracked_failures(tracked)

        try:
            import sentry_sdk as _sentry  # noqa: PLC0415

            _sentry.add_breadcrumb(
                category="ci_monitor.check_completed",
                message="CI monitor check completed",
                level="info",
                data={
                    "workflows_checked": workflows_checked,
                    "failures_detected": failures_detected,
                    "issues_created": issues_created,
                    "recovered": recovered,
                },
            )
        except ImportError:
            pass

        return {
            "workflows_checked": workflows_checked,
            "failures_detected": failures_detected,
            "issues_created": issues_created,
            "recovered": recovered,
        }
