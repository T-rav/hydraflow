"""Epic route handlers extracted from _routes.py."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from dashboard_routes._routes import RouteContext
from route_types import REPO_ALL, RepoSlugParam


def register(router: APIRouter, ctx: RouteContext) -> None:
    """Register epic-related routes on *router*."""

    def _is_all(repo: str | None) -> bool:
        return repo is not None and repo.strip().lower() == REPO_ALL

    @router.get("/api/epics")
    async def get_epics(
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Return all tracked epics — unioned across repos for ``repo=__all__``
        and tagged by repo slug (epic numbers collide across repos)."""
        epics: list[dict[str, object]] = []
        for _cfg, _state, _bus, get_orch, slug in ctx.resolve_runtimes(repo):
            orch = get_orch()
            if orch is None:
                continue
            for detail in await orch.epic_manager.get_all_detail():
                epics.append({**detail.model_dump(), "repo": slug})
        return JSONResponse(epics)

    @router.get("/api/epics/{epic_number}")
    async def get_epic_detail(
        epic_number: int,
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Return full detail for a single epic (requires a specific repo)."""
        if _is_all(repo):
            return JSONResponse(
                {"error": "epic detail requires a specific repo"}, status_code=400
            )
        _cfg, _state, _bus, _get_orch = ctx.resolve_runtime(repo)
        orch = _get_orch()
        if orch is None:
            return JSONResponse({"error": "orchestrator not running"}, status_code=503)
        detail = await orch.epic_manager.get_detail(epic_number)
        if detail is None:
            return JSONResponse({"error": "epic not found"}, status_code=404)
        return JSONResponse(detail.model_dump())

    @router.post("/api/epics/{epic_number}/release")
    async def trigger_epic_release(
        epic_number: int,
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Trigger async merge sequence and release creation for an epic.

        Returns a job_id. Completion is signalled via the EPIC_RELEASED WebSocket
        event — there is no REST polling endpoint for job status.
        """
        if _is_all(repo):
            return JSONResponse(
                {"error": "epic release requires a specific repo"}, status_code=400
            )
        _cfg, _state, _bus, _get_orch = ctx.resolve_runtime(repo)
        orch = _get_orch()
        if orch is None:
            return JSONResponse({"error": "orchestrator not running"}, status_code=503)
        result = await orch.epic_manager.trigger_release(epic_number)
        if "error" in result:
            return JSONResponse(result, status_code=400)
        return JSONResponse(result)
