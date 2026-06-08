"""HITL route handlers extracted from _routes.py."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from dashboard_routes._routes import RouteContext
from events import EventType, HydraFlowEvent
from github_cache_loop import GitHubDataCache
from models import (
    HITLCloseRequest,
    HITLSkipRequest,
    HITLUpdatePayload,
    IssueOutcomeType,
)
from ports import PRPort
from route_types import REPO_ALL, RepoSlugParam

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from events import EventBus
    from orchestrator import HydraFlowOrchestrator
    from state import StateTracker

logger = logging.getLogger("hydraflow.dashboard")


_SANDBOX_HITL_LABEL = "sandbox-hitl"


async def sandbox_hitl_handler(prs: PRPort) -> dict[str, Any]:
    """Return open PRs labeled ``sandbox-hitl`` for the System tab queue.

    PRs land here after :class:`SandboxFailureFixerLoop` hits the 3-attempt
    auto-fix cap and escalates by swapping the ``sandbox-fail-auto-fix``
    label for ``sandbox-hitl``. Surfaces the PR + branch so a human can
    take over.

    Kept separate from ``/api/hitl`` (which returns issue-shaped data via
    :class:`HITLItem`) so PR-shaped payloads don't contaminate that
    endpoint's contract — the dashboard merges the two lists client-side.
    """
    candidates = await prs.list_prs_by_label(_SANDBOX_HITL_LABEL)
    return {
        "items": [
            {
                "number": pr.number,
                "branch": pr.branch,
                "url": str(pr.url),
                "draft": pr.draft,
                "type": "pr",
                "label": _SANDBOX_HITL_LABEL,
            }
            for pr in candidates
        ],
    }


# Strong references for fire-and-forget warm_hitl_summary tasks — without
# this the GC can collect the Task before it completes, silently cancelling
# the coroutine (#6600). Follows the ``events.py:_pending_persists`` pattern.
_pending_warm_tasks: set[asyncio.Task[None]] = set()


def _log_warm_failure(task: asyncio.Task[None]) -> None:
    """Log any exception raised by a warm_hitl_summary task."""
    try:
        exc = task.exception()
    except asyncio.CancelledError:
        return
    if exc is not None:
        logger.warning("warm_hitl_summary task failed", exc_info=exc)


def register(router: APIRouter, ctx: RouteContext) -> None:
    """Register HITL-related routes on *router*."""

    def _clear_hitl_state(
        orch: HydraFlowOrchestrator | None,
        issue_number: int,
        state: StateTracker,
    ) -> None:
        """Clear all HITL tracking state for an issue (on the row's state)."""
        if orch:
            orch.skip_hitl_issue(issue_number)
        state.clear_hitl_state(issue_number)

    async def _resolve_hitl_item(
        issue_number: int,
        orch: HydraFlowOrchestrator,
        *,
        action: str,
        comment_heading: str,
        comment_body: str,
        outcome_type: IssueOutcomeType,
        reason: str,
        state: StateTracker,
        bus: EventBus,
        pr_manager: PRPort,
    ) -> JSONResponse:
        """Clear HITL state, record outcome, post comment, and publish event.

        Operates on the *row's* repo objects (state/bus/pr_manager) so a
        mutation never touches the default repo's persistence.
        """
        _clear_hitl_state(orch, issue_number, state)
        state.record_outcome(
            issue_number,
            outcome_type,
            reason=reason,
            phase="hitl",
        )

        try:
            await pr_manager.post_comment(
                issue_number,
                f"**{comment_heading}** — {comment_body}\n\n---\n*HydraFlow Dashboard*",
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "Failed to post %s comment for issue #%d",
                action,
                issue_number,
                exc_info=True,
            )

        await bus.publish(
            HydraFlowEvent(
                type=EventType.HITL_UPDATE,
                data=HITLUpdatePayload(
                    issue=issue_number,
                    status="resolved",
                    action=action,
                    reason=reason,
                ),
            )
        )
        return JSONResponse({"status": "ok"})

    def _enrich_hitl_data(
        data: dict[str, Any],
        issue_num: int,
        *,
        cfg: HydraFlowConfig,
        state: StateTracker,
    ) -> None:
        """Enrich one item's dict from the row's repo state/config in place.

        Reads cause/summary/visual evidence from the **row's** state (not the
        host's) and schedules summary warming with the row's state/config/
        issue-fetcher — fixing the latent bug where issue #N of a non-default
        repo was enriched (and warmed) against the default repo.
        """
        cause = state.get_hitl_cause(issue_num)
        origin = state.get_hitl_origin(issue_num)
        if not cause and origin:
            if origin in cfg.review_label:
                cause = "Review escalation"
            elif origin in cfg.find_label:
                cause = "Triage escalation"
            else:
                cause = "Escalation (reason not recorded)"
        if cause:
            data["cause"] = cause
        if cause and (
            "epic detected" in cause.lower() or "bug report detected" in cause.lower()
        ):
            data["issueTypeReview"] = True
        cached_summary = state.get_hitl_summary(issue_num)
        data["llmSummary"] = cached_summary or ""
        data["llmSummaryUpdatedAt"] = state.get_hitl_summary_updated_at(issue_num)
        visual_ev = state.get_hitl_visual_evidence(issue_num)
        if visual_ev:
            data["visualEvidence"] = visual_ev.model_dump()
        if (
            not cached_summary
            and cfg.transcript_summarization_enabled
            and not cfg.dry_run
            and bool(ctx.credentials.gh_token)
            and ctx.hitl_summary_retry_due(issue_num, state=state)
        ):
            fetcher = ctx.issue_fetcher_for(cfg)
            warm_task = asyncio.create_task(
                ctx.warm_hitl_summary(
                    issue_num,
                    cause=cause or "",
                    origin=origin,
                    state=state,
                    config=cfg,
                    issue_fetcher=fetcher,
                )
            )
            _pending_warm_tasks.add(warm_task)
            warm_task.add_done_callback(_pending_warm_tasks.discard)
            warm_task.add_done_callback(_log_warm_failure)

    @router.get("/api/hitl")
    async def get_hitl(
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Fetch issues/PRs labeled for human-in-the-loop, unioned across repos.

        For ``repo=__all__`` every registered repo contributes its HITL items
        tagged with its slug — **including stopped repos** (stuck issues matter
        regardless of pipeline state), so there is no top-level active-gate;
        each item is enriched against its own repo's state/config.
        """
        enriched: list[dict[str, Any]] = []
        for _cfg, _state, _bus, _get_orch, slug in ctx.resolve_runtimes(repo):
            orch = _get_orch()
            if orch and isinstance(
                getattr(orch, "github_cache", None), GitHubDataCache
            ):
                items = orch.github_cache.get_hitl_items()
            else:
                hitl_labels = list(
                    dict.fromkeys([*_cfg.hitl_label, *_cfg.hitl_active_label])
                )
                manager = ctx.pr_manager_for(_cfg, _bus)
                items = await manager.list_hitl_items(hitl_labels)
            for item in items:
                data = (
                    dict(item)
                    if isinstance(item, dict)
                    else item.model_dump(by_alias=True)
                )
                issue_num: int = int(
                    data.get("issue", 0) if isinstance(item, dict) else item.issue
                )
                if orch:
                    data["status"] = orch.get_hitl_status(issue_num)
                _enrich_hitl_data(data, issue_num, cfg=_cfg, state=_state)
                data["repo"] = slug
                enriched.append(data)

        return JSONResponse(enriched)

    @router.get("/api/sandbox-hitl")
    async def get_sandbox_hitl(
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Return open PRs labeled ``sandbox-hitl`` for the System tab queue.

        Cap-hit escalation surface from :class:`SandboxFailureFixerLoop`
        (after 3 failed auto-fix attempts the loop swaps
        ``sandbox-fail-auto-fix`` for ``sandbox-hitl``). Unioned across repos
        for ``repo=__all__`` (each PR tagged with its repo slug). Separate from
        ``/api/hitl`` so PR-shaped payloads don't contaminate the issue-shaped
        contract there — the dashboard merges client-side.
        """
        merged: list[dict[str, Any]] = []
        for _cfg, _state, _bus, _get_orch, slug in ctx.resolve_runtimes(repo):
            manager = ctx.pr_manager_for(_cfg, _bus)
            payload = await sandbox_hitl_handler(prs=manager)
            for pr in payload["items"]:
                pr["repo"] = slug
                merged.append(pr)
        return JSONResponse({"items": merged})

    def _reject_repo_all(repo: str | None) -> JSONResponse | None:
        """Return a 400 when a row-scoped mutation is called with repo=__all__."""
        if repo is not None and repo.strip().lower() == REPO_ALL:
            return JSONResponse(
                {"status": "error", "detail": "this action requires a specific repo"},
                status_code=400,
            )
        return None

    @router.get("/api/hitl/{issue_number}/summary")
    async def get_hitl_summary(
        issue_number: int, repo: RepoSlugParam = None
    ) -> JSONResponse:
        """Return cached HITL summary, generating one if missing (row's repo).

        A single issue's summary is repo-scoped, so ``repo=__all__`` is
        rejected — there is no aggregate summary for one issue number.
        """
        if (rejected := _reject_repo_all(repo)) is not None:
            return rejected
        _cfg, _state, _bus, _get_orch = ctx.resolve_runtime(repo)
        cached = _state.get_hitl_summary(issue_number)
        if cached:
            return JSONResponse(
                {
                    "issue": issue_number,
                    "summary": cached,
                    "updated_at": _state.get_hitl_summary_updated_at(issue_number),
                    "cached": True,
                }
            )

        cause = _state.get_hitl_cause(issue_number) or ""
        origin = _state.get_hitl_origin(issue_number)
        summary = await ctx.compute_hitl_summary(
            issue_number,
            cause=cause,
            origin=origin,
            state=_state,
            config=_cfg,
            issue_fetcher=ctx.issue_fetcher_for(_cfg),
        )
        if summary:
            return JSONResponse(
                {
                    "issue": issue_number,
                    "summary": summary,
                    "updated_at": _state.get_hitl_summary_updated_at(issue_number),
                    "cached": False,
                }
            )
        return JSONResponse(
            {
                "issue": issue_number,
                "summary": "",
                "updated_at": None,
                "cached": False,
            }
        )

    @router.post("/api/hitl/{issue_number}/correct")
    async def hitl_correct(
        issue_number: int, body: dict[str, Any], repo: RepoSlugParam = None
    ) -> JSONResponse:
        """Submit a correction for a HITL issue to guide retry (row's repo)."""
        if (rejected := _reject_repo_all(repo)) is not None:
            return rejected
        _cfg, _state, _bus, _get_orch = ctx.resolve_runtime(repo)
        orch = _get_orch()
        if not orch:
            return JSONResponse({"status": "no orchestrator"}, status_code=400)
        correction = body.get("correction") or ""
        if not correction.strip():
            return JSONResponse(
                {"status": "error", "detail": "Correction text must not be empty"},
                status_code=400,
            )
        orch.submit_hitl_correction(issue_number, correction)

        # Swap labels for immediate dashboard feedback
        await ctx.pr_manager_for(_cfg, _bus).swap_pipeline_labels(
            issue_number, _cfg.hitl_active_label[0]
        )

        await _bus.publish(
            HydraFlowEvent(
                type=EventType.HITL_UPDATE,
                data=HITLUpdatePayload(
                    issue=issue_number,
                    status="processing",
                    action="correct",
                ),
            )
        )
        return JSONResponse({"status": "ok"})

    @router.post("/api/hitl/{issue_number}/skip")
    async def hitl_skip(
        issue_number: int, body: HITLSkipRequest, repo: RepoSlugParam = None
    ) -> JSONResponse:
        """Remove a HITL issue from the queue without action (row's repo)."""
        if (rejected := _reject_repo_all(repo)) is not None:
            return rejected
        _cfg, _state, _bus, _get_orch = ctx.resolve_runtime(repo)
        orch = _get_orch()
        if not orch:
            return JSONResponse({"status": "no orchestrator"}, status_code=400)

        pr_manager = ctx.pr_manager_for(_cfg, _bus)
        await pr_manager.close_issue(issue_number)

        return await _resolve_hitl_item(
            issue_number,
            orch,
            action="skip",
            comment_heading="HITL Skip",
            comment_body=f"Operator skipped this issue.\n\n**Reason:** {body.reason}",
            outcome_type=IssueOutcomeType.HITL_SKIPPED,
            reason=body.reason,
            state=_state,
            bus=_bus,
            pr_manager=pr_manager,
        )

    @router.post("/api/hitl/{issue_number}/close")
    async def hitl_close(
        issue_number: int, body: HITLCloseRequest, repo: RepoSlugParam = None
    ) -> JSONResponse:
        """Close a HITL issue on GitHub (row's repo)."""
        if (rejected := _reject_repo_all(repo)) is not None:
            return rejected
        _cfg, _state, _bus, _get_orch = ctx.resolve_runtime(repo)
        orch = _get_orch()
        if not orch:
            return JSONResponse({"status": "no orchestrator"}, status_code=400)
        pr_manager = ctx.pr_manager_for(_cfg, _bus)
        await pr_manager.close_issue(issue_number)

        return await _resolve_hitl_item(
            issue_number,
            orch,
            action="close",
            comment_heading="HITL Close",
            comment_body=f"Operator closed this issue.\n\n**Reason:** {body.reason}",
            outcome_type=IssueOutcomeType.HITL_CLOSED,
            reason=body.reason,
            state=_state,
            bus=_bus,
            pr_manager=pr_manager,
        )

    @router.post("/api/hitl/{issue_number}/approve-process")
    async def hitl_approve_process(
        issue_number: int, repo: RepoSlugParam = None
    ) -> JSONResponse:
        """Approve a HITL item held for issue type review (row's repo).

        All issue types (bugs, epics, etc.) route to triage first.
        """
        if (rejected := _reject_repo_all(repo)) is not None:
            return rejected
        _cfg, _state, _bus, _get_orch = ctx.resolve_runtime(repo)
        orch = _get_orch()
        if not orch:
            return JSONResponse({"status": "no orchestrator"}, status_code=400)

        target_label = _cfg.find_label[0]
        target_stage = "triage"

        pr_manager = ctx.pr_manager_for(_cfg, _bus)
        await pr_manager.swap_pipeline_labels(issue_number, target_label)

        return await _resolve_hitl_item(
            issue_number,
            orch,
            action="approved_for_processing",
            comment_heading="Approved for processing",
            comment_body=(
                f"Operator approved this issue.\n\n"
                f"Routing to **{target_stage}** (`{target_label}`)."
            ),
            outcome_type=IssueOutcomeType.HITL_APPROVED,
            reason=f"Operator approved issue type for processing ({target_stage})",
            state=_state,
            bus=_bus,
            pr_manager=pr_manager,
        )

    @router.get("/api/human-input")
    async def get_human_input_requests(
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Return pending human-input prompts from the orchestrator."""
        _cfg, _state, _bus, _get_orch = ctx.resolve_runtime(repo)
        orch = _get_orch()
        if orch:
            return JSONResponse(orch.human_input_requests)
        return JSONResponse({})

    @router.post("/api/human-input/{issue_number}")
    async def provide_human_input(
        issue_number: int,
        body: dict[str, Any],
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Submit an operator answer to a pending human-input request."""
        _cfg, _state, _bus, _get_orch = ctx.resolve_runtime(repo)
        orch = _get_orch()
        if orch:
            answer = body.get("answer", "")
            orch.provide_human_input(issue_number, answer)
            return JSONResponse({"status": "ok"})
        return JSONResponse({"status": "no orchestrator"}, status_code=400)
