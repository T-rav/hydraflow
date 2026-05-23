"""Headless onboarding draft API routes."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from onboarding.design_ai import DesignAIService, apply_field_updates
from onboarding.models import (
    BootstrapDraft,
    BootstrapSpec,
    DesignChatRequest,
    DesignRevisionRequest,
    MaterializeRequest,
)
from onboarding.templating import MaterializeError, materialize_repository

if TYPE_CHECKING:
    from dashboard_routes._routes import RouteContext

logger = logging.getLogger("hydraflow.dashboard.onboarding")
design_ai = DesignAIService()


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


def _safe_materialized_path(
    draft: BootstrapDraft, fallback_parent: Path
) -> Path | None:
    raw_path = draft.materialized_path or str(fallback_parent / draft.spec.name)
    candidate = Path(raw_path).expanduser().resolve(strict=False)
    allowed_roots = (
        Path.home().resolve(strict=False),
        Path(tempfile.gettempdir()).resolve(strict=False),
    )
    for root in allowed_roots:
        try:
            common = os.path.commonpath([str(candidate), str(root)])
        except ValueError:
            continue
        if common == str(root):
            return candidate
    return None


async def _run_checked(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    timeout: float = 120.0,
    allowed_error_fragments: tuple[str, ...] = (),
) -> str:
    proc: asyncio.subprocess.Process | None = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(cwd) if cwd else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except FileNotFoundError as exc:
        raise RuntimeError(f"{cmd[0]} CLI not found") from exc
    except TimeoutError as exc:
        if proc is not None:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
        raise RuntimeError(f"{cmd[0]} command timed out") from exc
    if proc.returncode != 0:
        detail = (stderr or stdout or b"").decode(errors="replace").strip()
        if any(fragment in detail.lower() for fragment in allowed_error_fragments):
            return detail
        raise RuntimeError(detail or f"{cmd[0]} command failed")
    return (stdout or b"").decode(errors="replace").strip()


async def _push_materialized_draft(draft: BootstrapDraft, repo_dir: Path) -> str:
    if not repo_dir.exists() or not repo_dir.is_dir():
        raise RuntimeError("materialized repository path is missing")

    repo_slug = f"{draft.spec.owner}/{draft.spec.name}"
    visibility_flag = "--public" if draft.spec.visibility == "public" else "--private"
    main_branch = draft.spec.main_branch
    staging_branch = draft.spec.staging_branch
    remote_url = f"https://github.com/{repo_slug}.git"

    if not (repo_dir / ".git").exists():
        await _run_checked(["git", "init", "-b", main_branch], cwd=repo_dir, timeout=30)
    await _run_checked(
        ["git", "config", "user.name", "HydraFlow Onboarding"], cwd=repo_dir, timeout=30
    )
    await _run_checked(
        [
            "git",
            "config",
            "user.email",
            "hydraflow-onboarding@users.noreply.github.com",
        ],
        cwd=repo_dir,
        timeout=30,
    )
    await _run_checked(["git", "add", "-A"], cwd=repo_dir, timeout=30)
    await _run_checked(
        ["git", "commit", "-m", "Initial HydraFlow bootstrap"],
        cwd=repo_dir,
        timeout=60,
        allowed_error_fragments=("nothing to commit", "no changes added to commit"),
    )
    await _run_checked(
        [
            "gh",
            "repo",
            "create",
            repo_slug,
            visibility_flag,
            "--description",
            draft.spec.description,
        ],
        timeout=120,
    )
    try:
        await _run_checked(
            ["git", "remote", "add", "origin", remote_url], cwd=repo_dir, timeout=30
        )
    except RuntimeError as exc:
        if "remote origin already exists" not in str(exc).lower():
            raise
        await _run_checked(
            ["git", "remote", "set-url", "origin", remote_url],
            cwd=repo_dir,
            timeout=30,
        )
    await _run_checked(["git", "push", "-u", "origin", main_branch], cwd=repo_dir)
    if staging_branch != main_branch:
        await _run_checked(
            ["git", "checkout", "-B", staging_branch, main_branch],
            cwd=repo_dir,
            timeout=30,
        )
        await _run_checked(
            ["git", "push", "-u", "origin", staging_branch], cwd=repo_dir
        )
        await _run_checked(["git", "checkout", main_branch], cwd=repo_dir, timeout=30)
    return f"https://github.com/{repo_slug}"


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

    @router.post("/api/onboarding/drafts/{draft_id}/design/chat")
    async def chat_onboarding_draft(
        draft_id: str, request: DesignChatRequest
    ) -> JSONResponse:
        raw = ctx.state.get_onboarding_draft(draft_id)
        if raw is None:
            return JSONResponse({"error": "Draft not found"}, status_code=404)
        draft = _decode_draft(raw)
        if draft is None:
            return JSONResponse({"error": "Draft is invalid"}, status_code=500)

        turn = design_ai.chat(draft, request.message)
        draft.chat_messages.append({"role": "user", "content": request.message})
        draft.chat_messages.append({"role": "assistant", "content": turn.reply})
        draft.extracted_fields.update(turn.field_updates)
        try:
            draft.spec = apply_field_updates(draft.spec, turn.field_updates)
        except ValidationError:
            return JSONResponse({"error": "Design update is invalid"}, status_code=422)
        draft.events.append({"level": "info", "message": "design chat updated fields"})
        _persist_draft(ctx, draft)
        return JSONResponse(
            {
                "draft": draft.model_dump(mode="json"),
                "reply": turn.reply,
                "field_updates": turn.field_updates,
                "clarification": turn.clarification,
            }
        )

    @router.post("/api/onboarding/drafts/{draft_id}/design/spec")
    async def draft_onboarding_spec(
        draft_id: str, request: DesignRevisionRequest | None = None
    ) -> JSONResponse:
        raw = ctx.state.get_onboarding_draft(draft_id)
        if raw is None:
            return JSONResponse({"error": "Draft not found"}, status_code=404)
        draft = _decode_draft(raw)
        if draft is None:
            return JSONResponse({"error": "Draft is invalid"}, status_code=500)

        draft.spec_draft = design_ai.draft_spec(
            draft, request.note if request else None
        )
        draft.events.append({"level": "info", "message": "wizard spec drafted"})
        _persist_draft(ctx, draft)
        return JSONResponse(
            {"draft": draft.model_dump(mode="json"), "spec_draft": draft.spec_draft}
        )

    @router.post("/api/onboarding/drafts/{draft_id}/design/plan")
    async def draft_onboarding_plan(
        draft_id: str, request: DesignRevisionRequest | None = None
    ) -> JSONResponse:
        raw = ctx.state.get_onboarding_draft(draft_id)
        if raw is None:
            return JSONResponse({"error": "Draft not found"}, status_code=404)
        draft = _decode_draft(raw)
        if draft is None:
            return JSONResponse({"error": "Draft is invalid"}, status_code=500)

        draft.plan_draft = design_ai.draft_plan(
            draft, request.note if request else None
        )
        draft.events.append({"level": "info", "message": "wizard plan drafted"})
        _persist_draft(ctx, draft)
        return JSONResponse(
            {"draft": draft.model_dump(mode="json"), "plan_draft": draft.plan_draft}
        )

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
        draft.materialized_path = str(result.root)
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

    @router.post("/api/onboarding/drafts/{draft_id}/push")
    async def push_onboarding_draft(draft_id: str) -> JSONResponse:
        raw = ctx.state.get_onboarding_draft(draft_id)
        if raw is None:
            return JSONResponse({"error": "Draft not found"}, status_code=404)
        draft = _decode_draft(raw)
        if draft is None:
            return JSONResponse({"error": "Draft is invalid"}, status_code=500)
        if draft.materialize_status != "succeeded":
            return JSONResponse(
                {
                    "error": "Draft must be materialized before it can be pushed",
                    "draft": draft.model_dump(mode="json"),
                },
                status_code=409,
            )

        repo_dir = _safe_materialized_path(draft, ctx.config.repos_workspace_dir)
        if repo_dir is None:
            return JSONResponse(
                {
                    "error": "materialized_path must be inside your home directory or temp directory",
                    "draft": draft.model_dump(mode="json"),
                },
                status_code=400,
            )

        draft.status = "pushing"
        draft.push_status = "running"
        draft.events.append({"level": "info", "message": "push started"})
        _persist_draft(ctx, draft)

        try:
            repo_url = await _push_materialized_draft(draft, repo_dir)
        except RuntimeError as exc:
            draft.status = "materialized"
            draft.push_status = "failed"
            draft.events.append({"level": "error", "message": str(exc)})
            _persist_draft(ctx, draft)
            return JSONResponse(
                {
                    "error": "Draft could not be pushed",
                    "draft": draft.model_dump(mode="json"),
                },
                status_code=502,
            )

        draft.status = "pushed"
        draft.push_status = "succeeded"
        draft.repo_url = repo_url
        draft.events.append({"level": "info", "message": "push succeeded"})
        _persist_draft(ctx, draft)
        return JSONResponse(
            {"draft": draft.model_dump(mode="json"), "repo_url": repo_url}
        )
