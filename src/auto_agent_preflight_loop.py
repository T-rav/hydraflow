"""AutoAgentPreflightLoop — intercepts hitl-escalation issues for auto-resolution.

Spec §1–§11. Polls hitl-escalation items, runs PreflightAgent in attempt
sequence, applies PreflightDecision to the result, records audit + spend.

Layered kill-switch (ADR-0049): in-body enabled_cb gate at top of _do_work.
Sequential single-issue-per-tick. Daily-budget gate. Sub-label deny-list.

#9721 widened intake (gated by ``auto_agent_hitl_intake_enabled``): the loop
also intercepts idle, pipeline-origin ``hydraflow-hitl`` issues — the
attempt-cap exhaustion and quality-gate/zero-diff bails that previously went
straight to a human. Eligible issues are claimed by swapping to the
``hydraflow-hitl-autofix`` label BEFORE any spawn, which removes them from
the human queue (built from hitl + hitl-active only) so the widened attempt
can never race ``HITLPhase``. Issues carrying ``hydraflow-hitl-active`` or
``human-required`` are never intercepted; ``operator-abort`` parks stay
human-owned.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
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
        epic_manager: Any | None = None,
        runner: Any | None = None,
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

        # ADR-0105 decompose-to-converge: both are optional so the loop keeps
        # working (falling straight through to today's human-required
        # terminal) for callers that haven't threaded epic_manager/runner
        # through yet — e.g. existing test fixtures predating this feature.
        self._decomposer: Any | None = None
        self._council: Any | None = None
        if epic_manager is not None:
            from issue_decomposer import IssueDecomposer  # noqa: PLC0415

            self._decomposer = IssueDecomposer(pr_manager, epic_manager, state, config)
        if runner is not None:
            from decomposition_council import DecompositionCouncil  # noqa: PLC0415

            self._council = DecompositionCouncil(runner, config)

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

        # Escalation TTL re-drive (#9719). Placed after the daily-budget gate
        # so a budget-stopped day never spends via freshly re-driven retries.
        redriven = await self._redrive_stuck_escalations()
        if redriven:
            logger.info("Auto-agent re-drove %d stuck escalation(s)", redriven)

        # Poll for hitl-escalation issues that don't already have human-required.
        issues = await self._poll_eligible_issues()
        if not issues:
            return {"status": "ok", "issues_processed": 0}

        # #10260: an issue already resolved by an open, CI-green PR must not
        # re-enter a new attempt — LabelDriftWatcherLoop clears the stale
        # escalation labels asynchronously, but this guard makes the
        # dispatch loop itself immune to the lag before that reconciliation
        # runs.
        issue, suppressed = await self._select_dispatchable_issue(issues)
        if issue is None:
            return {"status": "ok", "issues_processed": 0, "suppressed": suppressed}

        # Sequential single-issue-per-tick.
        result = await self._process_one(issue)
        return {
            "status": "ok",
            "issues_processed": 1,
            "result_status": result.get("status"),
            "suppressed": suppressed,
        }

    async def _select_dispatchable_issue(
        self, issues: list[dict[str, Any]]
    ) -> tuple[dict[str, Any] | None, int]:
        """Return the first issue not already resolved by an open, CI-green PR.

        Returns ``(issue_or_None, suppressed_count)``. Scans in poll order so
        the single-issue-per-tick pick still respects the eligible list's
        ordering.
        """
        suppressed = 0
        for issue in issues:
            issue_number = int(issue.get("number", 0))
            if await self._is_resolved_by_open_pr(issue_number):
                suppressed += 1
                continue
            return issue, suppressed
        return None, suppressed

    async def _is_resolved_by_open_pr(self, issue_number: int) -> bool:
        """True when an OPEN PR already resolves *issue_number* with every
        CI check green (#10260). Any lookup failure — including an
        unconfigured test double returning something other than the
        declared int/list shape — degrades to False: never suppress a real
        dispatch on uncertain data."""
        try:
            pr_number = await self._prs.find_open_resolving_pr(issue_number)
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.debug(
                "Auto-agent: resolving-PR lookup failed for #%d: %s",
                issue_number,
                exc,
            )
            return False
        if not isinstance(pr_number, int) or pr_number <= 0:
            return False
        try:
            checks = await self._prs.get_pr_checks(pr_number)
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.debug(
                "Auto-agent: CI-check lookup failed for PR #%d (issue #%d): %s",
                pr_number,
                issue_number,
                exc,
            )
            return False
        if not isinstance(checks, list) or not checks:
            return False
        return all(
            isinstance(c, dict) and c.get("state", "").upper() in _PASSING_CI_STATES
            for c in checks
        )

    async def _reconcile_closed_issues(self) -> int:
        """Clear auto_agent_attempts for issues that have been closed.

        Polls the last 200 closed issues per intake label and drops attempt
        counts so a re-open starts fresh. #9721: when the widened intake is
        enabled, closed ``hydraflow-hitl-autofix`` (claimed mid-attempt) and
        ``hydraflow-hitl`` (returned to the queue, then human-closed) issues
        are reconciled too — otherwise their attempt counters leak forever.
        """
        labels = ["hitl-escalation"]
        if self._config.auto_agent_hitl_intake_enabled:
            labels.append(self._config.hitl_autofix_label[0])
            labels.append(self._config.hitl_label[0])
        cleared = 0
        seen: set[int] = set()
        for label in dict.fromkeys(labels):
            try:
                closed = await self._prs.list_closed_issues_by_label(
                    label,
                    limit=200,
                )
            except Exception as exc:
                logger.warning(
                    "Auto-agent close-reconciliation poll failed for %r: %s",
                    label,
                    exc,
                )
                continue
            for issue in closed:
                issue_number = int(issue.get("number", 0))
                if issue_number in seen:
                    continue
                seen.add(issue_number)
                if self._state.get_auto_agent_attempts(issue_number) > 0:
                    self._state.clear_auto_agent_attempts(issue_number)
                    cleared += 1
                # #9719: also drop any re-drive marker so a re-open starts
                # fresh (no-op when no marker exists).
                self._state.clear_auto_agent_redrive(issue_number)
        return cleared

    async def _redrive_stuck_escalations(self) -> int:
        """Re-feed still-real stuck escalations to preflight after a TTL (#9719).

        Candidate discovery is state-marker-driven (armed re-drive markers),
        never label-projection-driven; the "still stuck" / "human-claimed"
        cross-checks use per-label polls, which yield issue NUMBERS reliably
        regardless of whether summaries carry a ``labels`` field. Returns the
        number of issues re-driven this tick (bounded by the batch cap).
        """
        if not self._config.auto_agent_redrive_enabled:
            return 0
        armed = self._state.list_armed_auto_agent_redrives()
        if not armed:
            return 0
        try:
            still_stuck = {
                int(issue.get("number", 0))
                for issue in await self._prs.list_issues_by_label("human-required")
            }
            claimed: set[int] = set()
            for label in self._config.hitl_active_label:
                claimed |= {
                    int(issue.get("number", 0))
                    for issue in await self._prs.list_issues_by_label(label)
                }
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning("Auto-agent re-drive poll failed: %s", exc)
            return 0

        now = datetime.now(UTC)
        redriven = 0
        for issue_number, exhausted_at, count in armed:
            if redriven >= _REDRIVE_BATCH_CAP:
                break
            if issue_number not in still_stuck:
                # Resolved-but-not-closed: human-required is already gone, so
                # the marker is stale — drop it rather than re-drive.
                self._state.clear_auto_agent_redrive(issue_number)
                continue
            if count >= self._config.auto_agent_redrive_max_attempts:
                continue
            ttl_days = self._config.auto_agent_redrive_ttl_days * (
                self._config.auto_agent_redrive_backoff_multiplier**count
            )
            if _age_days(now, exhausted_at) < ttl_days:
                continue
            if issue_number in claimed:
                continue
            if await self._human_recently_active(issue_number, now):
                continue
            try:
                await self._do_redrive(issue_number, ttl_days)
            except Exception as exc:
                reraise_on_credit_or_bug(exc)
                logger.warning(
                    "Auto-agent re-drive failed for #%d: %s", issue_number, exc
                )
                continue
            redriven += 1
        return redriven

    async def _do_redrive(self, issue_number: int, ttl_days: float) -> None:
        """Perform one re-drive: reset state, strip labels, leave a directive.

        State-first ordering for count-safety: the re-drive count is bumped
        BEFORE any port write, so a partial failure can never exceed the
        re-drive budget (worst case: a counted re-drive whose labels survive
        until a later tick's attempt-cap branch re-arms the marker). The
        durable audit log is deliberately NOT cleared — ``gather_context``
        sources ``prior_attempts`` from it, so the retry sees the original
        failure summaries (the diverse-retry requirement).
        """
        new_count = self._state.record_auto_agent_redrive(issue_number)
        self._state.clear_auto_agent_attempts(issue_number)
        await self._prs.remove_label(issue_number, "human-required")
        await self._prs.remove_label(issue_number, "auto-agent-exhausted")
        await self._prs.post_comment(
            issue_number,
            _format_redrive_comment(
                ttl_days, new_count, self._config.auto_agent_redrive_max_attempts
            ),
        )
        self._audit_store.append(
            _redrive_audit(issue_number, new_count, repo=self._config.repo_slug)
        )
        logger.info(
            "Auto-agent re-drove stuck escalation #%d (re-drive %d)",
            issue_number,
            new_count,
        )

    async def _human_recently_active(self, issue_number: int, now: datetime) -> bool:
        """True when an authorized human commented within the quiet window.

        Empty allowlist → False immediately: the hitl-active label is the
        authoritative claim signal, and the loop's own bot comments must
        never read as human activity. Comment-poll failures return True —
        fail-safe: never yank an issue we can't inspect.
        """
        authorized = set(self._config.human_steering_authorized_users)
        if not authorized:
            return False
        try:
            comments = await self._prs.list_issue_comments(issue_number)
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning(
                "Auto-agent re-drive comment poll failed for #%d: %s",
                issue_number,
                exc,
            )
            return True
        quiet = timedelta(days=self._config.auto_agent_redrive_human_quiet_days)
        for comment in comments:
            login = str(comment.get("user", {}).get("login", ""))
            if login not in authorized:
                continue
            created = str(comment.get("created_at", ""))
            try:
                ts = datetime.fromisoformat(created.replace("Z", "+00:00"))
            except ValueError:
                # Unparseable timestamp on a human comment → assume recent.
                return True
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            if now - ts <= quiet:
                return True
        return False

    async def _poll_eligible_issues(self) -> list[dict[str, Any]]:
        """Return open hitl-escalation issues lacking human-required, plus —
        when ``auto_agent_hitl_intake_enabled`` — idle ``hydraflow-hitl``
        issues tagged with ``_intake='hitl_widened'`` (#9721)."""
        eligible: list[dict[str, Any]] = []
        seen: set[int] = set()
        try:
            raw = await self._prs.list_issues_by_label("hitl-escalation")
        except Exception as exc:
            logger.warning("Eligible-issue poll failed: %s", exc)
            raw = []
        for issue in raw:
            names = {lbl.get("name", "") for lbl in issue.get("labels", [])}
            if "human-required" in names:
                continue
            eligible.append(issue)
            seen.add(int(issue.get("number", 0)))
        if self._config.auto_agent_hitl_intake_enabled:
            eligible.extend(await self._poll_widened_hitl_issues(seen))
        return eligible

    async def _poll_widened_hitl_issues(self, seen: set[int]) -> list[dict[str, Any]]:
        """#9721: poll idle pipeline-origin ``hydraflow-hitl`` issues.

        Also polls the ``hydraflow-hitl-autofix`` claim label so an attempt
        interrupted mid-claim (crash, restart) is re-attempted — bounded by
        the shared attempt cap — rather than orphaned outside both queues.

        Race guards (never contend with a human or ``HITLPhase``): issues
        carrying ``human-required`` or any ``hitl_active_label`` are skipped;
        dual-labelled ``hitl-escalation`` issues are owned by the escalation
        branch; ``operator-abort`` parks are human-owned by definition.
        """
        cfg = self._config
        active = set(cfg.hitl_active_label)
        widened: list[dict[str, Any]] = []
        for label in dict.fromkeys((cfg.hitl_label[0], cfg.hitl_autofix_label[0])):
            try:
                raw = await self._prs.list_issues_by_label(label)
            except Exception as exc:
                logger.warning("Widened HITL intake poll failed for %r: %s", label, exc)
                continue
            for issue in raw:
                number = int(issue.get("number", 0))
                if number <= 0 or number in seen:
                    continue
                names = {lbl.get("name", "") for lbl in issue.get("labels", [])}
                if "human-required" in names:
                    continue
                if names & active:
                    continue
                if "hitl-escalation" in names:
                    continue
                if self._state.get_hitl_origin(number) == "operator-abort":
                    continue
                seen.add(number)
                widened.append({**issue, "_intake": "hitl_widened"})
        return widened

    def _playbook_stem_for_origin(self, origin: str | None) -> str:
        """#9721: route a widened issue to a specialist playbook by its
        recorded ``hitl_origin`` (the pipeline label ``escalate_to_hitl``
        stored — the sub-label lives in state, not on the issue).

        ``ready_label`` origins are ImplementPhase escalations (attempt cap,
        quality gate, zero diff) → the cap-exhausted specialist. Plan/review
        origins reuse the existing specialists. Unknown or absent origins
        (including ``operator-abort``, excluded at poll anyway) fall back to
        ``_default``.
        """
        if not origin:
            return "_default"
        cfg = self._config
        if origin in cfg.ready_label:
            return "implement-cap-exhausted"
        if origin in cfg.planner_label:
            return "plan-stuck"
        if origin in cfg.review_label:
            return "review-stuck"
        return "_default"

    async def _return_widened_claim(self, issue_number: int, labels: set[str]) -> None:
        """#9721: if the issue still carries the autofix claim label, return
        it to the human queue so a deny-list/exhaustion verdict never leaves
        it orphaned outside both the human queue and the widened poll."""
        if labels & set(self._config.hitl_autofix_label):
            await self._prs.swap_pipeline_labels(
                issue_number, self._config.hitl_label[0]
            )

    async def _process_one(self, issue: dict[str, Any]) -> dict[str, Any]:
        """Run one full pre-flight attempt for a single issue."""
        from preflight.agent import PreflightAgentDeps, run_preflight
        from preflight.audit import PreflightAuditEntry
        from preflight.context import gather_context
        from preflight.decision import apply_decision
        from preflight.decompose_terminal import decompose_or_escalate

        issue_number = int(issue.get("number", 0))
        issue_body = str(issue.get("body", "") or "")
        labels = {lbl.get("name", "") for lbl in issue.get("labels", [])}
        widened = str(issue.get("_intake", "")) == "hitl_widened"
        origin: str | None = None
        # Deterministic sub-label selection — set iteration is hash-randomised
        # in CPython, so an issue with multiple sub-labels would otherwise pick
        # a random playbook each tick (and randomly skip the deny-list). Sort
        # alphabetically so the same issue always routes to the same playbook.
        if widened:
            # #9721: a widened issue carries no escalation sub-label — the
            # routing key lives in state (hitl_origin). Its remaining labels
            # (minus the hitl family) still feed the deny-list below.
            hitl_family = (
                set(self._config.hitl_label)
                | set(self._config.hitl_active_label)
                | set(self._config.hitl_autofix_label)
            )
            sub_labels = sorted(labels - {"hitl-escalation"} - hitl_family)
            origin = self._state.get_hitl_origin(issue_number)
            sub_label = self._playbook_stem_for_origin(origin)
        else:
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
            if widened:
                await self._return_widened_claim(issue_number, labels)
            await self._prs.add_labels(issue_number, ["human-required"])
            self._audit_store.append(
                _skip_audit(
                    issue_number, denied, "deny_list", repo=self._config.repo_slug
                )
            )
            return {"status": "skipped_deny_list"}

        # Attempt-cap check. ADR-0105: before paging a human, try decomposing
        # the issue — a change that's merely too big/ambiguous to converge as
        # one unit shouldn't escalate, it should split. Only wired when both
        # epic_manager and runner were injected at construction; otherwise
        # this falls straight through to today's behavior.
        attempts = self._state.get_auto_agent_attempts(issue_number)
        if attempts >= self._config.auto_agent_max_attempts:
            outcome = "human-required"
            if self._decomposer is not None and self._council is not None:
                ctx = await gather_context(
                    issue_number=issue_number,
                    issue_body=issue_body,
                    sub_label=sub_label,
                    pr_port=self._prs,
                    wiki_store=self._wiki_store,
                    state=self._state,
                    audit_store=self._audit_store,
                    repo_slug="",
                    config=self._config,
                    issue_labels=sorted(labels),
                )
                outcome = await decompose_or_escalate(
                    issue_number=issue_number,
                    ctx=ctx,
                    config=self._config,
                    decomposer=self._decomposer,
                    council=self._council,
                    state=self._state,
                    prs=self._prs,
                )
            if outcome == "human-required":
                if widened:
                    await self._return_widened_claim(issue_number, labels)
                await self._prs.add_labels(
                    issue_number, ["human-required", "auto-agent-exhausted"]
                )
                # #9719: arm the TTL re-drive marker. Idempotent — a re-poll
                # of an already-exhausted issue must not refresh its clock.
                self._state.arm_auto_agent_redrive(issue_number, _now_iso())
                return {"status": "skipped_exhausted"}
            return {"status": "skipped_decomposed"}

        # #9721: claim the widened issue BEFORE gathering context / spawning.
        # The swap to the autofix label removes it from the human queue (built
        # from hitl + hitl-active only), so the attempt can never race
        # HITLPhase. Idempotent — re-claiming an already-claimed issue (crash
        # recovery via the autofix poll) is a no-op label-wise.
        if widened:
            await self._prs.swap_pipeline_labels(
                issue_number, self._config.hitl_autofix_label[0]
            )

        # Gather context. config + issue_labels feed the CH-6 data-governance
        # gate: regulated-class repos get their gathered free text redacted
        # before it enters any prompt (structured no-op otherwise).
        ctx = await gather_context(
            issue_number=issue_number,
            issue_body=issue_body,
            sub_label=sub_label,
            pr_port=self._prs,
            wiki_store=self._wiki_store,
            state=self._state,
            audit_store=self._audit_store,
            repo_slug="",
            config=self._config,
            issue_labels=sorted(labels),
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

        # Apply decision. ADR-0105: decomposer/council may be None (not
        # wired for this caller) — apply_decision degrades to today's
        # behavior in that case.
        decision = await apply_decision(
            issue_number=issue_number,
            sub_label=sub_label,
            result=result,
            pr_port=self._prs,
            state=self._state,
            max_attempts=self._config.auto_agent_max_attempts,
            decomposer=self._decomposer,
            council=self._council,
            config=self._config,
            ctx=ctx,
            hitl_widened=widened,
            origin_label=origin,
        )

        # #9719: the attempt that hits the cap arms the TTL re-drive marker.
        # Decomposed issues are already closed/superseded — nothing to
        # re-drive. Arming is idempotent (state guard preserves the first
        # exhaustion timestamp).
        if decision.get("exhausted") and not decision.get("decomposed"):
            self._state.arm_auto_agent_redrive(issue_number, _now_iso())

        # A *resolved* diagnose-failed issue (routed here from the diagnostic
        # loop, ADR-0084) must re-enter review rather than linger in the HITL
        # queue: the Auto-Agent pushed its fix to the existing PR branch, so
        # swap it back to review for a fresh pass. Widened issues are exempt:
        # apply_decision already routed them to their origin stage.
        if (
            not widened
            and result.status == "resolved"
            and "diagnose-failed" in sub_labels
        ):
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


# Per-tick cap on re-drives (#9719) — a burst of markers aging past the TTL
# together must not flood the eligible pool; the scan re-runs every tick, so
# the remainder drains over subsequent ticks.
_REDRIVE_BATCH_CAP = 3

# CI check states that count as a green verdict (#10260) — mirrors
# PRManager._PASSING_STATES.
_PASSING_CI_STATES = frozenset({"SUCCESS", "NEUTRAL", "SKIPPED"})


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _age_days(now: datetime, iso_ts: str) -> float:
    """Age in days of *iso_ts* relative to *now*.

    Malformed/empty timestamps return 0.0 — an unknown age must read as
    "not aged yet" so a corrupt marker can never trigger a re-drive.
    """
    try:
        then = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if then.tzinfo is None:
        then = then.replace(tzinfo=UTC)
    return (now - then).total_seconds() / 86400.0


def _format_redrive_comment(
    ttl_days: float, redrive_count: int, max_redrives: int
) -> str:
    """The re-drive directive — read back by the NEXT attempt.

    ``gather_context`` includes the last 10 issue comments in the retry
    prompt, so this comment doubles as the diverse-retry instruction: prior
    attempts failed and their summaries are already in ``prior_attempts``.
    """
    return (
        f"**Auto-Agent re-drive {redrive_count}/{max_redrives}** — this "
        f"escalation carried `human-required` for over {ttl_days:.0f} day(s) "
        "with no human claim, so it is being re-fed to auto-agent preflight "
        "(#9719): labels cleared, attempt budget reset.\n\n"
        "The codebase has moved since the original attempts and blocking "
        "dependencies may have unblocked. The prior attempts FAILED — their "
        "summaries appear above and in the audit history. Take a genuinely "
        "different approach; do not repeat a failed strategy."
    )


def _redrive_audit(issue: int, redrive_count: int, repo: str = ""):
    from preflight.audit import PreflightAuditEntry

    return PreflightAuditEntry(
        ts=_now_iso(),
        issue=issue,
        sub_label="_redrive",
        attempt_n=0,
        prompt_hash="",
        cost_usd=0.0,
        wall_clock_s=0.0,
        tokens=0,
        status="redrive",
        pr_url=None,
        diagnosis=(
            f"redrive: TTL re-drive #{redrive_count} — human-required + "
            "auto-agent-exhausted removed, attempt counter cleared "
            "(audit log preserved)"
        ),
        llm_summary=f"redrive: TTL re-drive #{redrive_count}",
        repo=repo,
    )


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
