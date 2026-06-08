"""Diagnostics dashboard routes.

Nine read-only endpoints that surface factory metrics (read from
``<data_root>/diagnostics/factory_metrics.jsonl``) and per-run trace
artifacts (``<data_root>/traces/<issue>/<phase>/run-N/``) for the
Diagnostics tab of the dashboard UI.

All endpoints accept a ``range`` query parameter (``24h``/``7d``/``30d``/
``all``) that is forwarded to :func:`factory_metrics.load_metrics`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Query

import dashboard_routes._cost_rollups as _cost_rollups_mod
from dashboard_routes._cost_merge import (
    merge_by_loop,
    merge_cost_by_model,
    merge_per_loop_cost,
    merge_rolling_24h,
    merge_top_issues,
)
from dashboard_routes._cost_rollups import (
    _parse_range,
    build_by_loop,
    build_cost_by_model,
    build_per_loop_cost,
    build_rolling_24h,
    build_top_issues,
)
from dashboard_routes._waterfall_builder import build_waterfall
from factory_metrics import (
    aggregate_top_skills,
    aggregate_top_subagents,
    aggregate_top_tools,
    cost_by_phase,
    headline_metrics,
    issues_table,
    load_metrics,
)
from route_types import REPO_ALL, RepoSlugParam

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from dashboard_routes._routes import RouteContext
    from events import EventBus
    from issue_fetcher import IssueFetcher

logger = logging.getLogger("hydraflow.dashboard.diagnostics")

_PHASE_PATTERN = re.compile(r"^[a-z_-]+$")


def _safe_traces_subdir(data_root: Path, *parts: str | int) -> Path | None:
    """Resolve a path under ``<data_root>/traces`` and reject traversal.

    Returns the resolved ``Path`` on success, or ``None`` if the resulting
    path escapes the traces directory (e.g. via ``..`` segments).
    """
    safe_root = (data_root / "traces").resolve()
    candidate = (data_root / "traces").joinpath(*[str(p) for p in parts]).resolve()
    try:
        candidate.relative_to(safe_root)
    except ValueError:
        return None
    return candidate


def _sort_issues(rows: list[dict[str, Any]], sort: str) -> list[dict[str, Any]]:
    """Return ``rows`` sorted by ``sort`` key (descending for numeric)."""
    if sort == "duration":
        return sorted(rows, key=lambda r: r.get("duration_seconds") or 0, reverse=True)
    if sort == "issue":
        return sorted(rows, key=lambda r: r.get("issue") or 0)
    # default: tokens descending
    return sorted(rows, key=lambda r: r.get("tokens") or 0, reverse=True)


def _parse_event_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts


def _cache_hit_rate_buckets(
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return a list of ``{timestamp, cache_hit_rate}`` rows, one per hour.

    Events without a parseable timestamp are dropped. Buckets are sorted
    ascending by hour.
    """
    buckets: dict[datetime, dict[str, int]] = {}
    for event in events:
        ts = _parse_event_timestamp(event.get("timestamp"))
        if ts is None:
            continue
        hour = ts.replace(minute=0, second=0, microsecond=0)
        tokens = event.get("tokens") or {}
        if not isinstance(tokens, dict):
            continue
        input_value = tokens.get("input", 0)
        cache_read_value = tokens.get("cache_read", 0)
        slot = buckets.setdefault(hour, {"input": 0, "cache_read": 0})
        if isinstance(input_value, int | float):
            slot["input"] += int(input_value)
        if isinstance(cache_read_value, int | float):
            slot["cache_read"] += int(cache_read_value)

    rows: list[dict[str, Any]] = []
    for hour in sorted(buckets.keys()):
        totals = buckets[hour]
        denom = totals["input"] + totals["cache_read"]
        rate = round(totals["cache_read"] / denom, 4) if denom > 0 else 0.0
        rows.append(
            {
                "timestamp": hour.isoformat(),
                "cache_hit_rate": rate,
            }
        )
    return rows


def _load_json_file(path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read %s: %s", path, exc)
        return None
    if isinstance(data, dict):
        return data
    return None


def _event_bus_for_rollup(config: HydraFlowConfig) -> EventBus | None:
    """Return an ``EventBus`` wired to the on-disk event log.

    Extracted so tests can monkeypatch a mock. Production path constructs
    a read-only bus against the config's event log; returns ``None`` if
    the log is unavailable so the caller falls back to trace-only rollups.
    """
    # Lazy import — ``events`` imports are heavy (async pubsub machinery).
    from events import EventBus, EventLog  # noqa: PLC0415

    try:
        log_path = getattr(config, "event_log_path", None)
        if log_path is None:
            return None
        log = EventLog(Path(log_path))
        return EventBus(max_history=0, event_log=log)
    except Exception:  # noqa: BLE001
        logger.warning("_event_bus_for_rollup: construction failed", exc_info=True)
        return None


def _build_issue_fetcher(config: HydraFlowConfig) -> IssueFetcher:
    """Construct an IssueFetcher for the waterfall endpoint.

    Split out so tests can monkeypatch a mock in place without standing
    up the full ServiceRegistry. The production path constructs a real
    IssueFetcher with the runtime credentials object.
    """
    # Lazy import — issue_fetcher pulls in async/subprocess machinery we
    # don't want eager-loaded at dashboard import time.
    from config import build_credentials  # noqa: PLC0415
    from issue_fetcher import IssueFetcher  # noqa: PLC0415

    credentials = build_credentials(config)
    return IssueFetcher(config, credentials)


def _issue_meta_from_github_issue(issue_number: int, gh_issue: Any) -> dict[str, Any]:
    """Convert a GitHubIssue model (or None) into the waterfall issue_meta shape."""
    if gh_issue is None:
        return {
            "number": issue_number,
            "title": "(unknown)",
            "labels": [],
            "first_seen": None,
            "merged_at": None,
        }
    return {
        "number": int(getattr(gh_issue, "number", issue_number)),
        "title": str(getattr(gh_issue, "title", "")),
        "labels": [str(lbl) for lbl in (getattr(gh_issue, "labels", []) or [])],
        "first_seen": str(getattr(gh_issue, "created_at", "") or "") or None,
        # merged_at is not on GitHubIssue; when available via issue_outcomes
        # the caller can hydrate it, but for v1 the spec treats None as fine.
        "merged_at": None,
    }


def build_diagnostics_router(
    config: HydraFlowConfig, ctx: RouteContext | None = None
) -> APIRouter:
    """Build the ``/api/diagnostics`` router.

    The returned router exposes GET endpoints that read from the factory
    metrics JSONL store, the per-run trace artifact directory, and the
    shared cost-rollup aggregator.

    When *ctx* is provided the factory-metrics endpoints honor a ``repo``
    query param: ``repo=__all__`` unions every repo's factory-metrics events
    before aggregating, and a specific slug scopes to that repo; per-issue
    endpoints resolve that single repo's config. Without *ctx* (legacy
    single-repo callers) every endpoint reads the bare *config*.
    """

    router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])

    def _config_for(repo: str | None) -> HydraFlowConfig:
        """The single resolved config for per-issue trace endpoints.

        Per-issue traces live under exactly one repo's ``data_root``, so a
        concrete slug is required. ``__all__`` has no single home and is
        rejected — the UI scopes each drill-down to the row's owning repo
        (carried on the issues-table row), never the aggregate sentinel.
        """
        if ctx is None:
            return config
        if repo is not None and repo.strip().lower() == REPO_ALL:
            raise HTTPException(
                status_code=400,
                detail="repo=__all__ is not valid for per-issue endpoints; pass a repo slug",
            )
        cfg, _s, _b, _g = ctx.resolve_runtime(repo)
        return cfg

    def _load(time_range: str, repo: str | None = None) -> list[dict[str, Any]]:
        """Load factory-metrics events, unioned across the resolved repos.

        Each event is tagged with its owning repo slug so downstream rows (the
        per-issue table in particular) stay attributable when ``__all__`` unions
        repos whose issue numbers collide. Legacy single-repo callers (``ctx is
        None``) read the bare config and leave events untagged.
        """
        if ctx is None:
            return load_metrics(config.factory_metrics_path, time_range=time_range)
        events: list[dict[str, Any]] = []
        for cfg, _s, _b, _g, slug in ctx.resolve_runtimes(repo):
            for event in load_metrics(cfg.factory_metrics_path, time_range=time_range):
                event["repo"] = slug
                events.append(event)
        return events

    def _runtimes(repo: str | None) -> list[tuple[HydraFlowConfig, str]]:
        """``(config, slug)`` pairs for cost rollups to aggregate over.

        One element for a concrete slug or ``None`` (the default repo), every
        registered repo for ``__all__``. Callers guard ``ctx is None`` first and
        read the bare config, so this is only reached in the multi-repo path.
        """
        if ctx is None:
            return [(config, "")]
        return [(cfg, slug) for cfg, _s, _b, _g, slug in ctx.resolve_runtimes(repo)]

    @router.get("/overview")
    def overview(
        range: str = Query("7d"), repo: RepoSlugParam = None
    ) -> dict[str, Any]:
        events = _load(range, repo)
        return headline_metrics(events)

    @router.get("/tools")
    def tools(
        range: str = Query("7d"),
        top_n: int = Query(10, ge=1, le=100),
        repo: RepoSlugParam = None,
    ) -> list[dict[str, Any]]:
        events = _load(range, repo)
        return [
            {"name": name, "count": count}
            for name, count in aggregate_top_tools(events, top_n=top_n)
        ]

    @router.get("/skills")
    def skills(
        range: str = Query("7d"),
        top_n: int = Query(10, ge=1, le=100),
        repo: RepoSlugParam = None,
    ) -> list[dict[str, Any]]:
        events = _load(range, repo)
        return aggregate_top_skills(events, top_n=top_n)

    @router.get("/subagents")
    def subagents(
        range: str = Query("7d"),
        top_n: int = Query(10, ge=1, le=100),
        repo: RepoSlugParam = None,
    ) -> list[dict[str, Any]]:
        events = _load(range, repo)
        # aggregate_top_subagents returns list[tuple[str, int]] — currently
        # always [] until per-subagent name attribution lands in the
        # collector. The wrapping below assumes the tuple shape and will
        # need to be revisited if the upstream signature changes.
        return [
            {"name": name, "count": count}
            for name, count in aggregate_top_subagents(events, top_n=top_n)
        ]

    @router.get("/cost-by-phase")
    def cost_by_phase_route(
        range: str = Query("7d"), repo: RepoSlugParam = None
    ) -> dict[str, int]:
        events = _load(range, repo)
        return cost_by_phase(events)

    @router.get("/issues")
    def issues(
        range: str = Query("7d"),
        sort: str = Query("tokens"),
        repo: RepoSlugParam = None,
    ) -> list[dict[str, Any]]:
        events = _load(range, repo)
        rows = issues_table(events)
        return _sort_issues(rows, sort)

    @router.get("/issue/{issue}/waterfall")
    def issue_waterfall(issue: int, repo: RepoSlugParam = None) -> dict[str, Any]:
        """Return the per-issue cost/phase waterfall (spec §4.11 point 1)."""
        cfg = _config_for(repo)
        fetcher = _build_issue_fetcher(cfg)
        try:
            gh_issue = asyncio.run(fetcher.fetch_issue_by_number(issue))
        except Exception:
            logger.warning(
                "waterfall: fetch_issue_by_number failed for #%d",
                issue,
                exc_info=True,
            )
            gh_issue = None
        issue_meta = _issue_meta_from_github_issue(issue, gh_issue)
        return build_waterfall(cfg, issue=issue, issue_meta=issue_meta)

    @router.get("/issue/{issue}/{phase}")
    def issue_phase(
        issue: int, phase: str, repo: RepoSlugParam = None
    ) -> list[dict[str, Any]]:
        if not _PHASE_PATTERN.fullmatch(phase):
            raise HTTPException(status_code=404, detail="not found")
        phase_dir = _safe_traces_subdir(_config_for(repo).data_root, issue, phase)
        if phase_dir is None or not phase_dir.is_dir():
            raise HTTPException(status_code=404, detail="not found")
        summaries: list[dict[str, Any]] = []
        for run_dir in sorted(phase_dir.iterdir()):
            if not run_dir.is_dir() or not run_dir.name.startswith("run-"):
                continue
            summary_path = run_dir / "summary.json"
            if not summary_path.exists():
                continue
            data = _load_json_file(summary_path)
            if data is not None:
                summaries.append(data)
        return summaries

    @router.get("/issue/{issue}/{phase}/{run_id}")
    def issue_phase_run(
        issue: int, phase: str, run_id: int, repo: RepoSlugParam = None
    ) -> dict[str, Any]:
        if not _PHASE_PATTERN.fullmatch(phase):
            raise HTTPException(status_code=404, detail="not found")
        run_dir = _safe_traces_subdir(
            _config_for(repo).data_root, issue, phase, f"run-{run_id}"
        )
        if run_dir is None or not run_dir.is_dir():
            raise HTTPException(status_code=404, detail="not found")
        summary_path = run_dir / "summary.json"
        if not summary_path.exists():
            raise HTTPException(status_code=404, detail="not found")
        summary = _load_json_file(summary_path)
        if summary is None:
            raise HTTPException(status_code=404, detail="not found")
        subprocesses: list[dict[str, Any]] = []
        for sub_path in sorted(run_dir.glob("subprocess-*.json")):
            data = _load_json_file(sub_path)
            if data is not None:
                subprocesses.append(data)
        return {"summary": summary, "subprocesses": subprocesses}

    @router.get("/cache")
    def cache(
        range: str = Query("7d"), repo: RepoSlugParam = None
    ) -> list[dict[str, Any]]:
        events = _load(range, repo)
        return _cache_hit_rate_buckets(events)

    # --- Cost-rollup endpoints (§4.11 points 4–5) ---------------------------
    # Repo-aware (Phase 3c-2): with ``ctx`` each endpoint builds per repo over
    # ``resolve_runtimes(repo)`` and folds the results (group-by-sum on the
    # phase/loop/model dimensions; per-issue rows carry a repo tag). ``ctx is
    # None`` keeps the bare single-repo builder. NOTE: ``/auto-agent`` (Overview
    # tab) is NOT yet repo-scoped — its percentile merge is deferred to 3c-3.

    @router.get("/cost/rolling-24h")
    def cost_rolling_24h(repo: RepoSlugParam = None) -> dict[str, Any]:
        """Total cost burned in the last 24h, grouped by phase and loop (§4.11 point 4)."""
        if ctx is None:
            return build_rolling_24h(config)
        return merge_rolling_24h(
            [build_rolling_24h(cfg) for cfg, _slug in _runtimes(repo)]
        )

    @router.get("/cost/top-issues")
    def cost_top_issues(
        range: str = Query("7d"),
        limit: int = Query(10, ge=1, le=100),
        repo: RepoSlugParam = None,
    ) -> list[dict[str, Any]]:
        """Most expensive issues in the window (§4.11 point 4)."""
        try:
            window = _parse_range(range)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        now = datetime.now(UTC)
        if ctx is None:
            return build_top_issues(config, since=now - window, until=now, limit=limit)
        per_repo = [
            (slug, build_top_issues(cfg, since=now - window, until=now, limit=limit))
            for cfg, slug in _runtimes(repo)
        ]
        return merge_top_issues(per_repo, limit=limit)

    @router.get("/cost/by-loop")
    def cost_by_loop_route(
        range: str = Query("7d"), repo: RepoSlugParam = None
    ) -> list[dict[str, Any]]:
        """Per-loop tick and wall-clock share over the range (§4.11 point 4)."""
        try:
            window = _parse_range(range)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        now = datetime.now(UTC)
        if ctx is None:
            return build_by_loop(config, since=now - window, until=now)
        return merge_by_loop(
            [
                build_by_loop(cfg, since=now - window, until=now)
                for cfg, _slug in _runtimes(repo)
            ]
        )

    @router.get("/cost/by-model")
    def cost_by_model_route(
        range: str = Query("7d"), repo: RepoSlugParam = None
    ) -> list[dict[str, Any]]:
        """Cross-loop spend broken out by model over the range."""
        try:
            window = _parse_range(range)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        now = _cost_rollups_mod._utcnow()
        if ctx is None:
            return build_cost_by_model(config, since=now - window, until=now)
        return merge_cost_by_model(
            [
                build_cost_by_model(cfg, since=now - window, until=now)
                for cfg, _slug in _runtimes(repo)
            ]
        )

    @router.get("/loops/cost")
    def loops_cost(
        range: str = Query("7d"), repo: RepoSlugParam = None
    ) -> list[dict[str, Any]]:
        """Per-loop machinery-level cost dashboard (§4.11 point 5)."""
        try:
            window = _parse_range(range)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        now = datetime.now(UTC)
        if ctx is None:
            return build_per_loop_cost(
                config,
                since=now - window,
                until=now,
                event_bus=_event_bus_for_rollup(config),
            )
        return merge_per_loop_cost(
            [
                build_per_loop_cost(
                    cfg,
                    since=now - window,
                    until=now,
                    event_bus=_event_bus_for_rollup(cfg),
                )
                for cfg, _slug in _runtimes(repo)
            ]
        )

    @router.get("/auto-agent")
    def auto_agent_stats() -> dict[str, Any]:
        """Auto-agent dashboard payload (spec §6.2)."""
        from preflight.audit import PreflightAuditStore  # noqa: PLC0415

        audit = PreflightAuditStore(config.data_root)
        today = audit.query_24h()
        week = audit.query_7d()
        top = audit.top_spend(n=5)
        return {
            "today": _stats_payload(today),
            "last_7d": _stats_payload(week),
            "top_spend": [
                {
                    "issue": e.issue,
                    "sub_label": e.sub_label,
                    "cost_usd": e.cost_usd,
                    "wall_clock_s": e.wall_clock_s,
                    "status": e.status,
                    "ts": e.ts,
                }
                for e in top
            ],
        }

    return router


def _stats_payload(stats: Any) -> dict[str, Any]:
    return {
        "spend_usd": stats.spend_usd,
        "attempts": stats.attempts,
        "resolved": stats.resolved,
        "resolution_rate": stats.resolution_rate,
        "p50_cost_usd": stats.p50_cost_usd,
        "p95_cost_usd": stats.p95_cost_usd,
        "p50_wall_clock_s": stats.p50_wall_clock_s,
        "p95_wall_clock_s": stats.p95_wall_clock_s,
    }
