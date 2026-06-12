"""AutoAgentPreflightLoop — intercepts hitl-escalation issues for auto-resolution.

Spec §1–§11. Polls hitl-escalation items, runs PreflightAgent in attempt
sequence, applies PreflightDecision to the result, records audit + spend.

Layered kill-switch (ADR-0049): in-body enabled_cb gate at top of _do_work.
Sequential single-issue-per-tick. Daily-budget gate. Sub-label deny-list.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from exception_classify import reraise_on_credit_or_bug
from subprocess_util import CreditExhaustedError

logger = logging.getLogger("hydraflow.auto_agent_preflight")


class AutoAgentPreflightLoop(BaseBackgroundLoop):
    """Intercepts hitl-escalation issues for auto-agent pre-flight."""

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        state: Any,
        pr_manager: Any,
        wiki_store: Any | None,
        audit_store: Any,
        deps: LoopDeps,
        workspaces: Any | None = None,
    ) -> None:
        super().__init__(
            worker_name="auto_agent_preflight",
            config=config,
            deps=deps,
            run_on_startup=False,
        )
        self._state = state
        self._prs = pr_manager
        self._wiki_store = wiki_store
        self._audit_store = audit_store
        self._workspaces = workspaces

    def _get_default_interval(self) -> int:
        return self._config.auto_agent_preflight_interval

    async def _do_work(self) -> dict[str, Any] | None:
        # ADR-0049 in-body kill-switch gate (universal mandate).
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}

        # Static config gate (defense-in-depth: operator can disable at deploy
        # time via HYDRAFLOW_AUTO_AGENT_PREFLIGHT_ENABLED=false even when the
        # UI toggle is unavailable).
        if not self._config.auto_agent_preflight_enabled:
            return {"status": "config_disabled"}

        cap = self._config.auto_agent_daily_budget_usd
        if cap is not None:
            today = datetime.now(UTC).date().isoformat()
            # Use the durable audit log as a floor for today's spend. The state
            # cache (add_auto_agent_daily_spend) is updated only AFTER the costly
            # run_preflight returns, so a crash in between loses the increment and
            # the gate would undercount → overspend past the cap. The audit entry
            # is appended BEFORE that cache update, so it never loses a completed
            # attempt; max() tolerates either being momentarily ahead.
            spend = max(
                self._state.get_auto_agent_daily_spend(today),
                self._audit_store.daily_spend(today),
            )
            if spend >= cap:
                return {"status": "budget_exceeded", "spend_usd": spend, "cap_usd": cap}

        cleared = await self._reconcile_closed_issues()
        if cleared:
            logger.info("Auto-agent reconciled %d closed issues", cleared)

        # Poll for hitl-escalation issues that don't already have human-required.
        issues = await self._poll_eligible_issues()
        if not issues:
            return {"status": "ok", "issues_processed": 0}

        # Sequential single-issue-per-tick.
        issue = issues[0]
        result = await self._process_one(issue)
        return {
            "status": "ok",
            "issues_processed": 1,
            "result_status": result.get("status"),
        }

    async def _reconcile_closed_issues(self) -> int:
        """Clear auto_agent_attempts for issues that have been closed.

        Polls the last 200 closed issues with hitl-escalation label and drops
        attempt counts so a re-open starts fresh.
        """
        try:
            closed = await self._prs.list_closed_issues_by_label(
                "hitl-escalation",
                limit=200,
            )
        except Exception as exc:
            logger.warning("Auto-agent close-reconciliation poll failed: %s", exc)
            return 0
        cleared = 0
        for issue in closed:
            issue_number = int(issue.get("number", 0))
            if self._state.get_auto_agent_attempts(issue_number) > 0:
                self._state.clear_auto_agent_attempts(issue_number)
                cleared += 1
        return cleared

    async def _poll_eligible_issues(self) -> list[dict[str, Any]]:
        """Return open hitl-escalation issues lacking human-required."""
        try:
            raw = await self._prs.list_issues_by_label("hitl-escalation")
        except Exception as exc:
            logger.warning("Eligible-issue poll failed: %s", exc)
            return []
        return [
            issue
            for issue in raw
            if "human-required"
            not in {lbl.get("name", "") for lbl in issue.get("labels", [])}
        ]

    async def _process_one(self, issue: dict[str, Any]) -> dict[str, Any]:
        """Run one full pre-flight attempt for a single issue."""
        from preflight.agent import PreflightAgentDeps, run_preflight
        from preflight.audit import PreflightAuditEntry
        from preflight.context import gather_context
        from preflight.decision import apply_decision

        issue_number = int(issue.get("number", 0))
        issue_body = str(issue.get("body", "") or "")
        labels = {lbl.get("name", "") for lbl in issue.get("labels", [])}
        # Deterministic sub-label selection — set iteration is hash-randomised
        # in CPython, so an issue with multiple sub-labels would otherwise pick
        # a random playbook each tick (and randomly skip the deny-list). Sort
        # alphabetically so the same issue always routes to the same playbook.
        sub_labels = sorted(labels - {"hitl-escalation"})
        sub_label = sub_labels[0] if sub_labels else "_default"

        # Sub-label deny-list (recursion safety, dark-factory §2.7). The real gap:
        # producers file the deny-listed label ALONGSIDE others — e.g.
        # principles_audit_loop files ["principles-stuck", "check-<id>"], and
        # "check-<id>" sorts first, so the old sub_labels[0]-only check missed the
        # deny-listed label and the auto-agent acted on a principles escalation it
        # must defer to a human. Check EVERY sub-label. removeprefix is defensive
        # for the config-default labels that carry the `hydraflow-` prefix (the
        # skip-list is unprefixed); it's a no-op for the unprefixed producers.
        denied = next(
            (
                s
                for s in sub_labels
                if s.removeprefix("hydraflow-")
                in self._config.auto_agent_skip_sublabels
            ),
            None,
        )
        if denied is not None:
            await self._prs.add_labels(issue_number, ["human-required"])
            self._audit_store.append(
                _skip_audit(
                    issue_number, denied, "deny_list", repo=self._config.repo_slug
                )
            )
            return {"status": "skipped_deny_list"}

        # Attempt-cap check.
        attempts = self._state.get_auto_agent_attempts(issue_number)
        if attempts >= self._config.auto_agent_max_attempts:
            await self._prs.add_labels(
                issue_number, ["human-required", "auto-agent-exhausted"]
            )
            return {"status": "skipped_exhausted"}

        # Gather context.
        ctx = await gather_context(
            issue_number=issue_number,
            issue_body=issue_body,
            sub_label=sub_label,
            pr_port=self._prs,
            wiki_store=self._wiki_store,
            state=self._state,
            audit_store=self._audit_store,
            repo_slug="",
        )

        # Bump attempts atomically before spawning.
        attempt_n = self._state.bump_auto_agent_attempts(issue_number)

        # Spawn agent.
        spawn_fn = self._build_spawn_fn(issue_number)
        deps = PreflightAgentDeps(
            persona=self._config.auto_agent_persona,
            cost_cap_usd=self._config.auto_agent_cost_cap_usd,
            wall_clock_cap_s=self._config.auto_agent_wall_clock_cap_s,
            spawn_fn=spawn_fn,
        )
        worktree_path = await self._resolve_worktree(issue_number)
        try:
            result = await run_preflight(
                context=ctx,
                repo_slug="",
                worktree_path=worktree_path,
                deps=deps,
            )
        except CreditExhaustedError:
            # A credit/session limit aborted the spawn before any real work
            # happened. Refund the attempt bumped above so a transient outage
            # doesn't consume the issue's budget and wrongly exhaust it to
            # human-required across repeated outages — then re-raise to stop the
            # cycle per the dark-factory credit-stop contract. The issue stays
            # eligible and is retried when budget returns (ADR-0084 pillar B).
            self._state.refund_auto_agent_attempt(issue_number)
            raise

        # Apply decision.
        await apply_decision(
            issue_number=issue_number,
            sub_label=sub_label,
            result=result,
            pr_port=self._prs,
            state=self._state,
            max_attempts=self._config.auto_agent_max_attempts,
        )

        # A *resolved* diagnose-failed issue (routed here from the diagnostic
        # loop, ADR-0084) must re-enter review rather than linger in the HITL
        # queue: the Auto-Agent pushed its fix to the existing PR branch, so
        # swap it back to review for a fresh pass.
        if result.status == "resolved" and "diagnose-failed" in sub_labels:
            try:
                await self._prs.swap_pipeline_labels(
                    issue_number, self._config.review_label[0]
                )
            except Exception:
                logger.warning(
                    "Auto-agent: failed to route resolved diagnose-failed #%d "
                    "back to review",
                    issue_number,
                    exc_info=True,
                )

        # Append audit.
        self._audit_store.append(
            PreflightAuditEntry(
                ts=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                issue=issue_number,
                sub_label=sub_label,
                attempt_n=attempt_n,
                prompt_hash=result.prompt_hash,
                cost_usd=result.cost_usd,
                wall_clock_s=result.wall_clock_s,
                tokens=result.tokens,
                status=result.status,
                pr_url=result.pr_url,
                diagnosis=result.diagnosis,
                llm_summary=result.diagnosis[:500],
                repo=self._config.repo_slug,
            )
        )

        # Update daily spend cache.
        today = datetime.now(UTC).date().isoformat()
        self._state.add_auto_agent_daily_spend(today, result.cost_usd)

        return {"status": result.status, "issue": issue_number}

    def _build_spawn_fn(self, issue_number: int):
        """Returns the spawn callable that runs the auto-agent subprocess.

        Each call constructs a fresh `AutoAgentRunner` (lifetime bounded by
        the single attempt) so the runner's internal subprocess set doesn't
        leak across attempts. Tests monkeypatch this method to inject a
        cassette `PreflightSpawn` and skip the real subprocess.
        """
        from preflight.agent import PreflightSpawn
        from preflight.auto_agent_runner import AutoAgentRunner

        runner = AutoAgentRunner(config=self._config, event_bus=self._bus)

        async def _spawn(prompt: str, worktree_path: str) -> PreflightSpawn:
            return await runner.run(
                prompt=prompt,
                worktree_path=worktree_path,
                issue_number=issue_number,
            )

        return _spawn

    async def _resolve_worktree(self, issue_number: int) -> str:
        """Return the path to the per-issue worktree.

        Mirrors the diagnostic-loop pattern: use the conventional
        `workspace_path_for_issue` and create on demand if a `WorkspacePort`
        was injected and the path doesn't exist. Falls back to `repo_root`
        when no port is wired (test fixtures, dry-run mode).
        """
        if self._workspaces is None:
            return str(self._config.repo_root)
        wt_path = self._config.workspace_path_for_issue(issue_number)
        if wt_path.exists():
            return str(wt_path)
        branch = f"agent/auto-agent-{issue_number}"
        try:
            created = await self._workspaces.create(issue_number, branch)
            return str(created)
        except Exception as exc:
            # Credit-exhaustion / likely-bug signals must propagate, not be
            # swallowed by the broad guard (ADR-0049 / dark-factory mandate).
            reraise_on_credit_or_bug(exc)
            # Workspace creation can fail (concurrent worktree, branch
            # collision, disk pressure). Degrade to repo_root so the
            # agent still gets a valid cwd; the agent itself can handle
            # the lack of a per-issue branch by reporting needs_human.
            logger.warning(
                "auto-agent worktree creation failed for #%d: %s — "
                "falling back to repo_root",
                issue_number,
                exc,
            )
            return str(self._config.repo_root)


def _skip_audit(issue: int, sub_label: str, reason: str, repo: str = ""):
    from preflight.audit import PreflightAuditEntry

    return PreflightAuditEntry(
        ts=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        issue=issue,
        sub_label=sub_label,
        attempt_n=0,
        prompt_hash="",
        cost_usd=0.0,
        wall_clock_s=0.0,
        tokens=0,
        status="skipped",
        pr_url=None,
        diagnosis=f"skipped: {reason}",
        llm_summary=f"skipped: {reason}",
        repo=repo,
    )
