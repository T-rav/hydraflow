"""Headless onboarding draft API routes."""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from onboarding.models import BootstrapDraft, BootstrapSpec, MaterializeRequest
from onboarding.templating import MaterializeError, materialize_repository

if TYPE_CHECKING:
    from dashboard_routes._routes import RouteContext

logger = logging.getLogger("hydraflow.dashboard.onboarding")


def _decode_draft(raw: dict[str, object]) -> BootstrapDraft | None:
    try:
        return BootstrapDraft.model_validate(raw)
    except ValidationError:
        logger.warning("Ignoring invalid onboarding draft payload")
        return None


def _allowed_output_dir(raw_path: str | None, default_parent: Path) -> Path | None:
    candidate = Path(raw_path).expanduser() if raw_path else default_parent
    resolved = candidate.resolve(strict=False)
    allowed_roots = (
        Path.home().resolve(strict=False),
        Path(tempfile.gettempdir()).resolve(strict=False),
    )
    for root in allowed_roots:
        try:
            os.path.commonpath([str(resolved), str(root)])
        except ValueError:
            continue
        if str(resolved) == str(root) or str(resolved).startswith(f"{root}{os.sep}"):
            return resolved
    return None


def _persist_draft(ctx: RouteContext, draft: BootstrapDraft) -> None:
    draft.touch()
    ctx.state.set_onboarding_draft(draft.id, draft.model_dump(mode="json"))


def register(router: APIRouter, ctx: RouteContext) -> None:
    """Register onboarding API routes on *router*."""

    @router.post("/api/onboarding/drafts")
    async def create_onboarding_draft(spec: BootstrapSpec) -> JSONResponse:
        draft = BootstrapDraft(spec=spec)
        ctx.state.set_onboarding_draft(
            draft.id,
            draft.model_dump(mode="json"),
        )
        return JSONResponse(draft.model_dump(mode="json"), status_code=201)

    @router.get("/api/onboarding/drafts")
    async def list_onboarding_drafts() -> JSONResponse:
        drafts = [
            draft.model_dump(mode="json")
            for raw in ctx.state.list_onboarding_drafts()
            if (draft := _decode_draft(raw)) is not None
        ]
        drafts.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
        return JSONResponse({"drafts": drafts})

    @router.get("/api/onboarding/drafts/{draft_id}")
    async def get_onboarding_draft(draft_id: str) -> JSONResponse:
        raw = ctx.state.get_onboarding_draft(draft_id)
        if raw is None:
            return JSONResponse({"error": "Draft not found"}, status_code=404)
        draft = _decode_draft(raw)
        if draft is None:
            return JSONResponse({"error": "Draft is invalid"}, status_code=500)
        return JSONResponse(draft.model_dump(mode="json"))

    @router.post("/api/onboarding/drafts/{draft_id}/materialize")
    async def materialize_onboarding_draft(
        draft_id: str, request: MaterializeRequest | None = None
    ) -> JSONResponse:
        raw = ctx.state.get_onboarding_draft(draft_id)
        if raw is None:
            return JSONResponse({"error": "Draft not found"}, status_code=404)
        draft = _decode_draft(raw)
        if draft is None:
            return JSONResponse({"error": "Draft is invalid"}, status_code=500)

        output_dir = _allowed_output_dir(
            request.output_dir if request else None,
            ctx.config.repos_workspace_dir,
        )
        if output_dir is None:
            return JSONResponse(
                {
                    "error": "output_dir must be inside your home directory or temp directory"
                },
                status_code=400,
            )

        draft.status = "materializing"
        draft.materialize_status = "running"
        draft.events.append({"level": "info", "message": "materialize started"})
        _persist_draft(ctx, draft)

        try:
            result = materialize_repository(draft.spec, output_dir)
        except MaterializeError as exc:
            draft.status = "error"
            draft.materialize_status = "failed"
            draft.events.append({"level": "error", "message": str(exc)})
            _persist_draft(ctx, draft)
            return JSONResponse(
                {
                    "error": "Draft could not be materialized",
                    "draft": draft.model_dump(mode="json"),
                },
                status_code=409,
            )

        draft.status = "materialized"
        draft.materialize_status = "succeeded"
        draft.events.extend(result.events)
        _persist_draft(ctx, draft)
        return JSONResponse(
            {
                "draft": draft.model_dump(mode="json"),
                "materialized": {
                    "path": str(result.root),
                    "files": [
                        {"path": item.path, "bytes_written": item.bytes_written}
                        for item in result.files
                    ],
                },
            }
        )
