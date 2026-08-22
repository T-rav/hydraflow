"""CI / GitHub Actions surface of :class:`pr_manager.PRManager`.

Extracted VERBATIM from ``pr_manager.py`` (god-class decomposition, Refs
#11547) as a mixin, same shape as ``pr_manager_promotion.py``. ``PRManager``
inherits :class:`PRManagerCIMixin`, so ``PRManager().wait_for_ci`` and every
``patch("pr_manager.PRManager.<method>")`` site resolve unchanged.

One cohesive concern: everything about *whether the machine is happy* —
workflow-run listing and rerun, check-run state for a PR, failure-log and
code-scanning-alert fetching, the advisory-vs-required verdict, and the
``wait_for_ci`` poll loop that the review phase blocks on.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

import ci_sentinels
from events import EventType, HydraFlowEvent
from models import CICheckPayload, CodeScanningAlert
from subprocess_util import run_subprocess

if TYPE_CHECKING:
    import re
    from pathlib import Path

    from config import Credentials, HydraFlowConfig
    from events import EventBus

logger = logging.getLogger("hydraflow.pr_manager")


class PRManagerCIMixin:
    """CI / Actions queries mixed into :class:`pr_manager.PRManager`."""

    # ------------------------------------------------------------------
    # Collaborator seams — attributes and methods provided by PRManager or a
    # sibling mixin. The method declarations are TYPE_CHECKING-only on
    # purpose: a runtime ``...`` body would take precedence over the real
    # implementation whenever the declaring mixin precedes the implementing
    # one in PRManager's MRO.
    # ------------------------------------------------------------------
    _config: HydraFlowConfig
    _repo: str
    _bus: EventBus
    _credentials: Credentials
    _PASSING_STATES: frozenset[str]
    _PENDING_STATES: frozenset[str]
    _RUN_ID_PATTERN: re.Pattern[str]

    if TYPE_CHECKING:

        def _assert_repo(self) -> None: ...  # provided by PRManager

        async def _run_gh(
            self, *cmd: str, cwd: Path | None = None
        ) -> str: ...  # provided by PRManager

        async def _gh_json_query(
            self, *args: Any, **kwargs: Any
        ) -> Any: ...  # provided by PRManager

    async def list_workflow_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return recent workflow runs, newest first (#9974, read-only).

        Uses the REST runs endpoint (not ``gh run list``) because the run
        object carries ``pull_requests`` — the PR association that
        blame-correlation needs.
        """
        self._assert_repo()
        per_page = max(1, min(int(limit), 100))
        output = await self._run_gh(
            "gh",
            "api",
            f"repos/{self._repo}/actions/runs?per_page={per_page}",
            "--jq",
            (
                "[.workflow_runs[] | {id: .id, workflow: .name, "
                'conclusion: (.conclusion // ""), created_at: .created_at, '
                "pr_number: (.pull_requests[0].number // 0)}]"
            ),
        )
        try:
            rows = json.loads(output or "[]")
        except ValueError:
            logger.warning("list_workflow_runs: unparseable gh output")
            return []
        return (
            [row for row in rows if isinstance(row, dict)]
            if isinstance(rows, list)
            else []
        )

    async def list_runs_for_workflow(
        self, workflow: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Return recent runs of ONE workflow file, newest first (#9814).

        Uses the workflow-scoped REST runs endpoint so a single fetch
        covers the RC-history consumers' windows without pulling every
        workflow's runs. ``run_started_at`` falls back to ``created_at``
        for runs that never started (rc_budget's duration math needs a
        timestamp either way).
        """
        self._assert_repo()
        per_page = max(1, min(int(limit), 100))
        output = await self._run_gh(
            "gh",
            "api",
            f"repos/{self._repo}/actions/workflows/{workflow}/runs?per_page={per_page}",
            "--jq",
            (
                '[.workflow_runs[] | {id: .id, url: (.html_url // ""), '
                'status: (.status // ""), conclusion: (.conclusion // ""), '
                'created_at: (.created_at // ""), '
                'run_started_at: (.run_started_at // .created_at // ""), '
                'updated_at: (.updated_at // "")}]'
            ),
        )
        try:
            rows = json.loads(output or "[]")
        except ValueError:
            logger.warning("list_runs_for_workflow: unparseable gh output")
            return []
        return (
            [row for row in rows if isinstance(row, dict)]
            if isinstance(rows, list)
            else []
        )

    async def get_workflow_run_jobs(self, run_id: int) -> list[dict[str, Any]]:
        """Return jobs for one workflow run (#9974, enriched #10010, #10027).

        Each dict: ``{"name", "status", "conclusion", "started_at",
        "completed_at", "steps"}``. ``started_at``/``completed_at``/``steps``
        feed GateHealthLoop's suspected-hang classifier (duration vs. the
        workflow's configured timeout-minutes, plus whether a test step
        ever reached a terminal conclusion) — the jobs API is the only
        source for a job's *actual* timing and step-level outcomes.

        ``status`` (queued / in_progress / completed, #10027) lets
        PrRedRepairLoop's settled-red predicate tell a genuinely finished
        job apart from one mid-rerun whose ``conclusion`` still reads its
        OLD (pre-rerun) value while ``status`` has already flipped back to
        pending — additive field, existing consumers ignore it.
        """
        self._assert_repo()
        output = await self._run_gh(
            "gh",
            "api",
            f"repos/{self._repo}/actions/runs/{int(run_id)}/jobs?per_page=100",
            "--jq",
            (
                '[.jobs[] | {name: .name, status: (.status // ""), '
                'conclusion: (.conclusion // ""), '
                'started_at: (.started_at // ""), '
                'completed_at: (.completed_at // ""), '
                "steps: [.steps[]? | {name: .name, "
                'conclusion: (.conclusion // "")}]}]'
            ),
        )
        try:
            rows = json.loads(output or "[]")
        except ValueError:
            logger.warning("get_workflow_run_jobs: unparseable gh output")
            return []
        return (
            [row for row in rows if isinstance(row, dict)]
            if isinstance(rows, list)
            else []
        )

    async def count_workflow_run_artifacts(self, run_id: int) -> int:
        """Return how many artifacts a workflow run uploaded (#9974)."""
        self._assert_repo()
        output = await self._run_gh(
            "gh",
            "api",
            f"repos/{self._repo}/actions/runs/{int(run_id)}/artifacts",
            "--jq",
            ".total_count",
        )
        try:
            return int((output or "0").strip())
        except ValueError:
            return 0

    async def rerun_workflow_failed(self, run_id: int) -> bool:
        """Trigger ``gh run rerun <id> --failed`` (#10027 bounded infra-flake retry).

        Reruns only the FAILED jobs within *run_id* — the same run id
        persists, which is why the caller's attempt cap is keyed by PR
        number rather than expecting a fresh run id per retry. Returns
        ``True`` on success, ``False`` on any ``gh`` failure (never
        raises) so the caller's attempt-cap bookkeeping stays authoritative
        regardless of transient gh/API errors.
        """
        if self._config.dry_run:
            logger.info("[dry-run] Would rerun failed jobs for run %d", run_id)
            return False
        self._assert_repo()
        try:
            await self._run_gh(
                "gh",
                "run",
                "rerun",
                str(run_id),
                "--repo",
                self._repo,
                "--failed",
            )
        except RuntimeError:
            logger.warning(
                "rerun_workflow_failed: gh run rerun failed for run %d",
                run_id,
                exc_info=True,
            )
            return False
        return True

    async def get_latest_ci_status(self) -> tuple[str, str]:
        """Return (conclusion, url) for the latest CI run on the main branch."""
        self._assert_repo()
        output = await self._run_gh(
            "gh",
            "run",
            "list",
            "--repo",
            self._repo,
            "--branch",
            self._config.main_branch,
            "--limit",
            "1",
            "--json",
            "conclusion,url",
            "--jq",
            ".[0] | [.conclusion, .url] | @tsv",
        )
        parts = output.strip().split("\t")
        conclusion = parts[0] if parts else ""
        url = parts[1] if len(parts) > 1 else ""
        return (conclusion, url)

    async def get_pr_checks(self, pr_number: int) -> list[dict[str, str]]:
        """Fetch CI check results for *pr_number*.

        Returns a list of dicts with ``name`` and ``state`` keys.
        Returns an empty list on failure or in dry-run mode.
        """
        return await self._gh_json_query(
            "gh",
            "pr",
            "checks",
            str(pr_number),
            "--repo",
            self._repo,
            "--json",
            "name,state",
            dry_run_return=[],
            dry_run_log=f"[dry-run] Would fetch CI checks for PR #{pr_number}",
            error_log=f"Could not fetch CI checks for PR #{pr_number}",
        )

    async def _get_failed_check_runs(self, pr_number: int) -> list[tuple[str, str]]:
        """Return [(name, run_id), ...] for failed CI checks on this PR.

        #8786 Phase 13: routed through the contracts boundary helper in
        lenient mode against ``GhCheckRun``. The helper logs WARN on
        shape drift (e.g. a new check state enum value, a renamed URL
        field) and falls back to the raw dict so the existing downstream
        processing keeps working.

        #10510: the ``gh pr checks --json`` URL field is ``link`` — the
        older ``detailsUrl`` name was removed and requesting it makes the
        whole call fail (``Unknown JSON field: "detailsUrl"``), so every
        poll 3x-retried and returned no failed runs.
        """
        from contracts.boundary import field_or, parse_list_with_shape  # noqa: PLC0415
        from contracts.shapes import GhCheckRun  # noqa: PLC0415

        raw = await self._run_gh(
            "gh",
            "pr",
            "checks",
            str(pr_number),
            "--repo",
            self._repo,
            "--json",
            "name,state,link",
        )
        results = parse_list_with_shape(raw, GhCheckRun)

        seen_run_ids: set[str] = set()
        failed_names: list[tuple[str, str]] = []
        for r in results:
            name = str(field_or(r, "name", "unknown"))
            state = str(field_or(r, "state", "")).upper()
            details_url = str(field_or(r, "details_url", "", dict_key="link"))
            if state in self._PASSING_STATES or state in self._PENDING_STATES:
                continue
            if not details_url:
                continue
            match = self._RUN_ID_PATTERN.search(details_url)
            if not match:
                continue
            run_id = match.group(1)
            if run_id not in seen_run_ids:
                seen_run_ids.add(run_id)
                failed_names.append((name or "unknown", run_id))
        return failed_names

    async def _fetch_run_log(self, name: str, run_id: str) -> str:
        """Fetch the --log-failed output for one run, or '' on error."""
        try:
            log_output = await self._run_gh(
                "gh",
                "run",
                "view",
                run_id,
                "--repo",
                self._repo,
                "--log-failed",
            )
            if log_output.strip():
                return f"### {name} (run {run_id})\n\n{log_output}"
        except RuntimeError as exc:
            logger.debug("Could not fetch log for run %s: %s", run_id, exc)
        return ""

    async def fetch_ci_failure_logs(self, pr_number: int) -> str:
        """Fetch full CI failure logs for *pr_number*.

        Queries check runs, extracts run IDs from failed checks, and
        fetches their ``--log-failed`` output.  Returns the concatenated
        log text (one section per failed check) or an empty string on
        error or in dry-run mode.
        """
        if self._config.dry_run:
            return ""

        try:
            failed_runs = await self._get_failed_check_runs(pr_number)
        except (RuntimeError, json.JSONDecodeError) as exc:
            logger.warning("Could not fetch CI checks for PR #%d: %s", pr_number, exc)
            return ""

        if not failed_runs:
            return ""

        sections = [
            log
            for name, run_id in failed_runs
            if (log := await self._fetch_run_log(name, run_id))
        ]
        return "\n\n".join(sections)

    async def fetch_code_scanning_alerts(self, branch: str) -> list[CodeScanningAlert]:
        """Fetch open code scanning alerts for *branch*.

        Uses the GitHub code-scanning API via ``gh api``.  Returns a list
        of :class:`CodeScanningAlert` instances (projected to key fields)
        or ``[]`` on error, 404, or when the repository has no code
        scanning configured.
        """
        if self._config.dry_run:
            return []

        jq_expr = (
            "[.[] | {number, rule: .rule.description, "
            "severity: .rule.severity, "
            "security_severity: .rule.security_severity_level, "
            "path: .most_recent_instance.location.path, "
            "start_line: .most_recent_instance.location.start_line, "
            "message: .most_recent_instance.message.text}]"
        )
        try:
            stdout = await run_subprocess(
                "gh",
                "api",
                f"repos/{self._config.repo}/code-scanning/alerts",
                "--field",
                f"ref={branch}",
                "--field",
                "state=open",
                "--field",
                "per_page=50",
                "--jq",
                jq_expr,
                timeout=30,
            )
            raw = json.loads(stdout) if stdout.strip() else []
            return [CodeScanningAlert.model_validate(a) for a in raw]
        except (RuntimeError, json.JSONDecodeError, ValueError):
            logger.debug(
                "Could not fetch code scanning alerts for branch %s",
                branch,
                exc_info=True,
            )
            return []

    def _evaluate_ci_checks(
        self, checks: list[dict[str, Any]], pr_number: int
    ) -> tuple[bool, str] | None:
        """Evaluate completed CI checks.

        Returns ``(passed, message)`` if all checks have finished,
        or ``None`` if any check is still pending.
        """
        pending = [
            c for c in checks if c.get("state", "").upper() in self._PENDING_STATES
        ]
        if pending:
            return None

        failed = [
            c["name"]
            for c in checks
            if c.get("state", "").upper() not in self._PASSING_STATES
        ]
        if failed:
            return False, f"Failed checks: {', '.join(str(n) for n in failed)}"
        return True, f"All {len(checks)} checks passed"

    async def _advisory_failures_only(self, pr_number: int) -> bool:
        """Return True if only advisory (non-required) checks are non-passing.

        ``_evaluate_ci_checks`` counts *every* non-passing check as a failure,
        but a check that is not in the base branch's required-status-check set
        must not block the merge — GitHub already allows it. Rather than parse
        the base branch's ruleset (``main`` uses a ruleset, not classic branch
        protection), we consult GitHub's own verdict: when all *required*
        checks pass and only advisory checks fail, GitHub reports
        ``mergeable=MERGEABLE`` with ``mergeStateStatus=UNSTABLE``. Any other
        state — or an unreadable response — returns False (fail-closed) so a
        real required-check failure never merges by accident. See #9910.
        """
        if self._config.dry_run:
            return False
        try:
            raw = await self._run_gh(
                "gh",
                "pr",
                "view",
                str(pr_number),
                "--repo",
                self._repo,
                "--json",
                "mergeable,mergeStateStatus",
            )
        # Fail-closed: any probe error keeps the failure verdict.
        except Exception:
            logger.debug(
                "Could not fetch merge-state for PR #%d (advisory-check gate)",
                pr_number,
                exc_info=True,
            )
            return False
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return False
        mergeable = str(data.get("mergeable", "")).upper()
        merge_state = str(data.get("mergeStateStatus", "")).upper()
        return mergeable == "MERGEABLE" and merge_state in {
            "CLEAN",
            "UNSTABLE",
            "HAS_HOOKS",
        }

    async def wait_for_ci(
        self,
        pr_number: int,
        timeout: int,
        poll_interval: int,
        stop_event: asyncio.Event,
    ) -> tuple[bool, str]:
        """Poll CI checks until all complete or *timeout* seconds elapse.

        Returns ``(passed, summary_message)``.
        """
        if self._config.dry_run:
            logger.info("[dry-run] Would wait for CI on PR #%d", pr_number)
            return True, "Dry-run: CI skipped"

        elapsed = 0
        while elapsed < timeout:
            if stop_event.is_set():
                return False, ci_sentinels.CI_STOPPED

            checks = await self.get_pr_checks(pr_number)

            if not checks:
                # No checks registered yet. For freshly-opened PRs (e.g.
                # RC promotion PRs cut by StagingPromotionLoop), CI may
                # not have registered any checks in the rollup until a
                # few seconds after the PR opens. The legacy behavior
                # ("treat empty as success") raced with the merge
                # attempt: wait_for_ci would return True immediately,
                # the loop would attempt merge, and GitHub would reject
                # because required checks weren't satisfied. Fix: treat
                # empty as PENDING — keep polling until checks appear or
                # timeout. The caller's "timed out" / "ci_pending" path
                # retries on the next loop tick.
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=poll_interval)
                    return False, ci_sentinels.CI_STOPPED
                except TimeoutError:
                    elapsed += poll_interval
                    continue

            verdict = self._evaluate_ci_checks(checks, pr_number)
            if verdict is None:
                # Still pending — publish event and wait
                pending_count = sum(
                    1
                    for c in checks
                    if c.get("state", "").upper() in self._PENDING_STATES
                )
                await self._bus.publish(
                    HydraFlowEvent(
                        type=EventType.CI_CHECK,
                        data=CICheckPayload(
                            pr=pr_number,
                            status="pending",
                            pending=pending_count,
                            total=len(checks),
                        ),
                    )
                )
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=poll_interval)
                    return False, ci_sentinels.CI_STOPPED
                except TimeoutError:
                    elapsed += poll_interval
                    continue

            passed, msg = verdict
            if not passed and await self._advisory_failures_only(pr_number):
                advisory = [
                    c["name"]
                    for c in checks
                    if c.get("state", "").upper() not in self._PASSING_STATES
                ]
                logger.info(
                    "PR #%d: all required checks satisfied; %d advisory "
                    "check(s) failing but non-blocking "
                    "(mergeStateStatus=UNSTABLE): %s",
                    pr_number,
                    len(advisory),
                    ", ".join(advisory),
                )
                passed, msg = (
                    True,
                    f"Required checks passed; advisory failing: {', '.join(advisory)}",
                )
            data: CICheckPayload = CICheckPayload(
                pr=pr_number,
                status="passed" if passed else "failed",
            )
            if not passed:
                # Extract failed names from the message for the event
                data["failed"] = [
                    c["name"]
                    for c in checks
                    if c.get("state", "").upper() not in self._PASSING_STATES
                ]
            else:
                data["total"] = len(checks)
            await self._bus.publish(HydraFlowEvent(type=EventType.CI_CHECK, data=data))
            return passed, msg

        return False, ci_sentinels.ci_timeout(timeout)

    async def refresh_pr_branch_with_arch_regen(
        self, pr_number: int, branch: str
    ) -> bool:
        """Self-heal a bot PR stuck red on stale ``docs/arch/generated/``.

        Merges ``origin/<base>`` into the PR head in an ephemeral worktree,
        re-runs ``arch.runner --emit`` to repair the staleness (or resolve an
        arch-generated-only merge conflict), commits, and pushes — re-triggering
        CI. Returns True only when a refresh commit was actually pushed; returns
        False for a clean no-op, a real (non-generated) conflict, or any git/gh
        failure, so the caller falls through to its ``failure_strategy``.

        Never force-pushes (the pre-push hook blocks it); a merge commit
        fast-forwards the remote head and squash-merge collapses it.
        """
        if self._config.dry_run:
            logger.info(
                "[dry-run] Would arch-refresh bot PR #%d on branch %s",
                pr_number,
                branch,
            )
            return False

        from auto_pr import refresh_branch_with_arch_regen  # noqa: PLC0415

        result = await refresh_branch_with_arch_regen(
            repo_root=self._config.repo_root,
            branch=branch,
            base=self._config.base_branch(),
            gh_token=self._credentials.gh_token,
            worktree_parent=self._config.workspace_base,
            commit_author_name=self._config.git_user_name,
            commit_author_email=self._config.git_user_email,
        )
        if result.status == "refreshed":
            logger.info(
                "Arch-refreshed bot PR #%d (%s) — merged base + regenerated "
                "artifacts; CI will re-run",
                pr_number,
                branch,
            )
            return True
        logger.info(
            "Arch-refresh of bot PR #%d (%s) did not push (%s)%s",
            pr_number,
            branch,
            result.status,
            f": {result.error}" if result.error else "",
        )
        return False
