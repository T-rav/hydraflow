"""Headless onboarding draft API routes."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from onboarding.models import BootstrapDraft, BootstrapSpec

if TYPE_CHECKING:
    from dashboard_routes._routes import RouteContext

logger = logging.getLogger("hydraflow.dashboard.onboarding")


def _decode_draft(raw: dict[str, object]) -> BootstrapDraft | None:
    try:
        return BootstrapDraft.model_validate(raw)
    except ValidationError:
        logger.warning("Ignoring invalid onboarding draft payload", exc_info=True)
        return None


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
