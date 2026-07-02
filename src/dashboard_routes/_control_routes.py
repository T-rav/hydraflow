"""Control route handlers extracted from _routes.py."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from admin_tasks import (
    run_clean,
    run_compact,
    run_ensure_labels,
    run_prep,
    run_scaffold,
)
from app_version import get_app_version
from config import HydraFlowConfig, save_config_file
from dashboard_routes._common import _INTERVAL_BOUNDS
from dashboard_routes._routes import RouteContext
from events import EventType, HydraFlowEvent
from models import (
    BackgroundWorkersResponse,
    BackgroundWorkerState,
    BackgroundWorkerStatus,
    BGWorkerHealth,
    ControlStatus,
    OrchestratorStatusPayload,
)
from prompt_telemetry import PromptTelemetry
from route_types import (
    REPO_ALL,
    ControlStatusConfig,
    ControlStatusResponse,
    RepoSlugParam,
)
from update_check import load_cached_update_result

if TYPE_CHECKING:
    from pr_manager import PRManager

logger = logging.getLogger("hydraflow.dashboard")


def _safe_error_message(exc: ValidationError) -> str:
    """Return a validation-style message without leaking stack trace details.

    Surfaces ``loc: msg`` per field — Pydantic designs those strings for
    end-users, so they're safe to return to the client. Closes the
    CodeQL ``py/stack-trace-exposure`` rule without losing the
    per-field feedback that makes settings forms usable.
    """
    parts = [f"{e['loc'][-1]}: {e['msg']}" for e in exc.errors() if e.get("loc")]
    return "; ".join(parts) if parts else "Invalid settings"


# Known workers with human-friendly labels (pipeline loops + background)
_bg_worker_defs = [
    (
        "triage",
        "Triage",
        "Classifies freshly discovered issues and routes them into the pipeline.",
    ),
    (
        "plan",
        "Plan",
        "Builds implementation plans for triaged issues that are ready to execute.",
    ),
    (
        "implement",
        "Implement",
        "Runs coding agents to implement planned issues and open pull requests.",
    ),
    (
        "review",
        "Review",
        "Reviews PRs, applies fixes, and merges approved work when checks pass.",
    ),
    (
        "retrospective",
        "Retrospective",
        "Captures post-merge outcomes and identifies recurring delivery patterns.",
    ),
    (
        "review_insights",
        "Review Insights",
        "Aggregates recurring review feedback into improvement opportunities.",
    ),
    (
        "pipeline_poller",
        "Pipeline Poller",
        "Refreshes live pipeline snapshots for dashboard queue/status rendering.",
    ),
    (
        "pr_unsticker",
        "PR Unsticker",
        "Requeues stalled HITL PRs by validating requirements and reopening flow.",
    ),
    (
        "report_issue",
        "Report Issue",
        "Processes queued bug reports into GitHub issues via the configured agent.",
    ),
    (
        "adr_reviewer",
        "ADR Reviewer",
        "Reviews proposed ADRs via a 3-judge council and routes to accept, reject, or escalate.",
    ),
    # --- Trust fleet (ADR-0045) ---
    (
        "corpus_learning",
        "Corpus Learning",
        "Synthesizes adversarial cases from skill/discover/shape escape signals and opens corpus-update PRs.",
    ),
    (
        "contract_refresh",
        "Contract Refresh",
        "Re-records fake-adapter cassettes and opens refresh PRs when committed cassettes drift from live behavior.",
    ),
    (
        "staging_bisect",
        "Staging Bisect",
        "Bisects RC red between last-green and current-red; opens auto-revert PRs and watches the next RC.",
    ),
    (
        "principles_audit",
        "Principles Audit",
        "Weekly ADR-0044 audit of HydraFlow-self plus managed repos; blocks onboarding on P1–P5 fails.",
    ),
    (
        "flake_tracker",
        "Flake Tracker",
        "Detects persistently flaky tests across recent RC runs and files flake-tracker issues.",
    ),
    (
        "skill_prompt_eval",
        "Skill Prompt Eval",
        "Weekly adversarial-corpus gate against built-in skills; flags PASS→FAIL regressions.",
    ),
    (
        "fake_coverage_auditor",
        "Fake Coverage Auditor",
        "Flags fake-adapter methods without cassettes and scenario helpers nobody calls.",
    ),
    (
        "rc_budget",
        "RC Budget",
        "Detects RC wall-clock bloat via rolling-median + spike signals across recent runs.",
    ),
    (
        "wiki_rot_detector",
        "Wiki Rot Detector",
        "Scans per-repo wikis for citations whose source code has moved or vanished.",
    ),
    (
        "trust_fleet_sanity",
        "Trust Fleet Sanity",
        "Meta-observer — watches the 9 trust loops for stalls, escalation spam, dedup growth, errors, cost spikes.",
    ),
    (
        "pricing_refresh",
        "Pricing Refresh",
        "Daily upstream-pricing refresh caretaker — fetches LiteLLM JSON, opens PR on drift; bounds-guarded, always human-reviewed.",
    ),
    (
        "cost_budget_watcher",
        "Cost Budget Watcher",
        "Polls rolling-24h LLM spend; disables caretaker loops when daily cap exceeded. Default unlimited.",
    ),
    # --- Background loops surfaced in the System tab (parity with bg_loop_registry;
    # enforced by tests/test_loop_wiring_completeness.py). Labels/descriptions mirror
    # ui/src/constants.js BACKGROUND_WORKERS. ---
    (
        "adr_touchpoint_auditor",
        "ADR Touchpoint Auditor",
        "Scans recently-merged PRs for ADR drift — cited src/ modules changed without the ADR being updated. Replaces the synchronous touchpoint gate. See ADR-0056.",
    ),
    (
        "adr_conformance",
        "ADR Conformance",
        "Evaluates every Accepted ADR's `Enforced by:` checks and files/updates remediation issues on drift. See ADR-0100.",
    ),
    (
        "auto_agent_preflight",
        "Auto-Agent Pre-Flight",
        "Intercepts hitl-escalation issues; runs an emulated-engineer subprocess to attempt autonomous resolution before the issue surfaces to a human (spec §1–§11; ADR-0050).",
    ),
    (
        "branch_protection_auditor",
        "Branch Protection Auditor",
        "Audits live GitHub branch protection against the canonical rulesets generated from gates.toml; files an issue on drift. See ADR-0082.",
    ),
    (
        "ci_monitor",
        "CI Monitor",
        "Detects failing CI on main and files/auto-closes issues.",
    ),
    (
        "dependabot_merge",
        "Dependabot Merge",
        "Auto-merges dependency update PRs from configured bots after CI passes.",
    ),
    (
        "diagnostic",
        "Diagnostic Agent",
        "Analyzes escalated issues, classifies severity, and attempts targeted fixes before HITL.",
    ),
    (
        "diagram_loop",
        "Diagram Loop (L24)",
        "Self-documenting architecture caretaker. Walks src/, tests/, docs/adr/ every 4h; emits regenerated docs/arch/generated/ markdown + opens a PR when the live truth has drifted. Per ADR-0029 (caretaker pattern) and the Architecture Knowledge System spec.",
    ),
    (
        "edge_proposer",
        "Edge Proposer",
        "Caretaker that proposes depends_on + implements edges between existing UL terms based on import graph + class inheritance. See ADR-0058.",
    ),
    (
        "entry_evidence",
        "Entry Evidence",
        "Caretaker that links wiki entries to UL terms via LLM matching, populating Term.evidence so the Atlas Domain view can render entry leaves under their term parents. See ADR-0062.",
    ),
    (
        "epic_monitor",
        "Epic Monitor",
        "Detects stale epics and refreshes progress cache so the dashboard shows accurate sub-issue rollups.",
    ),
    (
        "epic_sweeper",
        "Epic Sweeper",
        "Periodically sweeps open epics and auto-closes those with all sub-issues resolved.",
    ),
    (
        "gate_activator",
        "Gate Activator",
        "Proposes activating planned gates in gates.toml once the surface each protects exists (producing job + make target present, profile matches); files a reviewed issue. See ADR-0082.",
    ),
    (
        "github_cache",
        "GitHub Cache",
        "Single-poller cache for GitHub data; serves all dashboard + loop consumers from one shared snapshot to avoid rate-limit fan-out.",
    ),
    (
        "health_monitor",
        "Health Monitor",
        "Analyzes pipeline trends, auto-tunes parameters, detects knowledge gaps, and ingests log patterns.",
    ),
    (
        "label_drift_watcher",
        "Label Drift Watcher",
        "Periodic scan for cross-entity issue/PR label drift (e.g., issue at hydraflow-ready while linked PR at hydraflow-review with commits); reconciles via per-entity swap_pipeline_labels. See ADR-0088.",
    ),
    (
        "live_corpus_replay",
        "Live Corpus Replay",
        "Diffs fresh shadow-corpus samples against fake-adapter outputs to catch value-level drift between real and fake adapters; files one hydraflow-find issue per unique drift signature. See #8786 / ADR-0045.",
    ),
    (
        "memory_backlog",
        "Memory Backlog",
        "Files hydraflow-find issues for pending entries in docs/wiki/memory-feedback/.",
    ),
    (
        "merge_state_watcher",
        "Merge State Watcher",
        "Auto-rebases or HITL-escalates open PRs flagged mergeable=CONFLICTING (RC, dependabot, agent).",
    ),
    (
        "repo_wiki",
        "Repo Wiki",
        "Lints and maintains per-repo knowledge wikis compiled from plan/implement/review cycles.",
    ),
    (
        "runs_gc",
        "Runs GC",
        "Purges expired pipeline run artifacts per TTL and size-cap config; keeps the runs store from growing unbounded.",
    ),
    (
        "sandbox_failure_fixer",
        "Sandbox Failure Fixer",
        "Auto-fixes promotion PRs failing sandbox CI by dispatching the auto-agent",
    ),
    (
        "security_patch",
        "Security Patch",
        "Polls Dependabot alerts and files issues for fixable vulnerabilities.",
    ),
    (
        "sentry_ingest",
        "Sentry Ingest",
        "Polls Sentry for unresolved errors and files them as GitHub issues for the pipeline.",
    ),
    (
        "log_ingest",
        "Log Ingest",
        "Clusters and dedups recurring errors/warnings in HydraFlow's own server log and files them as fix-issues for the pipeline.",
    ),
    (
        "staging_promotion",
        "Staging Promotion",
        "Cuts release-candidate snapshots from staging and auto-promotes them to main on green CI. See ADR-0042.",
    ),
    (
        "stale_issue",
        "Stale General Issue Cleanup",
        "Auto-closes stale general issues (excludes HydraFlow lifecycle labels). Per-tag thresholds, configurable. Distinct from Stale Issue GC, which handles HITL escalations.",
    ),
    (
        "stale_issue_gc",
        "Stale HITL Issue GC",
        "Auto-closes stale HITL escalation issues — posts a farewell comment, capped at 10/cycle. Distinct from Stale General Issue Cleanup, which excludes HF lifecycle labels.",
    ),
    (
        "term_proposer",
        "Term Proposer",
        "Caretaker that grows the ubiquitous-language glossary by detecting load-bearing classes without terms (S1+S2+S5 signals), drafting them via LLM, and opening auto-merging bot PRs as `confidence: proposed`. See ADR-0054.",
    ),
    (
        "term_pruner",
        "Term Pruner",
        "Caretaker that deprecates UL terms whose code_anchor no longer resolves in src/. Companion to TermProposerLoop. See ADR-0057.",
    ),
    (
        "triage_retry",
        "Triage Retry",
        "Re-runs parked-issue triage every 24h with the original parking reason as context. Caps at 3 retries before escalating to HITL with the triage-retry-exhausted sub-label. Closes the only factory phase with no autonomous re-entry path. See ADR-0063 W2.",
    ),
    (
        "convergence_oscillation",
        "Convergence Oscillation",
        "Scans issue convergence ledgers for cross-boundary oscillation (repeated LOOP_BACK across triage/shape/plan or recurring review-lap findings) and escalates stuck issues to HITL, once each. See ADR-0098.",
    ),
    (
        "fitness_scorecard",
        "Fitness Scorecard",
        "Computes per-loop fitness scores each tick by combining event history and issue attribution. Persists to fitness.jsonl and regenerates docs/arch/generated/loop-fitness.md. Read-only caretaker per ADR-0029.",
    ),
    (
        "workspace_gc",
        "Workspace GC",
        "Garbage-collects stale workspaces and orphaned branches.",
    ),
]

# Workers that have independent configurable intervals
_INTERVAL_WORKERS = {
    "pr_unsticker",
    "pipeline_poller",
    "report_issue",
    # Trust fleet (ADR-0045): every loop's interval is operator-tunable.
    "corpus_learning",
    "contract_refresh",
    "staging_bisect",
    "principles_audit",
    "flake_tracker",
    "skill_prompt_eval",
    "fake_coverage_auditor",
    "rc_budget",
    "wiki_rot_detector",
    "trust_fleet_sanity",
    "pricing_refresh",
    "cost_budget_watcher",
}
# Pipeline loops share poll_interval (read-only display)
_PIPELINE_WORKERS = {"triage", "plan", "implement", "review"}
_WORKER_SOURCE_ALIASES: dict[str, tuple[str, ...]] = {
    "plan": ("planner",),
    "implement": ("agent",),
    "review": ("reviewer", "merge_conflict", "fresh_rebuild"),
}

_DEFAULT_PIPELINE_WORKERS = ("triage", "plan", "implement", "review", "hitl")


def register(router: APIRouter, ctx: RouteContext) -> None:  # noqa: PLR0915
    """Register control-related routes on *router*."""

    # Mutable fields that can be changed at runtime via PATCH
    _MUTABLE_FIELDS = {
        "gh_circuit_breaker_enabled",
        "max_triagers",
        "max_workers",
        "max_planners",
        "max_reviewers",
        "max_hitl_workers",
        "model",
        "review_model",
        "planner_model",
        "batch_size",
        "max_ci_fix_attempts",
        "max_quality_fix_attempts",
        "max_review_fix_attempts",
        "min_review_findings",
        "max_merge_conflict_fix_attempts",
        "ci_check_timeout",
        "ci_poll_interval",
        "poll_interval",
        "pr_unstick_interval",
        "pr_unstick_batch_size",
        "unstick_auto_merge",
        "unstick_all_causes",
        "memory_auto_approve",
        "workspace_base",
        "staging_enabled",
        "staging_branch",
        "main_branch",
        "rc_cadence_hours",
        "test_adequacy_coverage_timeout_secs",
    }

    def _build_system_worker_inference_stats(
        cfg: HydraFlowConfig | None = None,
    ) -> dict[str, dict[str, int]]:
        """Aggregate prompt-telemetry inference stats keyed by worker name.

        ``cfg`` defaults to the host config; pass the row's repo config so the
        per-repo cost telemetry is read from that repo's store.
        """
        telemetry = PromptTelemetry(cfg or ctx.config)
        source_totals = telemetry.get_source_totals()

        worker_totals: dict[str, dict[str, int]] = {}
        for worker_name, _label, _description in _bg_worker_defs:
            sources = (worker_name, *_WORKER_SOURCE_ALIASES.get(worker_name, ()))
            totals = {
                "inference_calls": 0,
                "total_tokens": 0,
                "pruned_chars_total": 0,
            }
            for source_name in sources:
                source_entry = source_totals.get(source_name)
                if not source_entry:
                    continue
                totals["inference_calls"] += source_entry["inference_calls"]
                totals["total_tokens"] += source_entry["total_tokens"]
                totals["pruned_chars_total"] += source_entry["pruned_chars_total"]
            if totals["inference_calls"] > 0:
                saved_tokens_est = round(totals["pruned_chars_total"] / 4)
                worker_totals[worker_name] = {
                    "inference_calls": totals["inference_calls"],
                    "total_tokens": totals["total_tokens"],
                    "pruned_chars_total": totals["pruned_chars_total"],
                    "saved_tokens_est": saved_tokens_est,
                    "unpruned_tokens_est": totals["total_tokens"] + saved_tokens_est,
                }
        return worker_totals

    def _compute_next_run(
        last_run: str | None, interval_seconds: int | None
    ) -> str | None:
        """Compute next run ISO timestamp from last_run + interval."""
        if not last_run or not interval_seconds:
            return None
        try:
            last_dt = datetime.fromisoformat(last_run)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=UTC)
            next_dt = last_dt + timedelta(seconds=interval_seconds)
            return next_dt.isoformat()
        except (ValueError, TypeError):
            return None

    @router.post("/api/control/start")
    async def start_orchestrator() -> JSONResponse:
        """Start the factory — the host line only.

        The factory-level Start brings up the **host** orchestrator line and
        nothing else. Registered repos are independent factory lines that the
        operator turns on individually via ``POST /api/runtimes/{slug}/start``
        once the factory is running — the factory runs fine with zero repos and
        must never force them all on. (Previously this called
        ``registry.start_all`` and booted every registered repo.)
        """
        registry = ctx.registry
        if registry is not None:
            host_rt = registry.get(ctx._default_slug())
            if host_rt is None:
                return JSONResponse(
                    {"error": "No host runtime registered"}, status_code=501
                )
            if not host_rt.running:
                await host_rt.start()
            await ctx.event_bus.publish(
                HydraFlowEvent(
                    type=EventType.ORCHESTRATOR_STATUS,
                    data=OrchestratorStatusPayload(status="running", reset=True),
                )
            )
            return JSONResponse({"status": "started"})

        # Legacy single-repo/test wiring (no registry): create+run the host orch.
        orch = ctx.get_orchestrator()
        if orch and orch.running:
            return JSONResponse({"error": "already running"}, status_code=409)

        from orchestrator import HydraFlowOrchestrator

        # Remove pipeline workers from the disabled set
        existing_disabled = ctx.state.get_disabled_workers()
        pipeline_names = set(_DEFAULT_PIPELINE_WORKERS)
        cleaned = existing_disabled - pipeline_names
        if cleaned != existing_disabled:
            ctx.state.set_disabled_workers(cleaned)

        new_orch = HydraFlowOrchestrator(
            ctx.config,
            event_bus=ctx.event_bus,
            state=ctx.state,
            pipeline_enabled=False,
        )
        ctx.set_orchestrator(new_orch)
        ctx.set_run_task(asyncio.create_task(new_orch.run()))
        await ctx.event_bus.publish(
            HydraFlowEvent(
                type=EventType.ORCHESTRATOR_STATUS,
                data=OrchestratorStatusPayload(status="running", reset=True),
            )
        )
        return JSONResponse({"status": "started"})

    @router.post("/api/control/stop")
    async def stop_orchestrator() -> JSONResponse:
        """Stop the entire factory — the host orchestrator and every line.

        The factory-level Stop halts every registered repo runtime
        (``registry.stop_all``), including the host. Stopping a single line is
        handled by ``POST /api/runtimes/{slug}/stop``.
        """
        registry = ctx.registry
        if registry is not None:
            if not any(rt.running for rt in registry.all):
                return JSONResponse({"error": "not running"}, status_code=400)
            await registry.stop_all()
            return JSONResponse({"status": "stopping"})

        # Legacy single-repo/test wiring (no registry): stop the host orch.
        orch = ctx.get_orchestrator()
        if not orch or not orch.running:
            return JSONResponse({"error": "not running"}, status_code=400)
        await orch.request_stop()
        return JSONResponse({"status": "stopping"})

    @router.post("/api/control/clear-credit-pause")
    async def clear_credit_pause(repo: RepoSlugParam = None) -> JSONResponse:
        """Clear an active credit pause, waking any sleeping loops.

        Credit pause is per-orchestrator, so ``repo=__all__`` fans out and
        clears every paused runtime; a single repo clears just that one.
        """
        if repo is not None and repo.strip().lower() == REPO_ALL:
            cleared: list[str] = []
            for _cfg, _state, _bus, _get_orch, slug in ctx.resolve_runtimes(repo):
                orch = _get_orch()
                if orch and orch.credits_paused_until is not None:
                    orch.clear_credit_pause()
                    cleared.append(slug)
            return JSONResponse({"status": "cleared", "repos": cleared})
        _cfg, _state, _bus, _get_orch = ctx.resolve_runtime(repo)
        orch = _get_orch()
        if not orch:
            return JSONResponse({"error": "no orchestrator"}, status_code=400)
        if orch.credits_paused_until is None:
            return JSONResponse({"error": "not paused"}, status_code=400)
        orch.clear_credit_pause()
        return JSONResponse({"status": "cleared"})

    # Rollup precedence for the aggregate top-level status (highest → lowest).
    _STATUS_PRECEDENCE = (
        "credits_paused",
        "auth_failed",
        "running",
        "stopping",
        "done",
        "idle",
    )

    def _control_status_config(
        cfg: HydraFlowConfig, *, latest_version: str, update_available: bool
    ) -> ControlStatusConfig:
        return ControlStatusConfig(
            app_version=get_app_version(),
            latest_version=latest_version,
            update_available=update_available,
            repo=cfg.repo,
            ready_label=cfg.ready_label,
            find_label=cfg.find_label,
            planner_label=cfg.planner_label,
            review_label=cfg.review_label,
            hitl_label=cfg.hitl_label,
            hitl_active_label=cfg.hitl_active_label,
            fixed_label=cfg.fixed_label,
            max_triagers=cfg.max_triagers,
            max_workers=cfg.max_workers,
            max_planners=cfg.max_planners,
            max_reviewers=cfg.max_reviewers,
            max_hitl_workers=cfg.max_hitl_workers,
            batch_size=cfg.batch_size,
            model=cfg.model,
            pr_unstick_batch_size=cfg.pr_unstick_batch_size,
            workspace_base=str(cfg.workspace_base),
            test_adequacy_coverage_timeout_secs=cfg.test_adequacy_coverage_timeout_secs,
        )

    def _runtime_status(orch: object | None) -> tuple[ControlStatus, str | None, bool]:
        """Return (status, credits_paused_until_iso, mockworld_active) for one orch."""
        status = getattr(orch, "run_status", "idle") if orch else "idle"
        try:
            control_status = ControlStatus(status)
        except ValueError:
            control_status = ControlStatus.IDLE
        credits = getattr(orch, "credits_paused_until", None) if orch else None
        credits_until = credits.isoformat() if credits else None
        # Sandbox-mode is duck-typed off the injected PRPort's _is_fake_adapter.
        mockworld_active = False
        if orch is not None:
            svc = getattr(orch, "_svc", None)
            if svc is not None:
                mockworld_active = bool(
                    getattr(getattr(svc, "prs", None), "_is_fake_adapter", False)
                )
        return control_status, credits_until, mockworld_active

    @router.get("/api/control/status")
    async def get_control_status(
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Return orchestrator run status, config summary, and version info.

        For ``repo=__all__`` the top-level fields are a rollup and ``repos``
        carries the per-repo breakdown; ``config`` is the default repo's.
        """
        update_result = load_cached_update_result(current_version=get_app_version())
        latest_version = (
            (update_result.latest_version or "") if update_result is not None else ""
        )
        update_available = (
            update_result.update_available if update_result is not None else False
        )

        if repo is not None and repo.strip().lower() == REPO_ALL:
            per_repo: list[dict[str, Any]] = []
            statuses: list[str] = []
            credits_candidates: list[str] = []
            mockworld_any = False
            for _cfg, _state, _bus, _get_orch, slug in ctx.resolve_runtimes(repo):
                cs, credits_until, mockworld = _runtime_status(_get_orch())
                statuses.append(cs.value)
                if credits_until:
                    credits_candidates.append(credits_until)
                mockworld_any = mockworld_any or mockworld
                per_repo.append(
                    {
                        "slug": slug,
                        "status": cs.value,
                        "credits_paused_until": credits_until,
                        "mockworld_active": mockworld,
                        "config": _control_status_config(
                            _cfg,
                            latest_version=latest_version,
                            update_available=update_available,
                        ).model_dump(),
                    }
                )
            rollup = next((s for s in _STATUS_PRECEDENCE if s in statuses), "idle")
            d_cfg, _ds, _db, _dget = ctx.resolve_runtime(None)
            response = ControlStatusResponse(
                status=ControlStatus(rollup),
                credits_paused_until=min(credits_candidates)
                if credits_candidates
                else None,
                config=_control_status_config(
                    d_cfg,
                    latest_version=latest_version,
                    update_available=update_available,
                ),
                mockworld_active=mockworld_any,
                repos=per_repo,
            )
            data = response.model_dump()
            data["current_session_id"] = None
            return JSONResponse(data)

        _cfg, _state, _bus, _get_orch = ctx.resolve_runtime(repo)
        orch = _get_orch()
        control_status, credits_until, mockworld_active = _runtime_status(orch)
        current_session = orch.current_session_id if orch else None
        response = ControlStatusResponse(
            status=control_status,
            credits_paused_until=credits_until,
            config=_control_status_config(
                _cfg,
                latest_version=latest_version,
                update_available=update_available,
            ),
            mockworld_active=mockworld_active,
        )
        data = response.model_dump()
        data["current_session_id"] = current_session
        return JSONResponse(data)

    @router.post("/api/control/credit-refresh")
    async def credit_refresh(
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Attempt to clear credit pause and resume processing.

        ``probe_credit_availability`` is a single process-global check, so
        ``repo=__all__`` probes once and resumes every paused runtime (parity
        with ``clear-credit-pause``).
        """
        from subprocess_util import probe_credit_availability

        async def _refresh_all() -> JSONResponse:
            paused = [
                (slug, orch)
                for _cfg, _state, _bus, _get_orch, slug in ctx.resolve_runtimes(repo)
                if (orch := _get_orch()) and orch.credits_paused_until is not None
            ]
            if not paused:
                return JSONResponse({"status": "not_paused"})
            if not await probe_credit_availability():
                return JSONResponse({"status": "still_exhausted"})
            resumed = [slug for slug, orch in paused if orch.try_clear_credit_pause()]
            return JSONResponse({"status": "resuming", "repos": resumed})

        if repo is not None and repo.strip().lower() == REPO_ALL:
            return await _refresh_all()

        _cfg, _state, _bus, _get_orch = ctx.resolve_runtime(repo)
        orch = _get_orch()
        if not orch:
            return JSONResponse({"error": "no orchestrator"}, status_code=400)
        if orch.credits_paused_until is None:
            return JSONResponse({"status": "not_paused"})
        credits_available = await probe_credit_availability()
        if not credits_available:
            return JSONResponse({"status": "still_exhausted"})
        cleared = orch.try_clear_credit_pause()
        if not cleared:
            return JSONResponse({"status": "not_paused"})
        return JSONResponse({"status": "resuming"})

    @router.post("/api/admin/prep")
    async def admin_prep(
        repo: str | None = Query(default=None, description="Repo slug to target"),
    ) -> JSONResponse:
        return await ctx.execute_admin_task("prep", run_prep, repo)

    @router.post("/api/admin/scaffold")
    async def admin_scaffold(
        repo: str | None = Query(default=None, description="Repo slug to target"),
    ) -> JSONResponse:
        return await ctx.execute_admin_task("scaffold", run_scaffold, repo)

    @router.post("/api/admin/clean")
    async def admin_clean(
        repo: str | None = Query(default=None, description="Repo slug to target"),
    ) -> JSONResponse:
        return await ctx.execute_admin_task("clean", run_clean, repo)

    @router.post("/api/admin/ensure-labels")
    async def admin_ensure_labels(
        repo: str | None = Query(default=None, description="Repo slug to target"),
    ) -> JSONResponse:
        return await ctx.execute_admin_task("ensure-labels", run_ensure_labels, repo)

    @router.post("/api/admin/compact")
    async def admin_compact(
        repo: str | None = Query(default=None, description="Repo slug to target"),
    ) -> JSONResponse:
        return await ctx.execute_admin_task("compact", run_compact, repo)

    @router.patch("/api/control/config")
    async def patch_config(
        body: dict[str, Any],
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Update runtime config fields. Pass ``persist: true`` to save to disk.

        Config writes target a single repo (or the default); ``repo=__all__``
        is rejected, and ``gh_circuit_breaker_enabled`` is process-global so it
        cannot be set per-repo.
        """
        if repo is not None and repo.strip().lower() == REPO_ALL:
            return JSONResponse(
                {
                    "status": "error",
                    "message": "config writes require a specific repo, not __all__",
                },
                status_code=400,
            )
        persist = body.pop("persist", False)
        _cfg, _state, _bus, _get_orch = ctx.resolve_runtime(repo)

        updates: dict[str, Any] = {}

        for key, value in body.items():
            if key not in _MUTABLE_FIELDS:
                continue
            if not hasattr(_cfg, key):
                continue
            updates[key] = value

        if repo is not None and "gh_circuit_breaker_enabled" in updates:
            return JSONResponse(
                {
                    "status": "error",
                    "message": "gh_circuit_breaker_enabled is process-global; "
                    "it cannot be set per-repo",
                },
                status_code=400,
            )

        if not updates:
            return JSONResponse({"status": "ok", "updated": {}})

        # Validate updates through Pydantic field constraints
        test_values = _cfg.model_dump()
        test_values.update(updates)
        try:
            validated = HydraFlowConfig.model_validate(test_values)
        except ValidationError as exc:
            errors = exc.errors()
            msg = "; ".join(
                f"{e['loc'][-1]}: {e['msg']}" for e in errors if e.get("loc")
            )
            return JSONResponse(
                {"status": "error", "message": msg or "Invalid configuration"},
                status_code=422,
            )

        # Apply validated values to the live config
        applied: dict[str, Any] = {}
        for key in updates:
            validated_value = getattr(validated, key)
            object.__setattr__(_cfg, key, validated_value)
            applied[key] = validated_value

        # The circuit breaker lives in the process-global subprocess layer, so
        # apply its enable/disable toggle live (the kill-switch). patch_config
        # otherwise only mutates the config object, which the breaker can't see.
        if "gh_circuit_breaker_enabled" in applied:
            from subprocess_util import (  # noqa: PLC0415
                set_gh_circuit_breaker_enabled,
            )

            set_gh_circuit_breaker_enabled(bool(applied["gh_circuit_breaker_enabled"]))

        if applied:
            if repo and ctx.repo_store is not None:
                ctx.repo_store.update_overrides(repo, applied)
            elif persist:
                save_config_file(_cfg.config_file, applied)

        return JSONResponse({"status": "ok", "updated": applied})

    def _workers_for_runtime(
        _cfg: HydraFlowConfig,
        _state: Any,
        orch: Any,
        slug: str,
    ) -> list[BackgroundWorkerStatus]:
        """Build the worker-status list for one runtime, tagged with its slug."""
        bg_states = orch.get_bg_worker_states() if orch else {}
        persisted_states: dict[str, BackgroundWorkerState] = {}
        if not orch:
            try:
                persisted_states = _state.get_bg_worker_states()
            except Exception:  # pragma: no cover - defensive guard
                logger.exception("Failed to load persisted bg worker states")
        inference_by_worker = _build_system_worker_inference_stats(_cfg)
        disabled_workers: set[str] = set()
        if not orch:
            try:
                disabled_workers = _state.get_disabled_workers()
            except Exception:  # pragma: no cover - defensive guard
                logger.exception("Failed to load persisted disabled workers")
        workers: list[BackgroundWorkerStatus] = []
        for name, label, description in _bg_worker_defs:
            enabled = (
                orch.is_bg_worker_enabled(name)
                if orch
                else name not in disabled_workers
            )

            # Determine interval for this worker
            interval: int | None = None
            if name in _INTERVAL_WORKERS and orch:
                interval = orch.get_bg_worker_interval(name)
            elif name in _INTERVAL_WORKERS:
                if name == "pr_unsticker":
                    interval = _cfg.pr_unstick_interval
                elif name == "pipeline_poller":
                    interval = 5
            elif name in _PIPELINE_WORKERS:
                interval = _cfg.poll_interval
            elif orch and name in _INTERVAL_BOUNDS:
                # Registry-backed loops surfaced in _bg_worker_defs but absent
                # from the curated _INTERVAL_WORKERS set: resolve the live
                # interval (incl. any operator override) straight from the
                # orchestrator so the System tab shows a real cadence + next_run
                # and interval edits round-trip. _INTERVAL_BOUNDS is the
                # editable-interval set, so this covers exactly the controllable
                # loops without inventing intervals for event-driven ones.
                interval = orch.get_bg_worker_interval(name)

            entry = bg_states.get(name) or persisted_states.get(name)
            if entry:
                last_run = entry.get("last_run")
                raw_details = entry.get("details", {})
                details: dict[str, Any] = (
                    dict(raw_details)
                    if isinstance(raw_details, dict)
                    else {"raw_details": str(raw_details)}
                )
                details.update(inference_by_worker.get(name, {}))
                workers.append(
                    BackgroundWorkerStatus(
                        name=name,
                        label=label,
                        description=description,
                        status=BGWorkerHealth(
                            entry.get("status", BGWorkerHealth.DISABLED)
                        ),
                        enabled=enabled,
                        last_run=last_run,
                        interval_seconds=interval,
                        next_run=_compute_next_run(last_run, interval),
                        details=details,
                        repo=slug,
                    )
                )
            else:
                workers.append(
                    BackgroundWorkerStatus(
                        name=name,
                        label=label,
                        description=description,
                        enabled=enabled,
                        interval_seconds=interval,
                        details=inference_by_worker.get(name, {}),
                        repo=slug,
                    )
                )
        return workers

    @router.get("/api/system/workers")
    async def get_system_workers(
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Return last known status of each background worker.

        For ``repo=__all__`` every repo's workers are unioned (not merged); a
        single repo (or the default) returns just its own. Every row is tagged
        with its CANONICAL resolved slug — resolve_runtimes uniformly handles
        all three cases, so the single-repo path no longer tags an empty string.
        """
        workers: list[BackgroundWorkerStatus] = []
        for _cfg, _state, _bus, _get_orch, slug in ctx.resolve_runtimes(repo):
            workers.extend(_workers_for_runtime(_cfg, _state, _get_orch(), slug))
        return JSONResponse(BackgroundWorkersResponse(workers=workers).model_dump())

    def _resolve_orch_for(repo: str | None) -> tuple[Any, JSONResponse | None]:
        """Resolve the row's orchestrator, or a 400 response (incl. __all__)."""
        if repo is not None and repo.strip().lower() == REPO_ALL:
            return None, JSONResponse(
                {"error": "this action requires a specific repo"}, status_code=400
            )
        _cfg, _state, _bus, _get_orch = ctx.resolve_runtime(repo)
        orch = _get_orch()
        if not orch:
            return None, JSONResponse({"error": "no orchestrator"}, status_code=400)
        return orch, None

    @router.post("/api/control/bg-worker")
    async def toggle_bg_worker(
        body: dict[str, Any], repo: RepoSlugParam = None
    ) -> JSONResponse:
        """Enable or disable a background worker (on the row's repo)."""
        name = body.get("name")
        enabled = body.get("enabled")
        if not name or enabled is None:
            return JSONResponse(
                {"error": "name and enabled are required"}, status_code=400
            )
        orch, rejected = _resolve_orch_for(repo)
        if rejected is not None:
            return rejected
        orch.set_bg_worker_enabled(name, bool(enabled))
        return JSONResponse({"status": "ok", "name": name, "enabled": bool(enabled)})

    @router.post("/api/control/bg-worker/trigger")
    async def trigger_bg_worker(
        body: dict[str, Any], repo: RepoSlugParam = None
    ) -> JSONResponse:
        """Trigger an immediate execution of a background worker (row's repo)."""
        name = body.get("name")
        if not name:
            return JSONResponse({"error": "name is required"}, status_code=400)
        orch, rejected = _resolve_orch_for(repo)
        if rejected is not None:
            return rejected
        triggered = orch.trigger_bg_worker(name)
        if not triggered:
            return JSONResponse({"error": f"unknown worker '{name}'"}, status_code=404)
        return JSONResponse({"status": "ok", "name": name})

    @router.post("/api/control/bg-worker/interval")
    async def set_bg_worker_interval(
        body: dict[str, Any], repo: RepoSlugParam = None
    ) -> JSONResponse:
        """Update the polling interval for a background worker (row's repo)."""
        name = body.get("name")
        interval = body.get("interval_seconds")
        if not name or interval is None:
            return JSONResponse(
                {"error": "name and interval_seconds are required"}, status_code=400
            )
        if name not in _INTERVAL_BOUNDS:
            return JSONResponse(
                {"error": f"interval not editable for worker '{name}'"}, status_code=400
            )
        try:
            interval = int(interval)
        except (TypeError, ValueError):
            return JSONResponse(
                {"error": "interval_seconds must be an integer"}, status_code=400
            )
        lo, hi = _INTERVAL_BOUNDS[name]
        if interval < lo or interval > hi:
            return JSONResponse(
                {"error": f"interval_seconds must be between {lo} and {hi}"},
                status_code=422,
            )
        orch, rejected = _resolve_orch_for(repo)
        if rejected is not None:
            return rejected
        orch.set_bg_worker_interval(name, interval)
        return JSONResponse(
            {"status": "ok", "name": name, "interval_seconds": interval}
        )

    @router.post("/api/admin/setup-staging-branch")
    async def setup_staging_branch(
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """One-shot: create staging branch from main (if missing) + protect it."""
        _cfg, _state, _bus, _get_orch = ctx.resolve_runtime(repo)
        # Branch-protection helpers are concrete-only on PRManager — they
        # call GitHub admin APIs Fakes don't model.
        pm: PRManager = cast("PRManager", ctx.pr_manager_for(_cfg, _bus))
        try:
            created = await pm.ensure_branch_exists(
                _cfg.staging_branch, base=_cfg.main_branch
            )
            protection = await pm.apply_staging_branch_protection(_cfg.staging_branch)
        except RuntimeError:
            logger.exception("setup_staging_branch failed")
            return JSONResponse(
                {
                    "status": "error",
                    "message": "Failed to configure staging branch; see server logs.",
                },
                status_code=502,
            )
        return JSONResponse(
            {
                "status": "ok",
                "branch": _cfg.staging_branch,
                "created": created,
                "protection": protection,
            }
        )

    @router.get("/api/staging-promotion/status")
    async def get_staging_promotion_status(  # noqa: PLR0914
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """RC lifecycle: cadence progress, open PR, recent throughput/failures."""
        _cfg, _state, _bus, _get_orch = ctx.resolve_runtime(repo)

        def _read_ts(path: Path) -> str | None:
            if not path.exists():
                return None
            try:
                return path.read_text().strip() or None
            except OSError:
                return None

        memory_dir = _cfg.data_root / "memory"
        last_rc_cut_at = _read_ts(memory_dir / ".staging_promotion_last_rc")
        last_sweep_at = _read_ts(memory_dir / ".staging_promotion_last_sweep")

        cadence_progress_hours: float | None = None
        if last_rc_cut_at:
            try:
                last = datetime.fromisoformat(last_rc_cut_at)
                if last.tzinfo is None:
                    last = last.replace(tzinfo=UTC)
                cadence_progress_hours = (
                    datetime.now(UTC) - last
                ).total_seconds() / 3600
            except ValueError:
                cadence_progress_hours = None

        open_pr = None
        recent: list[dict[str, Any]] = []
        if _cfg.staging_enabled:
            # ``list_recent_promotion_prs`` is GitHub-API helper on
            # concrete PRManager (not on PRPort).
            pm = cast("PRManager", ctx.pr_manager_for(_cfg, _bus))
            try:
                pr = await pm.find_open_promotion_pr()
            except Exception:  # noqa: BLE001
                pr = None
            if pr is not None:
                open_pr = {
                    "number": pr.number,
                    "branch": pr.branch,
                    "url": pr.url,
                }
            try:
                recent = await pm.list_recent_promotion_prs(days=7)
            except Exception:  # noqa: BLE001
                recent = []

        merged = sum(1 for p in recent if p.get("merged"))
        closed_unmerged = len(recent) - merged
        failure_rate = (closed_unmerged / len(recent)) if recent else None

        return JSONResponse(
            {
                "enabled": _cfg.staging_enabled,
                "cadence_hours": _cfg.rc_cadence_hours,
                "cadence_progress_hours": cadence_progress_hours,
                "last_rc_cut_at": last_rc_cut_at,
                "last_sweep_at": last_sweep_at,
                "open_promotion_pr": open_pr,
                "recent_window_days": 7,
                "recent_promoted": merged,
                "recent_failed": closed_unmerged,
                "recent_failure_rate": failure_rate,
            }
        )

    @router.get("/api/dependabot-merge/settings")
    async def get_dependabot_merge_settings() -> JSONResponse:
        """Return current Dependabot merge settings."""
        settings = ctx.state.get_dependabot_merge_settings()
        return JSONResponse(settings.model_dump())

    @router.post("/api/dependabot-merge/settings")
    async def set_dependabot_merge_settings(body: dict[str, Any]) -> JSONResponse:
        """Update Dependabot merge settings."""
        current = ctx.state.get_dependabot_merge_settings()
        update = current.model_dump()
        for key in ("authors", "failure_strategy", "review_mode"):
            if key in body:
                update[key] = body[key]

        try:
            from models import DependabotMergeSettings  # noqa: PLC0415

            new_settings = DependabotMergeSettings(**update)
        except ValidationError as exc:
            return JSONResponse({"error": _safe_error_message(exc)}, status_code=400)
        except ValueError:
            return JSONResponse({"error": "Invalid settings"}, status_code=400)

        ctx.state.set_dependabot_merge_settings(new_settings)
        return JSONResponse({"status": "ok", **new_settings.model_dump()})

    # --- Stale Issue Settings ---

    @router.get("/api/stale-issue/settings")
    async def get_stale_issue_settings() -> JSONResponse:
        """Return current stale issue cleanup settings."""
        settings = ctx.state.get_stale_issue_settings()
        return JSONResponse(settings.model_dump())

    @router.post("/api/stale-issue/settings")
    async def set_stale_issue_settings(body: dict[str, Any]) -> JSONResponse:
        """Update stale issue cleanup settings."""
        current = ctx.state.get_stale_issue_settings()
        update = current.model_dump()
        for key in ("staleness_days", "excluded_labels", "dry_run"):
            if key in body:
                update[key] = body[key]
        try:
            from models import StaleIssueSettings  # noqa: PLC0415

            new_settings = StaleIssueSettings(**update)
        except ValidationError as exc:
            return JSONResponse({"error": _safe_error_message(exc)}, status_code=400)
        except ValueError:
            return JSONResponse({"error": "Invalid settings"}, status_code=400)
        ctx.state.set_stale_issue_settings(new_settings)
        return JSONResponse({"status": "ok", **new_settings.model_dump()})

    # --- Security Patch Settings ---

    @router.get("/api/security-patch/settings")
    async def get_security_patch_settings() -> JSONResponse:
        """Return current security patch settings."""
        settings = ctx.state.get_security_patch_settings()
        return JSONResponse(settings.model_dump())

    @router.post("/api/security-patch/settings")
    async def set_security_patch_settings(body: dict[str, Any]) -> JSONResponse:
        """Update security patch settings."""
        current = ctx.state.get_security_patch_settings()
        update = current.model_dump()
        for key in ("severity_levels",):
            if key in body:
                update[key] = body[key]
        try:
            from models import SecurityPatchSettings  # noqa: PLC0415

            new_settings = SecurityPatchSettings(**update)
        except ValidationError as exc:
            return JSONResponse({"error": _safe_error_message(exc)}, status_code=400)
        except ValueError:
            return JSONResponse({"error": "Invalid settings"}, status_code=400)
        ctx.state.set_security_patch_settings(new_settings)
        return JSONResponse({"status": "ok", **new_settings.model_dump()})

    # --- CI Monitor Settings ---

    @router.get("/api/ci-monitor/settings")
    async def get_ci_monitor_settings() -> JSONResponse:
        """Return current CI monitor settings."""
        settings = ctx.state.get_ci_monitor_settings()
        return JSONResponse(settings.model_dump())

    @router.post("/api/ci-monitor/settings")
    async def set_ci_monitor_settings(body: dict[str, Any]) -> JSONResponse:
        """Update CI monitor settings."""
        current = ctx.state.get_ci_monitor_settings()
        update = current.model_dump()
        for key in ("branch", "workflows", "create_issue"):
            if key in body:
                update[key] = body[key]
        try:
            from models import CIMonitorSettings  # noqa: PLC0415

            new_settings = CIMonitorSettings(**update)
        except ValidationError as exc:
            return JSONResponse({"error": _safe_error_message(exc)}, status_code=400)
        except ValueError:
            return JSONResponse({"error": "Invalid settings"}, status_code=400)
        ctx.state.set_ci_monitor_settings(new_settings)
        return JSONResponse({"status": "ok", **new_settings.model_dump()})
