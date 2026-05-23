"""Headless onboarding draft API routes."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError

from onboarding.design_ai import DesignAIService, DesignTurn, apply_field_updates
from onboarding.models import (
    BootstrapDraft,
    BootstrapSpec,
    ContinuePlanRequest,
    DesignChatRequest,
    DesignRevisionRequest,
    MaterializeRequest,
    SaveSpecDraftRequest,
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


async def _apply_design_turn(
    ctx: RouteContext,
    draft: BootstrapDraft,
    request: DesignChatRequest,
) -> tuple[BootstrapDraft, DesignTurn] | JSONResponse:
    turn = await design_ai.chat(draft, request.message)
    draft.chat_messages.append({"role": "user", "content": request.message})
    draft.chat_messages.append({"role": "assistant", "content": turn.reply})
    draft.extracted_fields.update(turn.field_updates)
    try:
        draft.spec = apply_field_updates(draft.spec, turn.field_updates)
    except ValidationError:
        return JSONResponse({"error": "Design update is invalid"}, status_code=422)
    event_message = "design chat updated fields"
    if turn.source == "claude":
        event_message = "claude design chat updated fields"
    if turn.fallback_reason:
        event_message = f"design chat used form-fill fallback: {turn.fallback_reason}"
    draft.events.append({"level": "info", "message": event_message})
    _persist_draft(ctx, draft)
    return draft, turn


def _chat_response_payload(
    draft: BootstrapDraft, turn: DesignTurn
) -> dict[str, object]:
    return {
        "draft": draft.model_dump(mode="json"),
        "reply": turn.reply,
        "field_updates": turn.field_updates,
        "clarification": turn.clarification,
    }


def _operation_event_payload(event: dict[str, object]) -> dict[str, object]:
    return {"type": "activity", "event": event}


def _json_response_payload(response: JSONResponse) -> dict[str, object]:
    return json.loads(bytes(response.body).decode("utf-8"))


def _load_draft_response(
    ctx: RouteContext, draft_id: str
) -> tuple[BootstrapDraft | None, JSONResponse | None]:
    raw = ctx.state.get_onboarding_draft(draft_id)
    if raw is None:
        return None, JSONResponse({"error": "Draft not found"}, status_code=404)
    draft = _decode_draft(raw)
    if draft is None:
        return None, JSONResponse({"error": "Draft is invalid"}, status_code=500)
    return draft, None


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


def _next_plan_label(current_plan: str | None) -> str:
    if not current_plan:
        return "Plan 02"
    digits = "".join(ch for ch in current_plan if ch.isdigit())
    if not digits:
        return "Plan 02"
    return f"Plan {int(digits) + 1:02d}"


def _issue_title(plan_label: str, task: str) -> str:
    return f"[{plan_label}] {task}"[:120]


def _issue_body(draft: BootstrapDraft, plan_label: str, task: str, index: int) -> str:
    spec = draft.spec
    return (
        f"HydraFlow onboarding task generated from draft `{draft.id}`.\n\n"
        f"Plan: {plan_label}\n"
        f"Sequence: {index}\n"
        f"Target repo: {spec.owner}/{spec.name}\n\n"
        "## Task\n"
        f"{task}\n\n"
        "## Bootstrap Context\n"
        f"- Tech stack: {', '.join(spec.tech_stack) or 'unspecified'}\n"
        f"- Safety guards: {', '.join(spec.safety_guards) or 'standard'}\n"
        f"- Coverage floor: {spec.coverage_floor}%\n"
    )


def _standards_snapshot(draft: BootstrapDraft) -> dict[str, object]:
    spec = draft.spec
    return {
        "schema_version": 1,
        "repo": f"{spec.owner}/{spec.name}",
        "main_branch": spec.main_branch,
        "staging_branch": spec.staging_branch,
        "tech_stack": spec.tech_stack,
        "safety_guards": spec.safety_guards,
        "coverage_floor": spec.coverage_floor,
        "label_prefix": spec.label_prefix,
    }


def _read_snapshot(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def _write_snapshot(path: Path, snapshot: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(snapshot, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


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


async def _open_format_upgrade_pr(
    draft: BootstrapDraft, repo_dir: Path, snapshot: dict[str, object]
) -> str:
    branch = "hydraflow/format-upgrade"
    snapshot_path = repo_dir / ".hydraflow" / "standards-snapshot.json"

    await _run_checked(
        ["git", "fetch", "origin", draft.spec.staging_branch], cwd=repo_dir
    )
    await _run_checked(
        ["git", "checkout", "-B", branch, f"origin/{draft.spec.staging_branch}"],
        cwd=repo_dir,
        timeout=30,
    )
    _write_snapshot(snapshot_path, snapshot)
    await _run_checked(
        ["git", "add", str(snapshot_path.relative_to(repo_dir))], cwd=repo_dir
    )
    await _run_checked(
        ["git", "commit", "-m", "Update HydraFlow format standards snapshot"],
        cwd=repo_dir,
        timeout=60,
    )
    await _run_checked(
        ["git", "push", "-u", "origin", branch, "--force-with-lease"], cwd=repo_dir
    )
    pr_url = await _run_checked(
        [
            "gh",
            "pr",
            "create",
            "--base",
            draft.spec.staging_branch,
            "--head",
            branch,
            "--title",
            "chore: upgrade HydraFlow format",
            "--body",
            (
                "Updates the HydraFlow standards snapshot generated by the "
                "onboarding upgrade workflow."
            ),
        ],
        cwd=repo_dir,
        timeout=120,
    )
    await _run_checked(
        ["git", "checkout", draft.spec.main_branch], cwd=repo_dir, timeout=30
    )
    return pr_url


async def _upgrade_format_response(
    ctx: RouteContext, draft: BootstrapDraft
) -> JSONResponse:
    if draft.materialize_status != "succeeded":
        return JSONResponse(
            {
                "error": "Draft must be materialized before format upgrade",
                "draft": draft.model_dump(mode="json"),
            },
            status_code=409,
        )
    if draft.push_status != "succeeded":
        return JSONResponse(
            {
                "error": "Draft must be pushed before opening a format upgrade PR",
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

    snapshot = _standards_snapshot(draft)
    snapshot_path = repo_dir / ".hydraflow" / "standards-snapshot.json"
    if _read_snapshot(snapshot_path) == snapshot:
        draft.events.append(
            {"level": "info", "message": "format standards already up to date"}
        )
        _persist_draft(ctx, draft)
        return JSONResponse(
            {
                "draft": draft.model_dump(mode="json"),
                "status": "up_to_date",
                "changed": False,
            }
        )

    draft.events.append({"level": "info", "message": "format upgrade started"})
    _persist_draft(ctx, draft)

    try:
        pr_url = await _open_format_upgrade_pr(draft, repo_dir, snapshot)
    except RuntimeError as exc:
        draft.events.append({"level": "error", "message": str(exc)})
        _persist_draft(ctx, draft)
        return JSONResponse(
            {
                "error": "Format upgrade PR could not be opened",
                "draft": draft.model_dump(mode="json"),
            },
            status_code=502,
        )

    draft.events.append({"level": "info", "message": "format upgrade PR opened"})
    _persist_draft(ctx, draft)
    return JSONResponse(
        {
            "draft": draft.model_dump(mode="json"),
            "status": "pr_opened",
            "changed": True,
            "pr_url": pr_url,
        }
    )


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

        result = await _apply_design_turn(ctx, draft, request)
        if isinstance(result, JSONResponse):
            return result
        updated_draft, turn = result
        return JSONResponse(_chat_response_payload(updated_draft, turn))

    @router.post(
        "/api/onboarding/drafts/{draft_id}/design/chat/stream", response_model=None
    )
    async def stream_onboarding_draft_chat(
        draft_id: str, request: DesignChatRequest
    ) -> StreamingResponse | JSONResponse:
        raw = ctx.state.get_onboarding_draft(draft_id)
        if raw is None:
            return JSONResponse({"error": "Draft not found"}, status_code=404)
        draft = _decode_draft(raw)
        if draft is None:
            return JSONResponse({"error": "Draft is invalid"}, status_code=500)

        result = await _apply_design_turn(ctx, draft, request)
        if isinstance(result, JSONResponse):
            return result
        updated_draft, turn = result

        async def generate():
            reply = turn.reply or ""
            for index in range(0, len(reply), 32):
                chunk = reply[index : index + 32]
                yield json.dumps({"type": "reply_delta", "text": chunk}) + "\n"
                await asyncio.sleep(0)
            yield (
                json.dumps(
                    {"type": "final", **_chat_response_payload(updated_draft, turn)}
                )
                + "\n"
            )

        return StreamingResponse(
            generate(),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-cache"},
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

    @router.post("/api/onboarding/drafts/{draft_id}/design/spec/save")
    async def save_onboarding_spec_draft(
        draft_id: str, request: SaveSpecDraftRequest
    ) -> JSONResponse:
        draft, error_response = _load_draft_response(ctx, draft_id)
        if error_response is not None:
            return error_response
        assert draft is not None

        draft.spec_draft = request.spec_draft
        draft.events.append({"level": "info", "message": "wizard spec edits saved"})
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

    @router.post("/api/onboarding/drafts/{draft_id}/continue-plan")
    async def continue_onboarding_plan(
        draft_id: str, request: ContinuePlanRequest | None = None
    ) -> JSONResponse:
        raw = ctx.state.get_onboarding_draft(draft_id)
        if raw is None:
            return JSONResponse({"error": "Draft not found"}, status_code=404)
        draft = _decode_draft(raw)
        if draft is None:
            return JSONResponse({"error": "Draft is invalid"}, status_code=500)

        next_plan = _next_plan_label(request.current_plan if request else None)
        note_parts = [f"Continue onboarding with {next_plan}."]
        if request and request.note:
            note_parts.append(request.note)
        plan_tasks = design_ai.draft_plan(draft, " ".join(note_parts))
        labels = [f"{draft.spec.label_prefix}-find"]
        created_issues: list[dict[str, object]] = []

        draft.events.append(
            {"level": "info", "message": f"{next_plan} issue creation started"}
        )
        _persist_draft(ctx, draft)

        try:
            for index, task in enumerate(plan_tasks, start=1):
                issue_number = await ctx.pr_manager.create_issue(
                    title=_issue_title(next_plan, task),
                    body=_issue_body(draft, next_plan, task, index),
                    labels=labels,
                )
                if issue_number is None:
                    raise RuntimeError("GitHub issue creation returned no issue number")
                created_issues.append(
                    {
                        "number": issue_number,
                        "title": _issue_title(next_plan, task),
                        "task": task,
                    }
                )
        except Exception as exc:  # pragma: no cover - defensive around PRPort impls
            draft.events.append({"level": "error", "message": str(exc)})
            _persist_draft(ctx, draft)
            return JSONResponse(
                {
                    "error": "Next plan issues could not be created",
                    "draft": draft.model_dump(mode="json"),
                    "created_issues": created_issues,
                },
                status_code=502,
            )

        draft.current_plan = next_plan
        draft.plan_draft = plan_tasks
        draft.events.append(
            {
                "level": "info",
                "message": f"{next_plan} filed {len(created_issues)} hydraflow-find issues",
            }
        )
        _persist_draft(ctx, draft)
        return JSONResponse(
            {
                "draft": draft.model_dump(mode="json"),
                "plan": next_plan,
                "plan_draft": plan_tasks,
                "created_issues": created_issues,
            }
        )

    @router.post("/api/onboarding/drafts/{draft_id}/upgrade-format")
    async def upgrade_onboarding_format(draft_id: str) -> JSONResponse:
        draft, error_response = _load_draft_response(ctx, draft_id)
        if error_response is not None:
            return error_response
        assert draft is not None
        return await _upgrade_format_response(ctx, draft)

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

    @router.post(
        "/api/onboarding/drafts/{draft_id}/materialize/stream", response_model=None
    )
    async def stream_materialize_onboarding_draft(
        draft_id: str, request: MaterializeRequest | None = None
    ) -> StreamingResponse | JSONResponse:
        raw = ctx.state.get_onboarding_draft(draft_id)
        if raw is None:
            return JSONResponse({"error": "Draft not found"}, status_code=404)
        draft = _decode_draft(raw)
        if draft is None:
            return JSONResponse({"error": "Draft is invalid"}, status_code=500)
        initial_event_count = len(draft.events)

        async def generate():
            yield (
                json.dumps(
                    _operation_event_payload(
                        {"level": "info", "message": "materialize queued"}
                    )
                )
                + "\n"
            )
            await asyncio.sleep(0)
            response = await materialize_onboarding_draft(draft_id, request)
            payload = _json_response_payload(response)
            draft_payload = payload.get("draft") if isinstance(payload, dict) else None
            events = (
                draft_payload.get("events", [])
                if isinstance(draft_payload, dict)
                else []
            )
            if isinstance(events, list):
                for event in events[initial_event_count:]:
                    yield json.dumps(_operation_event_payload(event)) + "\n"
                    await asyncio.sleep(0)
            final_payload = {
                "type": "final",
                "ok": response.status_code < 400,
                "status": response.status_code,
                **payload,
            }
            yield json.dumps(final_payload) + "\n"

        return StreamingResponse(
            generate(),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-cache"},
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

    @router.post("/api/onboarding/drafts/{draft_id}/push/stream", response_model=None)
    async def stream_push_onboarding_draft(
        draft_id: str,
    ) -> StreamingResponse | JSONResponse:
        raw = ctx.state.get_onboarding_draft(draft_id)
        if raw is None:
            return JSONResponse({"error": "Draft not found"}, status_code=404)
        draft = _decode_draft(raw)
        if draft is None:
            return JSONResponse({"error": "Draft is invalid"}, status_code=500)
        initial_event_count = len(draft.events)

        async def generate():
            yield (
                json.dumps(
                    _operation_event_payload(
                        {"level": "info", "message": "push queued"}
                    )
                )
                + "\n"
            )
            await asyncio.sleep(0)
            response = await push_onboarding_draft(draft_id)
            payload = _json_response_payload(response)
            draft_payload = payload.get("draft") if isinstance(payload, dict) else None
            events = (
                draft_payload.get("events", [])
                if isinstance(draft_payload, dict)
                else []
            )
            if isinstance(events, list):
                for event in events[initial_event_count:]:
                    yield json.dumps(_operation_event_payload(event)) + "\n"
                    await asyncio.sleep(0)
            final_payload = {
                "type": "final",
                "ok": response.status_code < 400,
                "status": response.status_code,
                **payload,
            }
            yield json.dumps(final_payload) + "\n"

        return StreamingResponse(
            generate(),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-cache"},
        )
