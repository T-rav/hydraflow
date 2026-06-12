"""Route handlers for the HydraFlow dashboard API."""

from __future__ import annotations

import asyncio
import contextlib
import copy
import hashlib
import hmac
import json
import logging
import math
import os
import re
import sys
import tempfile
import time
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, cast

from fastapi import (
    APIRouter,
    HTTPException,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from admin_tasks import TaskResult
from app_version import get_app_version
from config import Credentials, HydraFlowConfig
from dashboard_routes._common import (
    _EPIC_INTERNAL_LABELS,
    _FRONTEND_STAGE_TO_LABEL_FIELD,
    _INFERENCE_COUNTER_KEYS,
    _STAGE_NAME_MAP,
    _coerce_history_status,
    _coerce_int,
    _extract_field_from_sources,
    _is_timestamp_in_range,
    _parse_iso_or_none,
    _status_sort_key,
)
from events import EventBus, EventType, HydraFlowEvent
from exception_classify import reraise_on_credit_or_bug
from github_cache_loop import GitHubDataCache
from issue_fetcher import IssueFetcher
from models import (
    BGWorkerHealth,
    GitHubIssue,
    HITLEscalationPayload,
    IntentRequest,
    IntentResponse,
    IssueHistoryEntry,
    IssueHistoryLink,
    IssueHistoryPR,
    IssueHistoryResponse,
    IssueOutcome,
    IssueOutcomeType,
    PipelineIssue,
    PipelineSnapshot,
    PipelineStats,
    QueueStats,
    parse_task_links,
)
from ports import PRPort
from pr_manager import PRManager
from prompt_telemetry import PromptTelemetry
from route_types import REPO_ALL, RepoSlugParam
from state import StateTracker
from timeline import TimelineBuilder
from transcript_summarizer import TranscriptSummarizer

if TYPE_CHECKING:
    from orchestrator import HydraFlowOrchestrator
from dashboard_routes._stats_merge import (
    merge_lifetime_stats,
    merge_pipeline_stats,
    merge_queue_stats,
)
from repo_runtime import RepoRuntime, RepoRuntimeRegistry
from repo_store import RepoRecord, RepoStore

logger = logging.getLogger("hydraflow.dashboard")


async def _run_dialog_command(*cmd: str, timeout_seconds: float = 30.0) -> str | None:
    """Run a folder-picker shell command and return trimmed stdout on success."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
    except (FileNotFoundError, OSError, TimeoutError):
        return None
    if proc.returncode != 0:
        return None
    selected = (stdout or b"").decode().strip()
    return selected or None


async def _pick_folder_with_dialog() -> str | None:
    """Open a best-effort native folder picker and return the selected path."""
    # NOTE: avoid Tk-based pickers here. This endpoint may run off the main
    # thread, and macOS AppKit requires UI objects to be created on main thread.
    if sys.platform == "darwin":
        selected = await _run_dialog_command(
            "osascript",
            "-e",
            'POSIX path of (choose folder with prompt "Select repository folder")',
        )
        if selected:
            return selected
    elif sys.platform.startswith("linux"):
        selected = await _run_dialog_command(
            "zenity",
            "--file-selection",
            "--directory",
            "--title=Select repository folder",
        )
        if selected:
            return selected
    elif sys.platform.startswith("win"):
        selected = await _run_dialog_command(
            "powershell",
            "-NoProfile",
            "-Command",
            (
                "[System.Reflection.Assembly]::LoadWithPartialName"
                "('System.Windows.Forms') | Out-Null; "
                "$d = New-Object System.Windows.Forms.FolderBrowserDialog; "
                "if ($d.ShowDialog() -eq 'OK') { Write-Output $d.SelectedPath }"
            ),
        )
        if selected:
            return selected
    return None


def _allowed_repo_roots() -> tuple[str, ...]:
    """Return normalized filesystem roots that repo browsing is allowed within."""
    roots = [
        os.path.realpath(str(Path.home())),
        os.path.realpath(tempfile.gettempdir()),
    ]
    deduped: list[str] = []
    for root in roots:
        if root not in deduped:
            deduped.append(root)
    return tuple(deduped)


def _normalize_allowed_dir(
    raw_path: str | None,
    allowed_roots: tuple[str, ...] | None = None,
) -> tuple[Path | None, str | None]:
    """Validate and normalize a directory path constrained to allowed roots.

    Parameters
    ----------
    allowed_roots:
        Override the default roots returned by :func:`_allowed_repo_roots`.
        Useful for testing without patching private module internals.
    """
    candidate = (raw_path or "").strip()
    if not candidate:
        return None, "path required"
    expanded = os.path.expanduser(candidate)
    if "\x00" in expanded:
        return None, "invalid path"
    candidate_abs = os.path.abspath(expanded)
    for root in allowed_roots if allowed_roots is not None else _allowed_repo_roots():
        root_real = os.path.realpath(root)
        with contextlib.suppress(ValueError):
            relative = os.path.relpath(candidate_abs, root_real)
            if relative == os.pardir or relative.startswith(f"{os.pardir}{os.sep}"):
                continue
            parts = [part for part in Path(relative).parts if part not in ("", ".")]
            if any(part == os.pardir for part in parts):
                continue
            resolved = Path(root_real).joinpath(*parts).resolve(strict=False)
            if os.path.commonpath([str(resolved), root_real]) != root_real:
                continue
            return resolved, None
    return None, "path must be inside your home directory or temp directory"


def _event_issue_number(data: Mapping[str, Any]) -> int | None:
    """Extract the issue number from an event data dict, coercing strings."""
    value = data.get("issue")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _normalise_event_status(
    event_type: EventType, data: Mapping[str, Any]
) -> str | None:
    """Map an event type and its data to a normalised history status string."""
    status = str(data.get("status", "")).lower()
    result: str | None = None
    if event_type == EventType.MERGE_UPDATE:
        result = "merged" if status == "merged" else None
    elif event_type == EventType.HITL_ESCALATION:
        result = "hitl"
    elif event_type == EventType.HITL_UPDATE:
        result = "reviewed" if status == "resolved" else "hitl"
    elif event_type == EventType.REVIEW_UPDATE:
        if status == "done":
            result = "reviewed"
        elif status == "failed":
            result = "failed"
        else:
            result = "active"
    elif event_type in {
        EventType.WORKER_UPDATE,
        EventType.PLANNER_UPDATE,
        EventType.TRIAGE_UPDATE,
    }:
        if status == "done":
            done_map = {
                EventType.WORKER_UPDATE: "implemented",
                EventType.PLANNER_UPDATE: "planned",
                EventType.TRIAGE_UPDATE: "triaged",
            }
            result = done_map.get(event_type, "active")
        elif status == "failed":
            result = "failed"
        else:
            result = "active"
    elif event_type == EventType.PR_CREATED:
        result = "in_review"
    return result


def _extract_repo_slug(
    req: dict[str, Any] | None,
    req_query: str | None,
    slug_query: str | None,
    repo_query: str | None,
) -> str:
    """Extract repo slug from supported request shapes."""
    return _extract_field_from_sources(
        ("slug", "repo"),
        req,
        req_query,
        (slug_query, repo_query),
        query_params_first=True,
    )


def _extract_repo_path(
    req: dict[str, Any] | None,
    req_query: str | None,
    path_query: str | None,
    repo_path_query: str | None,
) -> str:
    """Extract repo path from supported body/query payload shapes."""
    return _extract_field_from_sources(
        ("path", "repo_path"),
        req,
        req_query,
        (path_query, repo_path_query),
        query_params_first=False,
    )


_ISSUE_URL_RE = re.compile(r"https://github\.com/[^/\s]+/[^/\s]+/issues/(\d+)")


def _extract_issue_number(url: str) -> int:
    """Extract the issue number from a GitHub issue URL, or return 0."""
    m = _ISSUE_URL_RE.search(url)
    return int(m.group(1)) if m else 0


def _is_likely_disconnect(exc: BaseException) -> bool:
    """Return True if *exc* looks like a normal WebSocket disconnect rather than a code bug."""
    disconnect_types = (
        ConnectionResetError,
        ConnectionAbortedError,
        BrokenPipeError,
    )
    if isinstance(exc, disconnect_types):
        return True
    name = type(exc).__name__
    # Starlette / uvicorn raise these on unclean disconnects.
    return name in {
        "WebSocketDisconnect",
        "ConnectionClosedError",
        "ConnectionClosedOK",
    }


# Per-bus subscriber queue depth; the merged ``repo=__all__`` socket sizes its
# shared fan-in queue at ``N × this`` so a busy line can't starve the others.
_WS_MERGED_PER_BUS_QUEUE = 500

# A resolve_runtimes 5-tuple: (config, state, event_bus, get_orch, slug).
_Runtime = tuple[Any, Any, Any, Callable[[], Any], str]


def _merge_sorted_history(runtimes: list[_Runtime]) -> list[HydraFlowEvent]:
    """Merge every runtime's event history into one ``(timestamp, id)``-sorted list.

    Each event is stamped with its bus's repo slug when it isn't already tagged
    (``set_repo`` tags live events, but legacy/untagged history is normalized
    here). A bus that fails to yield history (a down/unstarted repo) is skipped —
    a single bad line must never sink the merged backfill. The id is the tie
    breaker because the module-global ``_event_counter`` only approximates
    wall-clock order across buses.
    """
    events: list[HydraFlowEvent] = []
    for _cfg, _state, bus, _get_orch, slug in runtimes:
        try:
            history = bus.get_history()
        except Exception:  # noqa: BLE001 — a down repo must not sink the merge
            logger.warning("merged WS: skipping history for repo %s", slug)
            continue
        for event in history:
            events.append(
                event
                if event.repo is not None
                else event.model_copy(update={"repo": slug})
            )
    events.sort(key=lambda e: (e.timestamp, e.id))
    return events


async def _forward_to_merged(
    src: asyncio.Queue[HydraFlowEvent],
    dst: asyncio.Queue[HydraFlowEvent],
    slug: str,
) -> None:
    """Forward live frames from one bus's queue into the shared merged queue.

    Stamps the repo slug when missing and drops the oldest frame on a full
    shared queue (mirroring ``EventBus.publish``'s slow-subscriber policy) so a
    single repo can't block the fan-in. Cancelled when the socket closes.
    """
    while True:
        event = await src.get()
        if event.repo is None:
            event = event.model_copy(update={"repo": slug})
        try:
            dst.put_nowait(event)
        except asyncio.QueueFull:
            with contextlib.suppress(asyncio.QueueEmpty):
                dst.get_nowait()
            with contextlib.suppress(asyncio.QueueFull):
                dst.put_nowait(event)


async def _serve_merged_ws(ws: WebSocket, runtimes: list[_Runtime]) -> None:
    """Stream a merged, repo-tagged event feed across every runtime's bus.

    Sends a ``(timestamp, id)``-sorted history backfill, then fans every bus's
    live subscription into one shared queue. A repo whose subscription fails is
    skipped (never a 1008 close — that would stop the frontend reconnect for the
    whole aggregate view). The single-repo fast path is handled by the caller.

    Note on ordering/dedup: ``event.id`` is unique only within a process'
    *live* stream (one shared counter), but persisted history from independent
    past sessions can reuse ids across repos. The merged feed therefore streams
    every frame repo-tagged and lets the client de-collide on ``(repo, id)`` —
    it never drops a frame here. Timestamps are uniformly UTC ISO-8601, so the
    lexicographic ``(timestamp, id)`` sort is chronological.
    """
    await ws.accept()
    if not runtimes:
        # Degenerate empty-aggregate view (no registered runtimes): close
        # cleanly instead of holding a socket the out-queue can never feed.
        # In practice the empty-registry guard (#9359) yields the default
        # runtime, so this only triggers defensively.
        with contextlib.suppress(Exception):
            await ws.close(code=1000)
        return
    history = _merge_sorted_history(runtimes)
    out_queue: asyncio.Queue[HydraFlowEvent] = asyncio.Queue(
        maxsize=max(1, len(runtimes)) * _WS_MERGED_PER_BUS_QUEUE
    )
    forwarders: list[asyncio.Task[None]] = []
    async with contextlib.AsyncExitStack() as stack:
        for _cfg, _state, bus, _get_orch, slug in runtimes:
            try:
                queue = await stack.enter_async_context(bus.subscription())
            except Exception:  # noqa: BLE001 — skip a down repo, keep the socket
                logger.warning("merged WS: skipping live feed for repo %s", slug)
                continue
            forwarders.append(
                asyncio.create_task(_forward_to_merged(queue, out_queue, slug))
            )
        try:
            for event in history:
                await ws.send_text(event.model_dump_json())
            while True:
                event = await out_queue.get()
                await ws.send_text(event.model_dump_json())
        except WebSocketDisconnect:
            pass
        except Exception as exc:  # noqa: BLE001
            if _is_likely_disconnect(exc):
                logger.warning(
                    "WebSocket disconnect during merged streaming: %s",
                    exc.__class__.__name__,
                )
            else:
                logger.error(
                    "WebSocket error during merged streaming: %s",
                    exc.__class__.__name__,
                    exc_info=True,
                )
        finally:
            for task in forwarders:
                task.cancel()
            # Await the cancellations so the buses are unsubscribed (AsyncExitStack
            # exit) only after their forwarders have actually stopped reading.
            await asyncio.gather(*forwarders, return_exceptions=True)


@dataclass
class RouteContext:
    """Bundles all dependencies needed by dashboard route handlers.

    Replaces the closure-capture pattern used by ``create_router()`` so that
    sub-routers can receive an explicit context object instead of relying on
    17+ closure variables.  This is a prerequisite for decomposing the
    monolithic router into smaller sub-router modules.
    """

    # Core services
    config: HydraFlowConfig
    credentials: Credentials
    event_bus: EventBus
    state: StateTracker
    pr_manager: PRPort

    # Orchestrator lifecycle callbacks
    get_orchestrator: Callable[[], HydraFlowOrchestrator | None]
    set_orchestrator: Callable[[HydraFlowOrchestrator], None]
    set_run_task: Callable[[asyncio.Task[None]], None]

    # Static asset directories
    ui_dist_dir: Path
    template_dir: Path

    # Multi-repo support
    registry: RepoRuntimeRegistry | None = None
    repo_store: RepoStore | None = None
    register_repo_cb: (
        Callable[[Path, str | None], Awaitable[tuple[RepoRecord, HydraFlowConfig]]]
        | None
    ) = None
    remove_repo_cb: Callable[[str], Awaitable[bool]] | None = None
    list_repos_cb: Callable[[], list[RepoRecord]] | None = None
    default_repo_slug: str | None = None
    allowed_repo_roots_fn: Callable[[], tuple[str, ...]] | None = None

    # HITL summary tuning
    hitl_summary_cooldown_seconds: int = 300

    # Derived state — initialised in __post_init__
    issue_fetcher: IssueFetcher = field(init=False)
    hitl_summarizer: TranscriptSummarizer = field(init=False)
    # Keys are bare ``int`` issue numbers on the host path and
    # ``(repo_slug, issue)`` tuples on repo-scoped paths (see warm_hitl_summary).
    hitl_summary_inflight: set[object] = field(init=False)
    hitl_summary_slots: asyncio.Semaphore = field(init=False)

    def __post_init__(self) -> None:
        self.issue_fetcher = IssueFetcher(self.config, credentials=self.credentials)
        # TranscriptSummarizer's __init__ is annotated PRManager (concrete);
        # production always passes the real adapter. Narrow at the call site
        # rather than expand TranscriptSummarizer's surface.
        self.hitl_summarizer = TranscriptSummarizer(
            self.config,
            cast("PRManager", self.pr_manager),
            self.event_bus,
            self.state,
            credentials=self.credentials,
        )
        self.hitl_summary_inflight = set()
        self.hitl_summary_slots = asyncio.Semaphore(3)

    # -- Dependency resolution helpers ------------------------------------------

    def _host_pipeline_active(self) -> bool:
        """Fallback host-pipeline check for single-repo/test wiring (no registry).

        Returns True when no orchestrator exists (headless/test mode).
        """
        orch = self.get_orchestrator()
        if orch is None:
            return True
        if not orch.running:
            return False
        return orch.pipeline_enabled

    def _default_slug(self) -> str:
        """Canonical dash slug for the default (host) repo.

        Prefers the explicitly-wired ``default_repo_slug``, else derives it from
        the host config (``owner/repo`` → ``owner-repo``, or the repo-root name).
        """
        return self.default_repo_slug or (
            self.config.repo.replace("/", "-")
            if self.config.repo
            else self.config.repo_root.name
        )

    def is_repo_pipeline_active(self, slug: str | None) -> bool:
        """Return whether the resolved repo's pipeline is actively processing.

        The host repo is a registered runtime like any other, so this resolves
        purely through the registry. Per the ``None``=default invariant, a
        ``None`` *slug* scopes to the **default** repo; only the ``REPO_ALL``
        sentinel (All repos view) returns True if ANY line is running.
        """
        if self.registry is not None:
            if slug is not None and slug.strip().lower() == REPO_ALL:
                return any(getattr(rt, "running", False) for rt in self.registry.all)
            # None ⇒ the default repo; a slug ⇒ that line. The host repo is a
            # registered runtime, so the default resolves through the registry
            # like any other (absent ⇒ not running).
            resolved = slug if slug is not None else self._default_slug()
            rt = self.registry.get(resolved)
            return getattr(rt, "running", False) if rt is not None else False
        # No registry (single-repo/test wiring): fall back to the host orch.
        return self._host_pipeline_active()

    def resolve_runtime(
        self,
        slug: str | None,
    ) -> tuple[
        HydraFlowConfig,
        StateTracker,
        EventBus,
        Callable[[], HydraFlowOrchestrator | None],
    ]:
        """Resolve per-repo dependencies from the registry.

        When *slug* is ``None``, matches the default repo, or no registry is
        configured, returns the single-repo defaults for backward compatibility.
        """
        if self.registry is not None and slug is not None:
            # The host repo is a registered runtime sharing the app-level
            # bus/state, so registry.get() resolves it just like any other line
            # — no default-repo special case needed.
            rt: RepoRuntime | None = self.registry.get(slug)
            if rt is not None:
                return rt.config, rt.state, rt.event_bus, lambda: rt.orchestrator
            # Also try case-insensitive match before giving up
            slug_lower = slug.lower()
            for registered_rt in self.registry.all:
                if registered_rt.slug.lower() == slug_lower:
                    return (
                        registered_rt.config,
                        registered_rt.state,
                        registered_rt.event_bus,
                        lambda _rt=registered_rt: _rt.orchestrator,
                    )
            # Repo may be registered (in /api/repos) but not yet started
            # (not in the runtime registry). Fall back to defaults so the
            # WS connects and the UI renders — just with no live events.
            logger.debug("Repo %r not in runtime registry — using defaults", slug)
            return self.config, self.state, self.event_bus, self.get_orchestrator
        return self.config, self.state, self.event_bus, self.get_orchestrator

    def resolve_runtimes(
        self,
        slug: str | None,
    ) -> list[
        tuple[
            HydraFlowConfig,
            StateTracker,
            EventBus,
            Callable[[], HydraFlowOrchestrator | None],
            str,
        ]
    ]:
        """Resolve per-repo dependencies for one repo, or every repo.

        - A concrete slug (or ``None``) returns a single-element list, reusing
          :meth:`resolve_runtime` and tagging it with the *resolved* slug (a
          fell-back tuple is tagged with the default slug, never the bogus
          requested slug).
        - ``REPO_ALL`` returns every registered runtime. The host repo is a
          registry member (the server registers it via
          ``RepoRuntime.from_shared``), so no separate default tuple is
          prepended. With no registry it degenerates to the single shared
          default.

        The 5th element is the canonical dash slug for tagging. The 4th element
        is always a zero-arg callable; the no-registry default may return
        ``None`` while registry runtimes yield their live orchestrator —
        consumers must handle ``None``.
        """
        default_slug = self._default_slug()

        if slug is not None and slug.strip().lower() == REPO_ALL:
            if self.registry is not None:
                return [
                    (
                        rt.config,
                        rt.state,
                        rt.event_bus,
                        lambda _rt=rt: _rt.orchestrator,
                        rt.slug,
                    )
                    for rt in self.registry.all
                ]
            return [
                (
                    self.config,
                    self.state,
                    self.event_bus,
                    self.get_orchestrator,
                    default_slug,
                )
            ]

        # Single-repo path. Determine the truthful resolved slug (a fell-back
        # tuple is tagged with the default slug, never the bogus requested
        # slug), then reuse the singular resolver for the dependencies.
        resolved_slug = default_slug
        if slug is not None and self.registry is not None:
            matched = self.registry.get(slug)
            if matched is not None:
                # Tolerate minimal runtime doubles without a slug attr.
                resolved_slug = getattr(matched, "slug", None) or slug
            else:
                slug_lower = slug.lower()
                for rt in self.registry.all:
                    if getattr(rt, "slug", "").lower() == slug_lower:
                        resolved_slug = rt.slug
                        break
        cfg, st, bus, get_orch = self.resolve_runtime(slug)
        return [(cfg, st, bus, get_orch, resolved_slug)]

    async def execute_admin_task(
        self,
        task_name: str,
        task_fn: Callable[[HydraFlowConfig], Awaitable[TaskResult]],
        slug: str | None,
    ) -> JSONResponse:
        """Run an admin task against the resolved repo config."""
        try:
            runtime_config, _, _, _ = self.resolve_runtime(slug)
        except HTTPException:
            return JSONResponse({"error": "Unknown repo"}, status_code=404)
        try:
            result = await task_fn(runtime_config)
        except Exception as exc:  # noqa: BLE001
            reraise_on_credit_or_bug(exc)
            logger.exception("%s task failed", task_name)
            return JSONResponse({"error": f"{task_name} failed"}, status_code=500)
        payload: dict[str, Any] = {"status": "ok", "result": result.as_dict()}
        status_code = 200
        if not result.success:
            payload["status"] = "error"
            status_code = 500
        return JSONResponse(payload, status_code=status_code)

    def pr_manager_for(self, cfg: HydraFlowConfig, bus: EventBus) -> PRPort:
        """Return the shared PRManager when config matches; otherwise create a new one."""
        if cfg is self.config and bus is self.event_bus:
            return self.pr_manager
        return PRManager(cfg, bus)

    def issue_fetcher_for(self, cfg: HydraFlowConfig) -> IssueFetcher:
        """Return the shared IssueFetcher for the host config; else a repo-scoped one.

        Mirrors :meth:`pr_manager_for` so a non-default repo fetches its own
        issues while the host path keeps using the (mockable) shared fetcher.
        """
        if cfg is self.config:
            return self.issue_fetcher
        return IssueFetcher(cfg, credentials=self.credentials)

    def list_repo_records(self) -> list[RepoRecord]:
        """Return repo records from the callback or store, with error fallback."""
        if self.list_repos_cb is not None:
            try:
                return self.list_repos_cb()
            except Exception:  # noqa: BLE001
                logger.warning("list_repos callback failed", exc_info=True)
        if self.repo_store is not None:
            try:
                return self.repo_store.list()
            except Exception:  # noqa: BLE001
                logger.warning("repo_store.list failed", exc_info=True)
        return []

    def serve_spa_index(self) -> HTMLResponse:
        """Serve the SPA index.html, falling back to template or placeholder."""
        react_index = self.ui_dist_dir / "index.html"
        if react_index.exists():
            return HTMLResponse(react_index.read_text())
        template_path = self.template_dir / "index.html"
        if template_path.exists():
            return HTMLResponse(template_path.read_text())
        return HTMLResponse(
            "<h1>HydraFlow Dashboard</h1><p>Run 'make ui' to build.</p>"
        )

    def repo_roots_fn(self) -> tuple[str, ...]:
        """Return the allowed repo roots, using the override if provided."""
        if self.allowed_repo_roots_fn is not None:
            return self.allowed_repo_roots_fn()
        return _allowed_repo_roots()

    def hitl_summary_retry_due(
        self, issue_number: int, *, state: StateTracker | None = None
    ) -> bool:
        """Return True if enough time has passed to retry a failed HITL summary.

        ``state`` defaults to the host state; pass the row's repo state so the
        cooldown is read from the repo that owns the issue (ADR-0007 multi-repo).
        """
        st = state or self.state
        failed_at, _ = st.get_hitl_summary_failure(issue_number)
        failed_dt = _parse_iso_or_none(failed_at)
        if failed_dt is None:
            return True
        age = (datetime.now(UTC) - failed_dt).total_seconds()
        return age >= self.hitl_summary_cooldown_seconds

    async def compute_hitl_summary(
        self,
        issue_number: int,
        *,
        cause: str,
        origin: str | None,
        state: StateTracker | None = None,
        config: HydraFlowConfig | None = None,
        issue_fetcher: IssueFetcher | None = None,
    ) -> str | None:
        """Fetch issue, generate and normalise a HITL summary, then persist to state.

        The ``state``/``config``/``issue_fetcher`` overrides default to the host
        runtime; callers serving a non-default repo MUST pass that repo's objects
        so the issue is fetched from the right GitHub repo and the summary is
        persisted to the right state — otherwise issue #N of repo B would be
        fetched from repo A and stored under A.
        """
        st = state or self.state
        cfg = config or self.config
        fetcher = issue_fetcher or self.issue_fetcher
        if (
            not cfg.transcript_summarization_enabled
            or cfg.dry_run
            or not self.credentials.gh_token
        ):
            return None
        issue = await fetcher.fetch_issue_by_number(issue_number)
        if issue is None:
            st.set_hitl_summary_failure(issue_number, "Issue fetch failed")
            return None
        context = _build_hitl_context(issue, cause=cause, origin=origin)
        generated = await self.hitl_summarizer.summarize_hitl_context(context)
        if not generated:
            st.set_hitl_summary_failure(issue_number, "Summary model returned empty")
            return None
        summary = _normalise_summary_lines(generated)
        if not summary:
            st.set_hitl_summary_failure(
                issue_number, "Summary normalization produced empty output"
            )
            return None
        st.set_hitl_summary(issue_number, summary)
        st.clear_hitl_summary_failure(issue_number)
        return summary

    async def warm_hitl_summary(
        self,
        issue_number: int,
        *,
        cause: str,
        origin: str | None,
        state: StateTracker | None = None,
        config: HydraFlowConfig | None = None,
        issue_fetcher: IssueFetcher | None = None,
    ) -> None:
        """Schedule background HITL summary generation, guarded by inflight tracking.

        Pass the row's repo ``state``/``config``/``issue_fetcher`` for non-default
        repos (see :meth:`compute_hitl_summary`).
        """
        # Key the in-flight guard by (repo_slug, issue) when a repo config is
        # given, so warming repo A's issue #42 does not transiently suppress
        # repo B's issue #42 (same number, different repo). The host path keeps
        # the bare-int key for back-compat.
        inflight_key: object = (
            (config.repo_slug, issue_number) if config is not None else issue_number
        )
        if inflight_key in self.hitl_summary_inflight:
            return
        self.hitl_summary_inflight.add(inflight_key)
        try:
            async with self.hitl_summary_slots:
                await self.compute_hitl_summary(
                    issue_number,
                    cause=cause,
                    origin=origin,
                    state=state,
                    config=config,
                    issue_fetcher=issue_fetcher,
                )
        except Exception as exc:
            (state or self.state).set_hitl_summary_failure(
                issue_number,
                f"{type(exc).__name__}: {exc}",
            )
            logger.exception(
                "Failed to warm HITL summary for issue #%d",
                issue_number,
            )
        finally:
            self.hitl_summary_inflight.discard(inflight_key)


def _build_hitl_context(issue: GitHubIssue, *, cause: str, origin: str | None) -> str:
    """Build a text context block for HITL summary generation."""
    body = (issue.body or "").strip()
    comments = issue.comments
    recent_comments = [str(c).strip() for c in comments[-5:] if str(c).strip()]
    comments_block = "\n".join(f"- {c[:400]}" for c in recent_comments)
    origin_text = origin or "unknown"
    return (
        f"Issue #{issue.number}: {issue.title}\n"
        f"Escalation cause: {cause or 'not recorded'}\n"
        f"Escalation origin: {origin_text}\n\n"
        f"Issue body:\n{body[:6000]}\n\n"
        f"Recent comments:\n{comments_block[:3000]}"
    )


def _normalise_summary_lines(raw: str) -> str:
    """Strip bullet prefixes and cap a summary to 8 lines."""
    lines = [line.strip(" -\t") for line in raw.splitlines() if line.strip()]
    return "\n".join(lines[:8]).strip()


def create_router(
    config: HydraFlowConfig,
    event_bus: EventBus,
    state: StateTracker,
    pr_manager: PRPort,
    get_orchestrator: Callable[[], HydraFlowOrchestrator | None],
    set_orchestrator: Callable[[HydraFlowOrchestrator], None],
    set_run_task: Callable[[asyncio.Task[None]], None],
    ui_dist_dir: Path,
    template_dir: Path,
    *,
    credentials: Credentials | None = None,
    registry: RepoRuntimeRegistry | None = None,
    repo_store: RepoStore | None = None,
    register_repo_cb: Callable[
        [Path, str | None], Awaitable[tuple[RepoRecord, HydraFlowConfig]]
    ]
    | None = None,
    remove_repo_cb: Callable[[str], Awaitable[bool]] | None = None,
    list_repos_cb: Callable[[], list[RepoRecord]] | None = None,
    default_repo_slug: str | None = None,
    allowed_repo_roots_fn: Callable[[], tuple[str, ...]] | None = None,
) -> APIRouter:
    """Create an APIRouter with all dashboard route handlers.

    When *registry* is provided, operational endpoints accept an optional
    ``repo`` query parameter to target a specific repo runtime.  When the
    parameter is omitted, the single-repo defaults (closure-captured
    *config*, *state*, *event_bus*, and *get_orchestrator*) are used for
    backward compatibility.
    """
    # Build the shared RouteContext that bundles all dependencies.
    _creds = credentials or Credentials()
    ctx = RouteContext(
        config=config,
        credentials=_creds,
        event_bus=event_bus,
        state=state,
        pr_manager=pr_manager,
        get_orchestrator=get_orchestrator,
        set_orchestrator=set_orchestrator,
        set_run_task=set_run_task,
        ui_dist_dir=ui_dist_dir,
        template_dir=template_dir,
        registry=registry,
        repo_store=repo_store,
        register_repo_cb=register_repo_cb,
        remove_repo_cb=remove_repo_cb,
        list_repos_cb=list_repos_cb,
        default_repo_slug=default_repo_slug,
        allowed_repo_roots_fn=allowed_repo_roots_fn,
    )

    router = APIRouter()

    # Thin delegates — route handlers call these; logic lives on RouteContext.
    def _resolve_runtime(
        slug: str | None,
    ) -> tuple[
        HydraFlowConfig,
        StateTracker,
        EventBus,
        Callable[[], HydraFlowOrchestrator | None],
    ]:
        return ctx.resolve_runtime(slug)

    def _resolve_runtimes(
        slug: str | None,
    ) -> list[
        tuple[
            HydraFlowConfig,
            StateTracker,
            EventBus,
            Callable[[], HydraFlowOrchestrator | None],
            str,
        ]
    ]:
        return ctx.resolve_runtimes(slug)

    def _is_pipeline_active(slug: str | None) -> bool:
        """Check if the selected repo's pipeline is running.

        A bare ``None`` slug checks the default repo's pipeline state; only the
        ``__all__`` sentinel (All repos view) returns True if any line is
        running. Data only shows when something is actually running.
        """
        return ctx.is_repo_pipeline_active(slug)

    async def _execute_admin_task(
        task_name: str,
        task_fn: Callable[[HydraFlowConfig], Awaitable[TaskResult]],
        slug: str | None,
    ) -> JSONResponse:
        return await ctx.execute_admin_task(task_name, task_fn, slug)

    def _pr_manager_for(cfg: HydraFlowConfig, bus: EventBus) -> PRPort:
        return ctx.pr_manager_for(cfg, bus)

    def _list_repo_records() -> list[RepoRecord]:
        return ctx.list_repo_records()

    def _repo_roots_fn() -> tuple[str, ...]:
        return ctx.repo_roots_fn()

    def _serve_spa_index() -> HTMLResponse:
        return ctx.serve_spa_index()

    def _hitl_summary_retry_due(issue_number: int) -> bool:
        return ctx.hitl_summary_retry_due(issue_number)

    async def _compute_hitl_summary(
        issue_number: int, *, cause: str, origin: str | None
    ) -> str | None:
        return await ctx.compute_hitl_summary(issue_number, cause=cause, origin=origin)

    async def _warm_hitl_summary(
        issue_number: int, *, cause: str, origin: str | None
    ) -> None:
        await ctx.warm_hitl_summary(issue_number, cause=cause, origin=origin)

    def _build_history_links(
        raw: dict[int, dict[str, Any]] | Iterable[Any],
    ) -> list[IssueHistoryLink]:
        """Convert the internal linked_issues accumulator to a sorted list."""
        if isinstance(raw, dict):
            return sorted(
                (
                    IssueHistoryLink(
                        target_id=int(v["target_id"]),
                        kind=v.get("kind", "relates_to"),
                        target_url=v.get("target_url"),
                    )
                    for v in raw.values()
                    if isinstance(v, dict) and _coerce_int(v.get("target_id")) > 0
                ),
                key=lambda lnk: lnk.target_id,
            )
        # Legacy fallback: bare set of ints
        return sorted(
            (IssueHistoryLink(target_id=int(v)) for v in raw if _coerce_int(v) > 0),
            key=lambda lnk: lnk.target_id,
        )

    def _new_issue_history_entry(
        issue_number: int, cfg: HydraFlowConfig
    ) -> dict[str, Any]:
        """Create a blank history aggregation row for an issue."""
        repo_slug = (cfg.repo or "").strip()
        if repo_slug.startswith("https://github.com/"):
            repo_slug = repo_slug[len("https://github.com/") :]
        elif repo_slug.startswith("http://github.com/"):
            repo_slug = repo_slug[len("http://github.com/") :]
        repo_slug = repo_slug.strip("/")
        issue_url = (
            f"https://github.com/{repo_slug}/issues/{issue_number}" if repo_slug else ""
        )
        return {
            "issue_number": issue_number,
            "title": f"Issue #{issue_number}",
            "issue_url": issue_url,
            "status": "unknown",
            "epic": "",
            "crate_number": None,
            "crate_title": "",
            "linked_issues": {},
            "prs": {},
            "session_ids": set(),
            "source_calls": {},
            "model_calls": {},
            "inference": dict.fromkeys(_INFERENCE_COUNTER_KEYS, 0),
            "first_seen": None,
            "last_seen": None,
            "status_updated_at": None,
        }

    def _touch_issue_timestamps(row: dict[str, Any], timestamp: str | None) -> None:
        """Update the first_seen / last_seen bounds of a history row."""
        if not timestamp:
            return
        current_first = row.get("first_seen")
        current_last = row.get("last_seen")
        if not isinstance(current_first, str) or timestamp < current_first:
            row["first_seen"] = timestamp
        if not isinstance(current_last, str) or timestamp > current_last:
            row["last_seen"] = timestamp

    def _build_issue_history_entry(
        row: dict[str, Any],
        outcome: IssueOutcome | None,
        repo_slug: str = "",
    ) -> IssueHistoryEntry:
        """Build an ``IssueHistoryEntry`` from a raw aggregation row."""
        issue_number = int(row["issue_number"])
        title = str(row.get("title", f"Issue #{issue_number}"))
        row_status = str(row.get("status", "unknown")).lower()

        linked_issues = _build_history_links(row.get("linked_issues", {}))
        prs_map = row.get("prs", {})
        if not isinstance(prs_map, dict):
            prs_map = {}
        pr_rows = sorted(
            (
                IssueHistoryPR(
                    number=int(pr_data["number"]),
                    url=str(pr_data.get("url", "")),
                    merged=bool(pr_data.get("merged", False)),
                    title=str(pr_data.get("title", "")),
                )
                for pr_data in prs_map.values()
                if isinstance(pr_data, dict) and _coerce_int(pr_data.get("number")) > 0
            ),
            key=lambda p: p.number,
            reverse=True,
        )

        return IssueHistoryEntry(
            issue_number=issue_number,
            title=title,
            issue_url=str(row.get("issue_url", "")),
            status=_coerce_history_status(row_status),
            epic=str(row.get("epic", "")),
            crate_number=row.get("crate_number"),
            crate_title=str(row.get("crate_title", "")),
            linked_issues=linked_issues,
            prs=pr_rows,
            session_ids=sorted(str(s) for s in row.get("session_ids", set()) if str(s)),
            source_calls=dict(sorted(row.get("source_calls", {}).items())),
            model_calls=dict(sorted(row.get("model_calls", {}).items())),
            inference={k: _coerce_int(v) for k, v in row.get("inference", {}).items()},
            first_seen=row.get("first_seen"),
            last_seen=row.get("last_seen"),
            outcome=outcome,
            repo=repo_slug,
        )

    def _aggregate_telemetry_record(
        row: dict[str, Any],
        record: dict[str, Any],
        pr_to_issue: dict[int, int],
        *,
        sum_counters: bool = False,
    ) -> None:
        """Extract shared metadata from a telemetry record into *row*.

        When *sum_counters* is True the inference counter keys are also
        accumulated (used in the per-record path).  The rollup path only
        needs metadata so it passes ``sum_counters=False``.
        """
        issue_number = int(row["issue_number"])
        timestamp = record.get("timestamp")
        _touch_issue_timestamps(row, timestamp if isinstance(timestamp, str) else None)

        session_id = str(record.get("session_id", "")).strip()
        if session_id:
            row["session_ids"].add(session_id)

        source = str(record.get("source", "")).strip()
        if source:
            row["source_calls"][source] = row["source_calls"].get(source, 0) + 1

        model = str(record.get("model", "")).strip()
        if model:
            row["model_calls"][model] = row["model_calls"].get(model, 0) + 1

        if sum_counters:
            for key in _INFERENCE_COUNTER_KEYS:
                row["inference"][key] += _coerce_int(record.get(key))

        pr_number = _coerce_int(record.get("pr_number"))
        if pr_number > 0:
            prs: dict[int, dict[str, Any]] = row["prs"]
            if pr_number not in prs:
                prs[pr_number] = {
                    "number": pr_number,
                    "url": "",
                    "merged": False,
                }
            pr_to_issue.setdefault(pr_number, issue_number)

    def _process_events_into_rows(
        events: list[Any],
        issue_rows: dict[int, dict[str, Any]],
        pr_to_issue: dict[int, int],
        since_dt: datetime | None,
        until_dt: datetime | None,
        cfg: HydraFlowConfig,
    ) -> None:
        """Process event-bus events into *issue_rows* in place."""
        for event in events:
            timestamp = event.timestamp
            if not _is_timestamp_in_range(timestamp, since_dt, until_dt):
                continue

            issue_number = _event_issue_number(event.data)
            if issue_number is None and event.type == EventType.MERGE_UPDATE:
                pr_num = _coerce_int(event.data.get("pr"))
                issue_number = pr_to_issue.get(pr_num)

            if issue_number is None or issue_number <= 0:
                continue

            row = issue_rows.setdefault(
                issue_number, _new_issue_history_entry(issue_number, cfg)
            )
            _touch_issue_timestamps(row, timestamp)

            maybe_title = str(event.data.get("title", "")).strip()
            if maybe_title:
                row["title"] = maybe_title

            maybe_url = str(event.data.get("url", "")).strip()
            if maybe_url.startswith(("http://", "https://")):
                row["issue_url"] = maybe_url

            if event.type == EventType.ISSUE_CREATED:
                labels = event.data.get("labels", [])
                if isinstance(labels, list) and not row.get("epic"):
                    for lbl in labels:
                        s = str(lbl).strip()
                        if (
                            s
                            and "epic" in s.lower()
                            and s.lower() not in _EPIC_INTERNAL_LABELS
                        ):
                            row["epic"] = s
                            break
                milestone_num = _coerce_int(event.data.get("milestone_number"))
                if milestone_num > 0 and not row.get("crate_number"):
                    row["crate_number"] = milestone_num

            if event.type == EventType.PR_CREATED:
                pr_number = _coerce_int(event.data.get("pr"))
                if pr_number > 0:
                    pr_to_issue[pr_number] = issue_number
                    prs = row["prs"]
                    payload = prs.get(
                        pr_number,
                        {"number": pr_number, "url": "", "merged": False},
                    )
                    url = str(event.data.get("url", "")).strip()
                    if url.startswith(("http://", "https://")):
                        payload["url"] = url
                    pr_title = str(event.data.get("title", "")).strip()
                    if pr_title:
                        payload["title"] = pr_title
                    prs[pr_number] = payload

            if event.type == EventType.MERGE_UPDATE:
                pr_number = _coerce_int(event.data.get("pr"))
                if pr_number > 0:
                    prs = row["prs"]
                    payload = prs.get(
                        pr_number,
                        {"number": pr_number, "url": "", "merged": False},
                    )
                    if str(event.data.get("status", "")).lower() == "merged":
                        payload["merged"] = True
                    merge_title = str(event.data.get("title", "")).strip()
                    if merge_title:
                        payload["title"] = merge_title
                    prs[pr_number] = payload

            normalised = _normalise_event_status(event.type, event.data)
            if normalised:
                current = str(row.get("status", "unknown"))
                current_ts = (
                    row.get("status_updated_at")
                    if isinstance(row.get("status_updated_at"), str)
                    else None
                )
                if _status_sort_key(normalised, timestamp) >= _status_sort_key(
                    current, current_ts
                ):
                    row["status"] = normalised
                    row["status_updated_at"] = timestamp

    def _filter_rows_to_items(
        issue_rows: dict[int, dict[str, Any]],
        requested_status: str,
        query_text: str,
        state: StateTracker,
        repo_slug: str = "",
    ) -> list[IssueHistoryEntry]:
        """Filter *issue_rows* and convert to ``IssueHistoryEntry`` objects."""
        items: list[IssueHistoryEntry] = []
        for row in issue_rows.values():
            row_status = str(row.get("status", "unknown")).lower()
            if requested_status and row_status != requested_status:
                continue

            issue_number = int(row["issue_number"])
            title = str(row.get("title", f"Issue #{issue_number}"))
            if (
                query_text
                and query_text not in title.lower()
                and query_text not in str(issue_number)
            ):
                continue

            items.append(
                _build_issue_history_entry(
                    row, state.get_outcome(issue_number), repo_slug
                )
            )
        return items

    async def _apply_enrichment_and_crate_titles(
        items: list[IssueHistoryEntry],
        issue_rows: dict[int, dict[str, Any]],
        requested_status: str,
        query_text: str,
        use_unfiltered: bool,
        *,
        cfg: HydraFlowConfig,
        bus: EventBus,
        state: StateTracker,
        repo_slug: str,
        use_cache: bool,
    ) -> list[IssueHistoryEntry]:
        """Enrich items via GitHub and backfill crate titles from milestones.

        Runs against the runtime's own *cfg*/*state*/PR manager. The persistent
        ``_history_cache`` (enriched-issue set + cached rows) is keyed to the
        default runtime only, so it is read/written exclusively when *use_cache*
        is True — per-repo / ``__all__`` requests track enrichment locally and
        never mutate the default cache.

        Returns a (potentially rebuilt) items list.
        """
        already_enriched: set[int] = (
            _history_cache.get("enriched_issues", set()) if use_cache else set()
        )
        issue_lookup = {
            item.issue_number: issue_rows[item.issue_number] for item in items
        }
        enrich_candidates = [
            item.issue_number
            for item in items
            if item.issue_number not in already_enriched
            and (
                not item.issue_url
                or item.title.startswith("Issue #")
                or (not item.epic and not item.linked_issues)
            )
        ][:40]
        if enrich_candidates:
            await _enrich_issue_history_with_github(
                {k: issue_lookup[k] for k in enrich_candidates}, cfg
            )
            already_enriched.update(enrich_candidates)
            if use_cache:
                _history_cache["enriched_issues"] = already_enriched
                if use_unfiltered and _history_cache["issue_rows"] is not None:
                    _history_cache["issue_rows"] = copy.deepcopy(issue_rows)
                    _save_history_cache()
            # Rebuild items from enriched rows.
            items = _filter_rows_to_items(
                issue_rows, requested_status, query_text, state, repo_slug
            )

        # Sort before crate-title backfill so milestone fetches are done
        # after ordering.  The caller applies the page limit after returning.
        items.sort(
            key=lambda item: (
                item.last_seen or "",
                item.inference.get("total_tokens", 0),
                item.issue_number,
            ),
            reverse=True,
        )

        # Populate crate titles from milestones for items that have a
        # crate_number but no title yet.
        needs_title = any(i.crate_number and not i.crate_title for i in items)
        if needs_title:
            try:
                # ``list_milestones`` is concrete-only on PRManager.
                manager = _pr_manager_for(cfg, bus)
                milestones = await cast("PRManager", manager).list_milestones(
                    state="all"
                )
                title_map = {m.number: m.title for m in milestones}
                items = [
                    i.model_copy(
                        update={"crate_title": title_map.get(i.crate_number, "")}
                    )
                    if i.crate_number and not i.crate_title
                    else i
                    for i in items
                ]
                # Also backfill into the raw rows so the cache carries titles.
                backfilled = False
                for i in items:
                    if i.crate_number and i.crate_title:
                        raw = issue_rows.get(i.issue_number)
                        if raw is not None and raw.get("crate_title") != i.crate_title:
                            raw["crate_title"] = i.crate_title
                            backfilled = True
                if (
                    backfilled
                    and use_cache
                    and use_unfiltered
                    and _history_cache.get("issue_rows") is not None
                ):
                    _history_cache["issue_rows"] = copy.deepcopy(issue_rows)
                    _save_history_cache()
            except Exception:
                logger.warning(
                    "Failed to fetch milestones for crate titles", exc_info=True
                )

        # Backfill epic field from state's epic tracking when not already set.
        epic_states = state.get_all_epic_states()
        if epic_states:
            child_to_epic: dict[int, str] = {}
            for es in epic_states.values():
                title = es.title or f"Epic #{es.epic_number}"
                for child in es.child_issues:
                    child_to_epic[child] = title
            if child_to_epic:
                items = [
                    i.model_copy(update={"epic": child_to_epic[i.issue_number]})
                    if not i.epic and i.issue_number in child_to_epic
                    else i
                    for i in items
                ]

        # Derive outcome for issues that completed the pipeline (have a
        # merged PR) but were never given an explicit record_outcome() call.
        items = [
            i.model_copy(
                update={
                    "outcome": IssueOutcome(
                        outcome=IssueOutcomeType.MERGED,
                        reason="Derived from merged PR",
                        closed_at=i.last_seen or "",
                        pr_number=next((p.number for p in i.prs if p.merged), None),
                        phase="review",
                    )
                }
            )
            if not i.outcome and any(p.merged for p in i.prs)
            else i
            for i in items
        ]

        return items

    async def _enrich_issue_history_with_github(
        entries: dict[int, dict[str, Any]],
        cfg: HydraFlowConfig,
        limit: int = 150,
    ) -> None:
        """Concurrently fetch GitHub metadata and apply it to history entries."""
        if not entries:
            return

        fetcher = IssueFetcher(cfg, credentials=_creds)
        issue_numbers = sorted(entries.keys(), reverse=True)[:limit]
        sem = asyncio.Semaphore(6)

        async def _fetch_and_apply(issue_number: int) -> None:
            """Fetch one issue under the semaphore and apply fields to its entry."""
            async with sem:
                issue = await fetcher.fetch_issue_by_number(issue_number)
            if issue is None:
                return
            row = entries.get(issue_number)
            if row is None:
                return
            row["title"] = issue.title or row.get("title") or f"Issue #{issue_number}"
            row["issue_url"] = issue.url or row.get("issue_url", "")
            labels = [str(lbl).strip() for lbl in issue.labels if str(lbl).strip()]
            if not row.get("epic"):
                # Skip internal pipeline labels (e.g. hydraflow-epic-child);
                # only keep labels that look like actual epic names.
                epic = next(
                    (
                        lbl
                        for lbl in labels
                        if "epic" in lbl.lower()
                        and lbl.lower() not in _EPIC_INTERNAL_LABELS
                    ),
                    "",
                )
                row["epic"] = epic
            ms_num = _coerce_int(getattr(issue, "milestone_number", None))
            if ms_num > 0 and not row.get("crate_number"):
                row["crate_number"] = ms_num
            for link in parse_task_links(issue.body or ""):
                try:
                    tid = int(link.target_id)
                except (ValueError, TypeError):
                    continue
                row["linked_issues"][tid] = {
                    "target_id": tid,
                    "kind": str(link.kind),
                    "target_url": link.target_url or None,
                }

        results = await asyncio.gather(
            *(_fetch_and_apply(num) for num in issue_numbers),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, Exception):
                logger.warning("Issue enrichment fetch failed: %s", result)

    @router.get("/healthz")
    def get_health() -> JSONResponse:
        """Lightweight readiness response for load balancers and monitors."""
        orchestrator = get_orchestrator()
        orchestrator_running = bool(getattr(orchestrator, "running", False))
        worker_states = state.get_bg_worker_states()
        session_counters = state.get_session_counters()
        session_started_at: str | None = session_counters.session_start or None
        uptime_seconds: int | None = None
        if session_started_at:
            try:
                started_dt = datetime.fromisoformat(session_started_at)
            except (ValueError, TypeError):
                session_started_at = None
            else:
                uptime_seconds = max(
                    int((datetime.now(UTC) - started_dt).total_seconds()),
                    0,
                )

        def _normalise_worker_health(
            raw_status: str | BGWorkerHealth | None,
        ) -> BGWorkerHealth:
            """Coerce a raw status value to a BGWorkerHealth enum member."""
            if isinstance(raw_status, BGWorkerHealth):
                return raw_status
            try:
                return BGWorkerHealth(str(raw_status or "").lower())
            except ValueError:
                return BGWorkerHealth.DISABLED

        worker_count = len(worker_states)
        worker_errors = sorted(
            name
            for name, heartbeat in worker_states.items()
            if _normalise_worker_health(heartbeat.get("status")) == BGWorkerHealth.ERROR
        )
        if orchestrator is None:
            orchestrator_running = False
        orchestrator_status = "missing"
        if orchestrator is not None and orchestrator_running:
            orchestrator_status = "running"
        elif orchestrator is not None:
            orchestrator_status = "idle"

        worker_status = "disabled"
        if worker_count > 0:
            worker_status = "degraded" if worker_errors else "ok"

        status = "ok"
        if orchestrator_status == "missing":
            status = "starting"
        elif orchestrator_status == "idle":
            status = "idle"
        if worker_status == "degraded":
            status = "degraded"

        def _is_loopback_host(host: str) -> bool:
            """Return True if the host resolves to localhost or 127.x.x.x."""
            host_lower = (host or "").lower()
            return host_lower == "localhost" or host_lower.startswith("127.")

        dashboard_binding = {
            "host": config.dashboard_host,
            "port": config.dashboard_port,
        }
        dashboard_public = not _is_loopback_host(config.dashboard_host)

        # GitHub cache health (if available).
        # CacheSnapshot.age_seconds returns float("inf") when a dataset has
        # never been fetched (no orchestrator poll yet, e.g. cold sandbox
        # boot). JSON encoding chokes on inf, so we coerce to None for
        # those entries and report the cache as "uninitialized".
        github_cache_health: dict[str, object] = {"status": "unknown"}
        if orchestrator is not None and isinstance(
            getattr(orchestrator, "github_cache", None), GitHubDataCache
        ):
            gh_cache: GitHubDataCache = orchestrator.github_cache
            cache_ages_raw = {
                ds: gh_cache.get_cache_age(ds)
                for ds in ("open_prs", "hitl_items", "label_counts")
            }
            cache_ages: dict[str, float | None] = {
                ds: (None if math.isinf(age) else round(age, 1))
                for ds, age in cache_ages_raw.items()
            }
            finite_ages = [a for a in cache_ages.values() if a is not None]
            if not finite_ages:
                cache_status = "uninitialized"
                max_age = 0.0
            else:
                max_age = max(finite_ages)
                cache_status = (
                    "stale" if max_age > config.data_poll_interval * 3 else "ok"
                )
            github_cache_health = {
                "status": cache_status,
                "age_seconds": cache_ages,
            }

        # Queue depths
        queue_depths: dict[str, int] = {}
        if orchestrator is not None:
            issue_store = getattr(orchestrator, "issue_store", None)
            if issue_store is not None and hasattr(issue_store, "get_queue_stats"):
                qstats = issue_store.get_queue_stats()
                queue_depths = dict(qstats.queue_depth)

        checks = {
            "orchestrator": {
                "status": orchestrator_status,
                "running": orchestrator_running,
                "session_started_at": session_started_at,
            },
            "workers": {
                "status": worker_status,
                "count": worker_count,
                "errors": worker_errors,
            },
            "dashboard": {
                "status": "ok" if config.dashboard_enabled else "disabled",
                "host": config.dashboard_host,
                "port": config.dashboard_port,
                "public": dashboard_public,
            },
            "github_cache": github_cache_health,
            "queue_depths": queue_depths,
        }
        ready = checks["orchestrator"]["status"] == "running" and checks["workers"][
            "status"
        ] in {"ok", "disabled"}
        payload = {
            "status": status,
            "version": get_app_version(),
            "timestamp": datetime.now(UTC).isoformat(),
            "orchestrator_running": orchestrator_running,
            "active_issue_count": len(state.get_active_issue_numbers()),
            "active_workspaces": len(state.get_active_workspaces()),
            "worker_count": worker_count,
            "worker_errors": worker_errors,
            "dashboard": dashboard_binding,
            "session_started_at": session_started_at,
            "uptime_seconds": uptime_seconds,
            "ready": ready,
            "checks": checks,
        }
        return JSONResponse(payload)

    @router.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        """Serve the single-page application root."""
        return _serve_spa_index()

    @router.get("/api/state")
    async def get_state(
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Return the full state tracker snapshot as JSON."""
        _cfg, _state, _bus, _get_orch = _resolve_runtime(repo)
        return JSONResponse(_state.to_dict())

    @router.get("/api/stats")
    async def get_stats(
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Return lifetime stats and optional queue depths.

        For ``repo=__all__`` the lifetime stats are summed across every repo and
        the queue depths are merged across the active lines.
        """
        runtimes = _resolve_runtimes(repo)
        data: dict[str, Any] = merge_lifetime_stats(
            [st.get_lifetime_stats() for _cfg, st, _bus, _go, _slug in runtimes]
        ).model_dump()
        queues: list[QueueStats] = []
        for _cfg, _st, _bus, get_orch, _slug in runtimes:
            orch = get_orch()
            if orch:
                queues.append(orch.issue_store.get_queue_stats())
        if queues:
            data["queue"] = merge_queue_stats(queues).model_dump()
        return JSONResponse(data)

    @router.get("/api/queue")
    async def get_queue(
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Return current queue depths, merged across active lines for __all__."""
        queues: list[QueueStats] = []
        for _cfg, _st, _bus, get_orch, slug in _resolve_runtimes(repo):
            if not _is_pipeline_active(slug):
                continue
            orch = get_orch()
            if orch:
                queues.append(orch.issue_store.get_queue_stats())
        return JSONResponse(merge_queue_stats(queues).model_dump())

    @router.post("/api/request-changes")
    async def request_changes(
        body: dict[str, Any], repo: RepoSlugParam = None
    ) -> JSONResponse:
        """Escalate an issue to HITL with user feedback (repo-scoped).

        Resolves the per-repo runtime so the label swap, HITL cause/origin, and
        escalation event all land on the SELECTED repo — not the default one —
        in a multi-repo deployment.
        """
        if repo is not None and repo.strip().lower() == REPO_ALL:
            return JSONResponse(
                {
                    "status": "error",
                    "detail": "request-changes requires a specific repo",
                },
                status_code=400,
            )
        _cfg, _state, _bus, _get_orch = _resolve_runtime(repo)
        issue_number: int | None = body.get("issue_number")
        feedback = (body.get("feedback") or "").strip()
        stage: str = body.get("stage") or ""

        if not isinstance(issue_number, int) or issue_number < 1 or not feedback:
            return JSONResponse(
                {
                    "status": "error",
                    "detail": "issue_number and feedback are required",
                },
                status_code=400,
            )

        label_field = _FRONTEND_STAGE_TO_LABEL_FIELD.get(stage)
        if not label_field:
            return JSONResponse(
                {"status": "error", "detail": f"Unknown stage: {stage}"},
                status_code=400,
            )

        stage_labels: list[str] = getattr(_cfg, label_field, [])
        origin_label: str = stage_labels[0]

        manager = _pr_manager_for(_cfg, _bus)
        await manager.swap_pipeline_labels(issue_number, _cfg.hitl_label[0])

        _state.set_hitl_cause(issue_number, feedback)
        _state.set_hitl_origin(issue_number, origin_label)

        await _bus.publish(
            HydraFlowEvent(
                type=EventType.HITL_ESCALATION,
                data=HITLEscalationPayload(
                    issue=issue_number,
                    cause=feedback,
                    origin=origin_label,
                ),
            )
        )

        return JSONResponse({"status": "ok"})

    @router.get("/api/pipeline")
    async def get_pipeline(
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Return the pipeline snapshot — issues per stage, unioned across repos
        for ``repo=__all__`` with each issue tagged by its repo slug."""
        merged_stages: dict[str, list[PipelineIssue]] = {}
        for _cfg, _st, _bus, get_orch, slug in _resolve_runtimes(repo):
            if not _is_pipeline_active(slug):
                continue
            orch = get_orch()
            if orch is None:
                continue
            raw = orch.issue_store.get_pipeline_snapshot()
            for backend_stage, issues in raw.items():
                frontend_stage = _STAGE_NAME_MAP.get(backend_stage, backend_stage)
                bucket = merged_stages.setdefault(frontend_stage, [])
                for entry in issues:
                    bucket.append(
                        PipelineIssue.model_validate(entry).model_copy(
                            update={"repo": slug}
                        )
                    )
        return JSONResponse(PipelineSnapshot(stages=merged_stages).model_dump())

    @router.get("/api/pipeline/stats")
    async def get_pipeline_stats(
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Return lightweight pipeline stats — merged across active lines for __all__."""
        stats_list: list[PipelineStats] = []
        for _cfg, _st, _bus, get_orch, slug in _resolve_runtimes(repo):
            if not _is_pipeline_active(slug):
                continue
            orch = get_orch()
            if orch:
                stats_list.append(orch.build_pipeline_stats())
        merged = merge_pipeline_stats(stats_list)
        return JSONResponse(merged.model_dump() if merged is not None else {})

    @router.get("/api/events")
    async def get_events(
        since: str | None = None,
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Return event history, optionally filtered by a since timestamp.

        Resolves the per-repo event bus via ``_resolve_runtimes(repo)`` so the
        reconnect ``?since=`` backfill returns the requested repo's events in a
        multi-repo deployment. For ``repo=__all__`` it unions every runtime's
        events, repo-tags each, and merge-sorts by ``(timestamp, id)`` — the REST
        twin of the merged ``/ws`` stream.
        """
        since_dt: datetime | None = None
        if since is not None:
            try:
                since_dt = datetime.fromisoformat(since)
                if since_dt.tzinfo is None:
                    since_dt = since_dt.replace(tzinfo=UTC)
            except (ValueError, TypeError):
                since_dt = None  # Fall through to in-memory history

        merged: list[HydraFlowEvent] = []
        for _cfg, _state, _bus, _get_orch, slug in _resolve_runtimes(repo):
            events: list[HydraFlowEvent] | None = None
            if since_dt is not None:
                events = await _bus.load_events_since(since_dt)
            if events is None:
                events = _bus.get_history()
            for event in events:
                merged.append(
                    event
                    if event.repo is not None
                    else event.model_copy(update={"repo": slug})
                )
        merged.sort(key=lambda e: (e.timestamp, e.id))
        return JSONResponse([e.model_dump() for e in merged])

    @router.get("/api/prs")
    async def get_prs(
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Fetch all open HydraFlow PRs from GitHub.

        For ``repo=__all__`` this unions every runtime's open PRs; each item is
        tagged with its repo slug so the frontend de-collides same-number PRs
        across repos and matches them to repo-qualified live ``pr_created`` /
        ``merge_update`` frames (else REST-loaded PRs would duplicate).
        """
        result: list[dict[str, Any]] = []
        for _cfg, _state, _bus, _get_orch, slug in _resolve_runtimes(repo):
            orch = _get_orch()
            if orch and isinstance(
                getattr(orch, "github_cache", None), GitHubDataCache
            ):
                items = orch.github_cache.get_open_prs()
            else:
                # ``list_open_prs`` is a dashboard helper on the concrete
                # PRManager, not on PRPort.
                manager = cast("PRManager", _pr_manager_for(_cfg, _bus))
                all_labels = list(
                    {
                        *_cfg.ready_label,
                        *_cfg.review_label,
                        *_cfg.fixed_label,
                        *_cfg.hitl_label,
                        *_cfg.hitl_active_label,
                        *_cfg.planner_label,
                    }
                )
                items = await manager.list_open_prs(all_labels)
            # Overlay merged flag from IssueStore so the frontend has
            # authoritative merged state instead of session-volatile flags.
            merged_numbers = (
                orch.issue_store.get_merged_numbers() if orch else frozenset()
            )
            for item in items:
                data = item if isinstance(item, dict) else item.model_dump()
                issue_num = data.get("issue")
                if issue_num in merged_numbers:
                    data["merged"] = True
                # Tag with the runtime's canonical slug (matches live event.repo).
                data["repo"] = slug
                result.append(data)
        return JSONResponse(result)

    # --- Epic routes (extracted to _epic_routes.py) ---
    from dashboard_routes._epic_routes import register as _register_epics

    _register_epics(router, ctx)

    # --- Crate routes (extracted to _crates_routes.py) ---
    from dashboard_routes._crates_routes import register as _register_crates

    _register_crates(router, ctx)

    # --- Wiki routes (Phase 5 of git-backed repo wiki) ---
    from dashboard_routes._wiki_routes import register as _register_wiki

    _register_wiki(router, ctx)

    # --- Atlas routes (ADR-0090) ---
    from dashboard_routes._atlas_routes import register as _register_atlas

    _register_atlas(router, ctx)

    # --- HITL routes (extracted to _hitl_routes.py) ---
    from dashboard_routes._hitl_routes import register as _register_hitl

    _register_hitl(router, ctx)

    # Memory context routes removed in Phase 3 cutover — wiki routes replace them.

    # --- Control routes (extracted to _control_routes.py) ---
    from dashboard_routes._control_routes import register as _register_control

    _register_control(router, ctx)

    # --- Metrics routes (extracted to _metrics_routes.py) ---
    from dashboard_routes._metrics_routes import register as _register_metrics

    _register_metrics(router, ctx)

    # --- Diagnostics routes (factory metrics + trace artifacts) ---
    from dashboard_routes._diagnostics_routes import build_diagnostics_router

    router.include_router(build_diagnostics_router(config, ctx))

    # --- Trust-fleet routes (§12.1; Plan 5b-3 schema) -----------------------
    from types import SimpleNamespace  # noqa: PLC0415

    from dashboard_routes._trust_routes import build_trust_router  # noqa: PLC0415

    def _trust_deps_factory() -> SimpleNamespace:
        """Return the event_bus/bg_workers/state trio for the trust router.

        The orchestrator owns the live ``BGWorkerManager``; tests that
        don't construct an orchestrator get ``bg_workers=None``, which
        the trust handler treats as "all workers disabled" rather than
        failing the request.
        """
        orch = ctx.get_orchestrator()
        bg_workers = getattr(orch, "_bg_workers", None) if orch is not None else None
        return SimpleNamespace(
            event_bus=ctx.event_bus,
            bg_workers=bg_workers,
            state=ctx.state,
        )

    router.include_router(build_trust_router(config, deps_factory=_trust_deps_factory))

    # --- Factory health routes (longitudinal retrospective analysis) ---
    from dashboard_routes._factory_health_routes import build_factory_health_router

    router.include_router(build_factory_health_router(config, ctx))

    # --- Issue history cache ---
    # Cache the aggregated issue_rows + pr_to_issue for the unfiltered case.
    # Persisted to disk so the first request after restart is fast.
    # Invalidated when the event count or telemetry file changes.
    _history_cache_file = config.data_path("metrics", "history_cache.json")
    _HISTORY_CACHE_TTL = 30  # seconds

    _history_cache: dict[str, Any] = {
        "event_count": -1,
        "telemetry_mtime": 0.0,
        "issue_rows": None,
        "pr_to_issue": None,
        "enriched_issues": set(),
    }
    _history_cache_ts: list[float] = [0.0]

    def _save_history_cache() -> None:
        """Persist in-memory history cache to disk."""
        rows = _history_cache.get("issue_rows")
        if rows is None:
            return
        serialisable_rows: dict[str, Any] = {}
        for k, v in rows.items():
            entry = dict(v)
            # Convert sets to lists for JSON serialisation.
            entry["session_ids"] = sorted(entry.get("session_ids") or [])
            serialisable_rows[str(k)] = entry
        payload = {
            "event_count": _history_cache.get("event_count", -1),
            "telemetry_mtime": _history_cache.get("telemetry_mtime", 0.0),
            "issue_rows": serialisable_rows,
            "pr_to_issue": {
                str(k): v for k, v in (_history_cache.get("pr_to_issue") or {}).items()
            },
            "enriched_issues": sorted(_history_cache.get("enriched_issues") or []),
        }
        try:
            _history_cache_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = _history_cache_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload))
            tmp.replace(_history_cache_file)
        except OSError:
            logger.debug("Could not persist history cache", exc_info=True)

    def _load_history_cache() -> None:
        """Load persisted history cache from disk into memory."""
        if not _history_cache_file.is_file():
            return
        try:
            raw = json.loads(_history_cache_file.read_text())
        except (OSError, json.JSONDecodeError, ValueError):
            logger.debug("Corrupt history cache, ignoring", exc_info=True)
            return
        if not isinstance(raw, dict) or "issue_rows" not in raw:
            return
        rows: dict[int, dict[str, Any]] = {}
        for k, v in raw.get("issue_rows", {}).items():
            if not isinstance(v, dict):
                continue
            entry = dict(v)
            # Restore session_ids to a set.
            entry["session_ids"] = set(entry.get("session_ids") or [])
            # JSON keys are always strings — restore int keys for sub-dicts
            # so enrichment lookups (which use int keys) don't create dupes.
            if isinstance(entry.get("prs"), dict):
                entry["prs"] = {int(pk): pv for pk, pv in entry["prs"].items()}
            if isinstance(entry.get("linked_issues"), dict):
                entry["linked_issues"] = {
                    int(lk): lv for lk, lv in entry["linked_issues"].items()
                }
            rows[int(k)] = entry
        _history_cache["issue_rows"] = rows
        _history_cache["pr_to_issue"] = {
            int(k): int(v) for k, v in raw.get("pr_to_issue", {}).items()
        }
        _history_cache["event_count"] = raw.get("event_count", -1)
        _history_cache["telemetry_mtime"] = raw.get("telemetry_mtime", 0.0)
        _history_cache["enriched_issues"] = set(raw.get("enriched_issues") or [])
        # Set timestamp so TTL check works (treat as "just loaded").
        _history_cache_ts[0] = time.monotonic()

    # Warm the in-memory cache from disk on startup.
    try:
        _load_history_cache()
    except Exception:
        logger.warning("History cache warm-up failed", exc_info=True)

    async def _collect_history_items(
        cfg: HydraFlowConfig,
        state: StateTracker,
        bus: EventBus,
        repo_slug: str,
        *,
        since_dt: datetime | None,
        until_dt: datetime | None,
        requested_status: str,
        query_text: str,
        use_cache: bool,
    ) -> list[IssueHistoryEntry]:
        """Build issue-history rows for ONE runtime, tagged with *repo_slug*.

        Reads the runtime's own telemetry/events/state. The persistent
        ``_history_cache`` is keyed to the default runtime only, so it is
        read/written exclusively when *use_cache* is True (``repo is None``);
        per-repo and ``__all__`` requests build fresh so one repo's rollups
        never bleed into another's view — or into the cached default.
        """
        telemetry = PromptTelemetry(cfg)
        all_events = bus.get_history()

        # Check if we can reuse cached aggregation for the unfiltered case.
        use_unfiltered = since_dt is None and until_dt is None
        event_count = len(all_events)
        telem_mtime = telemetry.get_mtime()
        now = time.monotonic()
        cache_hit = (
            use_cache
            and use_unfiltered
            and _history_cache["issue_rows"] is not None
            and _history_cache["event_count"] == event_count
            and _history_cache["telemetry_mtime"] == telem_mtime
            and (now - _history_cache_ts[0]) < _HISTORY_CACHE_TTL
        )

        if cache_hit:
            issue_rows: dict[int, dict[str, Any]] = copy.deepcopy(
                _history_cache["issue_rows"]
            )
            pr_to_issue: dict[int, int] = dict(_history_cache["pr_to_issue"])
        else:
            issue_rows = {}
            pr_to_issue = {}

            # Build PR→issue mapping from all in-memory events first so merge
            # events in the selected range still resolve when PR creation
            # happened earlier.
            for event in all_events:
                if event.type != EventType.PR_CREATED:
                    continue
                mapped_issue = _event_issue_number(event.data)
                mapped_pr = _coerce_int(event.data.get("pr"))
                if mapped_issue is not None and mapped_issue > 0 and mapped_pr > 0:
                    pr_to_issue[mapped_pr] = mapped_issue

        use_issue_rollups = (
            since_dt is None
            and until_dt is None
            and not query_text
            and not requested_status
        )
        if cache_hit:
            pass  # aggregation already done
        elif use_issue_rollups:
            for issue_number, counters in telemetry.get_issue_totals().items():
                row = issue_rows.setdefault(
                    issue_number, _new_issue_history_entry(issue_number, cfg)
                )
                for key in _INFERENCE_COUNTER_KEYS:
                    row["inference"][key] = _coerce_int(counters.get(key, 0))
            # Keep metadata (sessions/model/source/pr links) from recent rows
            # without re-summing counters that already came from rollups.
            for record in telemetry.load_inferences(limit=5000):
                issue_number = _coerce_int(record.get("issue_number"))
                if issue_number <= 0:
                    continue
                row = issue_rows.get(issue_number)
                if row is None:
                    continue
                _aggregate_telemetry_record(
                    row, record, pr_to_issue, sum_counters=False
                )
        else:
            inference_rows = telemetry.load_inferences(limit=50000)
            for record in inference_rows:
                timestamp = record.get("timestamp")
                if not _is_timestamp_in_range(
                    timestamp if isinstance(timestamp, str) else None,
                    since_dt,
                    until_dt,
                ):
                    continue
                issue_number = _coerce_int(record.get("issue_number"))
                if issue_number <= 0:
                    continue
                row = issue_rows.setdefault(
                    issue_number, _new_issue_history_entry(issue_number, cfg)
                )
                _aggregate_telemetry_record(row, record, pr_to_issue, sum_counters=True)

        if not cache_hit:
            _process_events_into_rows(
                all_events, issue_rows, pr_to_issue, since_dt, until_dt, cfg
            )

            # Store in cache if this was an unfiltered aggregation. Only the
            # default-repo view is cached: _history_cache is not repo-keyed, so
            # a per-repo / __all__ request must never read (see cache_hit) or
            # write it, or one repo's rollups would bleed into another's view.
            if use_cache and use_unfiltered:
                _history_cache["issue_rows"] = copy.deepcopy(issue_rows)
                _history_cache["pr_to_issue"] = dict(pr_to_issue)
                _history_cache["event_count"] = event_count
                _history_cache["telemetry_mtime"] = telem_mtime
                _history_cache_ts[0] = now
                _save_history_cache()

        items = _filter_rows_to_items(
            issue_rows, requested_status, query_text, state, repo_slug
        )

        # Enrich via GitHub, backfill crate titles, sort.
        items = await _apply_enrichment_and_crate_titles(
            items,
            issue_rows,
            requested_status,
            query_text,
            use_unfiltered,
            cfg=cfg,
            bus=bus,
            state=state,
            repo_slug=repo_slug,
            use_cache=use_cache,
        )
        return items

    @router.get("/api/issues/history")
    async def get_issue_history(
        since: str | None = None,
        until: str | None = None,
        status: str | None = None,
        query: str | None = None,
        limit: int = 300,
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Return issue lifecycle history with inference rollups (repo-scoped).

        For ``repo=__all__`` the history is unioned across every runtime and
        each row is tagged with its repo slug. Issue numbers collide across
        repos, so rows are kept distinct per ``(repo, issue_number)`` (the
        per-runtime lists are simply concatenated, never merged by number).
        """
        since_dt = _parse_iso_or_none(since)
        until_dt = _parse_iso_or_none(until)
        requested_status = (status or "").strip().lower()
        query_text = (query or "").strip().lower()
        clamped_limit = max(1, min(limit, 1000))

        # The persistent history cache is keyed to the default runtime, so only
        # a bare (repo is None) request may use it.
        use_cache = repo is None

        items: list[IssueHistoryEntry] = []
        for _cfg, _state, _bus, _get_orch, slug in _resolve_runtimes(repo):
            items.extend(
                await _collect_history_items(
                    _cfg,
                    _state,
                    _bus,
                    slug,
                    since_dt=since_dt,
                    until_dt=until_dt,
                    requested_status=requested_status,
                    query_text=query_text,
                    use_cache=use_cache,
                )
            )

        # Order globally across runtimes (per-runtime lists were each sorted),
        # then apply the page limit to the merged result.
        items.sort(
            key=lambda item: (
                item.last_seen or "",
                item.inference.get("total_tokens", 0),
                item.issue_number,
            ),
            reverse=True,
        )
        items = items[:clamped_limit]

        totals = {
            "issues": len(items),
            "inference_calls": sum(
                i.inference.get("inference_calls", 0) for i in items
            ),
            "total_tokens": sum(i.inference.get("total_tokens", 0) for i in items),
        }

        return JSONResponse(
            IssueHistoryResponse(
                items=items,
                totals=totals,
                since=since_dt.isoformat() if since_dt else None,
                until=until_dt.isoformat() if until_dt else None,
            ).model_dump()
        )

    @router.get("/api/troubleshooting")
    async def get_troubleshooting() -> JSONResponse:
        """Return learned troubleshooting patterns."""
        from troubleshooting_store import TroubleshootingPatternStore

        memory_dir = config.data_path("memory")
        store = TroubleshootingPatternStore(memory_dir)
        all_patterns = store.load_patterns(limit=None)
        total = len(all_patterns)
        capped = all_patterns[:100]

        return JSONResponse(
            {
                "total_patterns": total,
                "patterns": [p.model_dump() for p in capped],
            }
        )

    @router.get("/api/timeline")
    async def get_timeline(repo: RepoSlugParam = None) -> JSONResponse:
        """Return timelines for all tracked issues (repo-scoped).

        For ``repo=__all__`` this unions every runtime's timelines and tags
        each item with its dash slug, so a same-numbered issue in two repos
        stays distinct.
        """
        if repo is not None and repo.strip().lower() == REPO_ALL:
            merged: list[dict[str, Any]] = []
            for _cfg, _st, _bus, _get_orch, slug in _resolve_runtimes(repo):
                for timeline in TimelineBuilder(_bus).build_all():
                    merged.append(
                        timeline.model_copy(update={"repo": slug}).model_dump()
                    )
            return JSONResponse(merged)
        _cfg, _state, _bus, _get_orch = _resolve_runtime(repo)
        builder = TimelineBuilder(_bus)
        timelines = builder.build_all()
        return JSONResponse([t.model_dump() for t in timelines])

    @router.get("/api/timeline/issue/{issue_number}")
    async def get_timeline_issue(
        issue_number: int, repo: RepoSlugParam = None
    ) -> JSONResponse:
        """Return the event timeline for a single issue (repo-scoped).

        For ``repo=__all__`` this searches every runtime and returns the first
        match (repo-tagged). Issue numbers aren't globally unique, so the first
        registered repo carrying the issue wins; 404 if no repo has it.
        """
        if repo is not None and repo.strip().lower() == REPO_ALL:
            for _cfg, _st, _bus, _get_orch, slug in _resolve_runtimes(repo):
                timeline = TimelineBuilder(_bus).build_for_issue(issue_number)
                if timeline is not None:
                    return JSONResponse(
                        timeline.model_copy(update={"repo": slug}).model_dump()
                    )
            return JSONResponse({"error": "Issue not found"}, status_code=404)
        _cfg, _state, _bus, _get_orch = _resolve_runtime(repo)
        builder = TimelineBuilder(_bus)
        timeline = builder.build_for_issue(issue_number)
        if timeline is None:
            return JSONResponse({"error": "Issue not found"}, status_code=404)
        return JSONResponse(timeline.model_dump())

    @router.get("/api/timeline/completed")
    async def get_completed_timelines(repo: RepoSlugParam = None) -> JSONResponse:
        """Return persisted timelines for completed (merged) issues (repo-scoped).

        Unlike /api/timeline which derives from ephemeral events,
        these survive event log rotation. For ``repo=__all__`` it unions every
        runtime's persisted timelines, each tagged with its dash slug.
        """
        if repo is not None and repo.strip().lower() == REPO_ALL:
            merged: list[dict[str, Any]] = []
            for _cfg, _st, _bus, _get_orch, slug in _resolve_runtimes(repo):
                for timeline in _st.get_all_completed_timelines().values():
                    merged.append(
                        timeline.model_copy(update={"repo": slug}).model_dump()
                    )
            return JSONResponse(merged)
        _cfg, _state, _bus, _get_orch = _resolve_runtime(repo)
        timelines = _state.get_all_completed_timelines()
        return JSONResponse([t.model_dump() for t in timelines.values()])

    # --- State/runtimes/repos/filesystem routes (extracted to _state_routes.py) ---
    from dashboard_routes._state_routes import register as _register_state

    _register_state(router, ctx)

    @router.post("/api/intent")
    async def submit_intent(
        request: IntentRequest, repo: RepoSlugParam = None
    ) -> JSONResponse:
        """Create a GitHub issue from a user intent typed in the dashboard.

        Repo-scoped: the issue is created in the SELECTED repo (and its URL
        points there), not the default repo, in a multi-repo deployment.
        ``repo=__all__`` is rejected — issue creation needs a specific repo.
        """
        if repo is not None and repo.strip().lower() == REPO_ALL:
            return JSONResponse(
                {
                    "status": "error",
                    "detail": "issue creation requires a specific repo",
                },
                status_code=400,
            )
        _cfg, _state, _bus, _get_orch = _resolve_runtime(repo)
        title = request.text[:120]
        body = request.text
        labels = list(_cfg.planner_label)

        manager = _pr_manager_for(_cfg, _bus)
        issue_number = await manager.create_issue(title=title, body=body, labels=labels)

        if issue_number == 0:
            return JSONResponse({"error": "Failed to create issue"}, status_code=500)

        url = f"https://github.com/{_cfg.repo}/issues/{issue_number}"
        response = IntentResponse(issue_number=issue_number, title=title, url=url)
        return JSONResponse(response.model_dump())

    # --- Reports routes (extracted to _reports_routes.py) ---
    from dashboard_routes._reports_routes import register as _register_reports

    _register_reports(router, ctx)

    # --- Headless onboarding draft routes (merged from main) ---
    from dashboard_routes._onboarding_routes import register as _register_onboarding

    _register_onboarding(router, ctx)

    @router.get("/api/sessions")
    async def get_sessions(
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Return session logs — unioned across repos for ``repo=__all__``.

        Each runtime's state is already repo-scoped, and ``SessionLog.repo``
        + the ``{repo_slug}-{ts}`` session_id make entries self-identifying.
        """
        sessions = []
        for _cfg, _state, _bus, _get_orch, _slug in _resolve_runtimes(repo):
            sessions.extend(_state.load_sessions())
        repo_filter = (repo or "").strip()
        if repo_filter.lower() != REPO_ALL and registry is None:
            # Legacy no-registry wiring: the single state holds sessions for
            # every repo. Scope to the requested repo — and per the None=default
            # invariant, a bare request scopes to the DEFAULT repo, not the
            # whole set. Normalize slash/dash so a dash-form query slug
            # ("owner-x") matches a slash-form SessionLog.repo ("owner/x").
            target = (
                (repo_filter or _resolve_runtimes(None)[0][4]).replace("/", "-").lower()
            )
            sessions = [
                session
                for session in sessions
                if (session.repo or "").replace("/", "-").lower() == target
            ]
        return JSONResponse([s.model_dump() for s in sessions])

    @router.get("/api/sessions/{session_id}")
    async def get_session_detail(
        session_id: str,
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Return a single session by ID with associated events.

        Searches the resolved runtime(s) — for ``repo=__all__`` this finds the
        owning repo across every line; for a specific repo it checks just that one.
        """
        for _cfg, _state, _bus, _get_orch, _slug in _resolve_runtimes(repo):
            session = _state.get_session(session_id)
            if session is None:
                continue
            session_events = [
                e.model_dump() for e in _bus.get_history() if e.session_id == session_id
            ]
            data = session.model_dump()
            data["events"] = session_events
            return JSONResponse(data)
        return JSONResponse({"error": "Session not found"}, status_code=404)

    @router.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket) -> None:
        """Stream event history then live events over a WebSocket connection."""
        repo_slug: str | None = ws.query_params.get("repo")

        # Aggregate view: fan every registered repo's bus into one socket. Branch
        # BEFORE _resolve_runtime — it would treat "__all__" as an unknown slug
        # and 1008-close, streaming one repo mislabeled as the aggregate.
        if (repo_slug or "").strip().lower() == REPO_ALL:
            await _serve_merged_ws(ws, _resolve_runtimes(REPO_ALL))
            return

        # Single-repo fast path (None / specific slug) — unchanged.
        try:
            _cfg, _state, bus, _get_orch = _resolve_runtime(repo_slug)
        except (ValueError, HTTPException):
            await ws.accept()
            await ws.close(code=1008, reason=f"Unknown repo: {repo_slug}")
            return

        await ws.accept()

        # Snapshot history BEFORE subscribing to avoid duplicates.
        # Events published between snapshot and subscribe are picked
        # up by the live queue, never sent twice.
        history = bus.get_history()

        async with bus.subscription() as queue:
            # Send history on connect
            for event in history:
                try:
                    await ws.send_text(event.model_dump_json())
                except Exception as exc:
                    if _is_likely_disconnect(exc):
                        logger.warning(
                            "WebSocket disconnect during history replay: %s",
                            exc.__class__.__name__,
                        )
                    else:
                        logger.error(
                            "WebSocket error during history replay: %s",
                            exc.__class__.__name__,
                            exc_info=True,
                        )
                    return

            # Stream live events
            try:
                while True:
                    event: HydraFlowEvent = await queue.get()
                    await ws.send_text(event.model_dump_json())
            except WebSocketDisconnect:
                pass
            except Exception as exc:
                if _is_likely_disconnect(exc):
                    logger.warning(
                        "WebSocket disconnect during live streaming: %s",
                        exc.__class__.__name__,
                    )
                else:
                    logger.error(
                        "WebSocket error during live streaming: %s",
                        exc.__class__.__name__,
                        exc_info=True,
                    )

    # ---------------------------------------------------------------------------
    # JSONL data endpoints
    # ---------------------------------------------------------------------------

    def _read_jsonl(path: Path) -> list[dict[str, Any]]:
        """Read a JSONL file and return parsed records, skipping malformed lines."""
        if not path.exists():
            return []
        records: list[dict[str, Any]] = []
        try:
            for line in path.read_text(encoding="utf-8").strip().splitlines():
                with contextlib.suppress(json.JSONDecodeError):
                    records.append(json.loads(line))
        except OSError:
            pass
        return records

    @router.get("/api/hitl-recommendations")
    async def get_hitl_recommendations() -> JSONResponse:
        """Return unactioned HITL recommendations filed by the health monitor."""
        path = config.data_path("memory", "hitl_recommendations.jsonl")
        return JSONResponse(_read_jsonl(path))

    @router.get("/api/adr-decisions")
    async def get_adr_decisions() -> JSONResponse:
        """Return ADR decision records from adr_reviewer and memory pre-validation."""
        path = config.data_path("memory", "adr_decisions.jsonl")
        return JSONResponse(_read_jsonl(path))

    @router.get("/api/verification-records")
    async def get_verification_records() -> JSONResponse:
        """Return post-merge verification records requiring human review."""
        path = config.data_path("memory", "verification_records.jsonl")
        return JSONResponse(_read_jsonl(path))

    # SPA catch-all: serve index.html for any path not matched above.
    # This must be registered LAST so it doesn't shadow API/WS routes.
    @router.get("/{path:path}", response_model=None)
    async def spa_catchall(path: str) -> Response:
        """Catch-all route: serve static assets or fall back to the SPA index."""
        # Don't catch API, WebSocket, or static-asset paths
        if path.startswith(("api/", "ws/", "assets/", "static/")) or path == "ws":
            return JSONResponse({"detail": "Not Found"}, status_code=404)

        # Serve only root-level static files from ui/dist/ (e.g. logos, favicon).
        # Reject nested/relative segments to prevent path traversal.
        path_parts = PurePosixPath(path).parts
        if len(path_parts) == 1 and path_parts[0] not in {"", ".", ".."}:
            static_file = (ui_dist_dir / path_parts[0]).resolve()
            if (
                static_file.is_relative_to(ui_dist_dir.resolve())
                and static_file.is_file()
            ):
                return FileResponse(static_file)

        return _serve_spa_index()

    # ------------------------------------------------------------------
    # Product track — Shape HTML artifacts
    # ------------------------------------------------------------------

    @router.get("/api/shape/artifact/{issue_number}")
    def get_shape_artifact(issue_number: int, slug: str | None = None) -> Response:
        """Serve the Shape phase HTML artifact for an issue.

        Returns the self-contained HTML direction cards for rendering
        in OpenClaw's canvas or the dashboard.
        """
        cfg, _st, _bus, _get_orch = _resolve_runtime(slug)
        path = cfg.data_root / "artifacts" / "shape" / f"issue-{issue_number}.html"
        if not path.is_file():
            return JSONResponse(
                {"error": f"No shape artifact for issue #{issue_number}"},
                status_code=404,
            )
        return HTMLResponse(path.read_text(encoding="utf-8"))

    @router.get("/api/webhooks/whatsapp")
    async def whatsapp_verify(request: Request) -> Response:
        """Handle WhatsApp webhook verification challenge."""
        mode = request.query_params.get("hub.mode")
        token = request.query_params.get("hub.verify_token")
        challenge = request.query_params.get("hub.challenge", "")
        _cfg, _st, _bus, _get_orch = _resolve_runtime(None)
        expected_token = (
            ctx.credentials.whatsapp_verify_token or ctx.credentials.whatsapp_token
        )
        if mode == "subscribe" and token == expected_token:
            return Response(content=challenge, media_type="text/plain")
        return Response(content="Forbidden", status_code=403)

    @router.post("/api/webhooks/whatsapp")
    async def whatsapp_webhook(request: Request) -> JSONResponse:
        """Receive inbound WhatsApp messages and route to shape conversations.

        Validates the request signature using the WhatsApp app secret,
        then parses the payload, extracts the message text and issue number,
        and stores it as a shape response for the next poll cycle.
        """
        from whatsapp_bridge import WhatsAppBridge  # noqa: PLC0415

        _cfg, _st, _bus, _get_orch = _resolve_runtime(None)
        if not _cfg.whatsapp_enabled:
            return JSONResponse({"status": "disabled"}, status_code=403)

        # Signature verification: reject unsigned or forged requests.
        # Meta sends X-Hub-Signature-256: sha256=<hex> computed over the raw
        # request body using the app secret.  We must verify before processing.
        raw_body = await request.body()
        sig_header = request.headers.get("x-hub-signature-256")
        if sig_header is None:
            return JSONResponse({"status": "missing_signature"}, status_code=403)

        app_secret = ctx.credentials.whatsapp_app_secret
        expected_mac = hmac.new(
            app_secret.encode(), raw_body, hashlib.sha256
        ).hexdigest()
        expected_header = f"sha256={expected_mac}"
        if not hmac.compare_digest(sig_header, expected_header):
            return JSONResponse({"status": "invalid_signature"}, status_code=403)

        request_body = await request.json()
        text, issue_number = WhatsAppBridge.parse_webhook(request_body)
        if not text:
            return JSONResponse({"status": "no_message"})

        # If no issue number found, try to find the most recent active shape
        if issue_number is None:
            for key in list(_st._data.shape_conversations):
                c = _st._data.shape_conversations[key]
                if c.status == "exploring":
                    issue_number = c.issue_number
                    break

        if issue_number is None:
            return JSONResponse({"status": "no_issue_match"}, status_code=400)

        # Store response for shape phase to pick up (avoids race condition)
        _st.set_shape_response(issue_number, text)

        # Post to GitHub for audit trail (best-effort)
        with contextlib.suppress(Exception):
            await pr_manager.post_comment(issue_number, f"*[via WhatsApp]* {text}")

        return JSONResponse({"status": "ok", "issue": issue_number})

    return router
