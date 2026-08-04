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
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Query

import dashboard_routes._cost_rollups as _cost_rollups_mod
import finder_calibration as fc
from dashboard_routes._cost_merge import (
    group_cost_by_model_by_repo,
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
from finder_faceplate import (
    FINDER_LOOP_WORKER,
    BaselineLedger,
    baseline_ledger_path,
    build_faceplates,
)
from route_types import REPO_ALL, RepoSlugParam
from vitals.report import latest_verdict_payload

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

    @router.get("/gauntlet-calibration")
    def gauntlet_calibration(repo: RepoSlugParam = None) -> dict[str, Any]:
        """Judge-independence + fail-visible dispatch calibration panel (#10371).

        Reads the append-only fail-open ledger and returns the calibration
        metrics: percent of classed merges carrying an independent verdict, the
        fail-open rate + Shewhart control limit (and whether it is breached), the
        independence-unavailable rate, and disagreement-by-family. This is the
        dashboard panel's data source (the generated arch doc stays a
        deterministic instrument spec).
        """
        import judge_independence as ji
        from audit.metrics import calibration_metrics as sampled_audit_metrics
        from audit.store import AuditSampleLedger

        cfg = _config_for(repo) if repo is not None else config
        records = ji.read_records(ji.ledger_path_for(cfg))
        result = ji.calibration_metrics(records)
        # Sampled adversarial re-audit (#10370): merge the silent-escape
        # estimator's metrics from its own append-only ledger into the shared
        # panel, alongside the judge-independence fail-open metrics.
        samples = AuditSampleLedger(
            cfg.diagnostics_dir / "audit_samples.jsonl"
        ).read_all()
        result["sampled_audit"] = sampled_audit_metrics(samples)
        return result

    @router.get("/finder-faceplates")
    def finder_faceplates(
        repo: RepoSlugParam = None, range: str = Query("7d")
    ) -> dict[str, Any]:
        """Per-finder loop-faceplate panel (#10826).

        Joins each generative finder's measured noise floor (the #10821
        :class:`finder_calibration.CalibrationLedger`, populated on-demand by
        ``scripts/calibrate_finders.py``) with the baseline it was measured
        against and the finder's LIVE finding-rate, into one faceplate row per
        finder: ``calibrated`` + (when calibrated) ``floor_mean`` /
        ``floor_sigma`` / ``threshold`` / ``sample_count`` / ``low_confidence`` /
        ``last_calibrated`` / ``drift_days`` / ``baseline_stale``, plus
        ``live_rate`` and a ``status`` (``within_floor`` | ``above_floor`` |
        ``uncalibrated``) via
        :func:`finder_calibration.indistinguishable_from_floor`.

        **Live finding-rate source (unit caveat):** the per-loop findings-filed
        counter from :func:`build_per_loop_cost` (``BACKGROUND_WORKER_STATUS``
        events), mapped finder→loop via ``FINDER_LOOP_WORKER``, over the
        requested ``range``. This is a windowed, dedup-gated FILED count, whereas
        the floor is a per-single-run flagged count — the same "how many did this
        finder flag recently" quantity but not identically normalized. A finder's
        loop with no telemetry in the window yields ``live_rate: null`` (never an
        invented number). Read-only; an empty ledger yields every finder
        ``calibrated: false`` (pending), never an error.
        """
        cfg = _config_for(repo) if repo is not None else config
        floors = fc.CalibrationLedger(
            fc.calibration_ledger_path(cfg.data_root)
        ).latest_by_finder()
        baselines = BaselineLedger(
            baseline_ledger_path(cfg.data_root)
        ).latest_by_finder()

        # Live finding-rate: per-loop findings-filed over the window. Read-only
        # and fail-soft — a rollup failure yields all-null live rates rather than
        # a 500 on a diagnostics panel whose primary data is the calibration
        # ledger. The narrow catch mirrors the cost endpoints' failure surface
        # (bad range, event-loop, file I/O) without a blanket except.
        live_rates: dict[str, int | None] = dict.fromkeys(FINDER_LOOP_WORKER)
        try:
            window = _parse_range(range)
            now = datetime.now(UTC)
            rows = build_per_loop_cost(
                cfg,
                since=now - window,
                until=now,
                event_bus=_event_bus_for_rollup(cfg),
            )
            filed_by_loop = {
                str(r.get("loop")): int(r.get("issues_filed", 0) or 0) for r in rows
            }
            live_rates = {
                fid: filed_by_loop.get(worker)
                for fid, worker in FINDER_LOOP_WORKER.items()
            }
        except (ValueError, RuntimeError, OSError, KeyError):
            logger.warning("finder-faceplates: live-rate rollup failed", exc_info=True)

        now = datetime.now(UTC)
        finders = build_faceplates(floors, baselines, live_rates, now)
        return {"finders": finders, "generated_at": now.isoformat()}

    @router.get("/second-order-vitals")
    def second_order_vitals(repo: RepoSlugParam = None) -> dict[str, Any]:
        """Green-while-dying residual monitor verdict (#10373).

        Reads the append-only ``vitals.jsonl`` verdict history and returns the
        latest vitals verdict — ``green | watch | diverging`` — with its
        coverage (``n-of-5 reporting``) and the k-of-5 family tally. Read-only
        (Pattern B): the loop computes and reports; this endpoint just surfaces
        the most recent persisted verdict. With no history yet it returns an
        honest ``green (0-of-5 reporting)`` rather than erroring.
        """
        cfg = _config_for(repo) if repo is not None else config
        path = cfg.diagnostics_dir / "vitals.jsonl"
        records: list[dict[str, Any]] = []
        try:
            text = path.read_text(encoding="utf-8") if path.exists() else ""
        except OSError:
            text = ""
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                records.append(obj)
        return latest_verdict_payload(records)

    @router.get("/supervisor/thread")
    def supervisor_thread(
        limit: int = Query(50, ge=1, le=500), repo: RepoSlugParam = None
    ) -> dict[str, Any]:
        """Recent Tier-2 goal-supervisor observations (ADR-0124).

        Read-only: :class:`GoalSupervisorLoop` appends observations to
        ``<data_root>/supervisor_thread.jsonl``; this surfaces the most recent
        ``limit`` (newest last) for the operator console's supervisor panel.
        Each record is honest by construction — assessment, insights, the
        nudges taken (pending verification), the escalations (surfaced, not
        self-done), and the transients deferred. With no thread yet it returns
        an empty list rather than erroring.
        """
        from supervisor_observation import read_thread  # noqa: PLC0415

        cfg = _config_for(repo) if repo is not None else config
        observations = read_thread(cfg, limit=limit)
        return {"observations": observations, "count": len(observations)}

    @router.post("/supervisor/ack")
    def supervisor_ack(
        body: dict[str, Any], repo: RepoSlugParam = None
    ) -> dict[str, Any]:
        """Acknowledge one Tier-2 goal-supervisor escalation (ADR-0124).

        Append-only + honest (rule 6): records ``(ts, escalation)`` to
        ``<data_root>/supervisor_acks.jsonl`` WITHOUT rewriting the supervisor's
        original observation. :func:`supervisor_observation.read_thread` JOINs the
        ack back so the panel renders the escalation as handled and it stops
        driving the verdict — a handled escalation stops nagging, but the record
        of it stays. Scoped to one repo's ``data_root`` (``__all__`` rejected,
        like the per-issue endpoints).
        """
        from supervisor_observation import append_ack  # noqa: PLC0415

        ts = body.get("ts")
        escalation = body.get("escalation")
        if not ts or not escalation:
            raise HTTPException(
                status_code=400, detail="ts and escalation are required"
            )
        cfg = _config_for(repo) if repo is not None else config
        append_ack(cfg, ts=str(ts), escalation=str(escalation))
        return {"status": "ok"}

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
    # None`` keeps the bare single-repo builder. ``/auto-agent`` (Phase 3c-4)
    # reads ONE shared audit.jsonl and filters by each entry's ``repo`` stamp
    # rather than unioning per-repo files.

    def _audit_repos(repo: str | None) -> frozenset[str] | None:
        """Acceptable ``entry.repo`` values for the requested scope (``None`` =
        every repo). Legacy entries (``repo == ""``) were written by the single
        pre-multi-repo host, so they fold into the host/default repo's scope.
        """
        if ctx is None:
            return None
        if repo is not None and repo.strip().lower() == REPO_ALL:
            return None
        default = ctx.resolve_runtimes(None)[0][4]
        slug = default if repo is None else ctx.resolve_runtimes(repo)[0][4]
        return frozenset({slug, ""}) if slug == default else frozenset({slug})

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

    @router.get("/cost/by-model-by-repo")
    def cost_by_model_by_repo(repo: RepoSlugParam = None) -> dict[str, Any]:
        """Repo + per-repo cost-per-model over a rolling 24h window (#10785).

        The operator console's cost/tokens panel reads this single endpoint:
        ``all`` is the cross-repo cost-per-model aggregate and ``repos`` is the
        per-repo breakdown, both over the last 24h (``window_label`` = "last
        24h"). Reuses the existing per-repo ``build_cost_by_model`` builder and
        the ``merge_cost_by_model`` fold via ``group_cost_by_model_by_repo`` — no
        new cost math. The window is fixed at 24h (not ``range``-selectable):
        per-run / per-issue cost is intentionally out of scope because
        ``cost_inferences.jsonl`` carries no run/session id.
        """
        now = _cost_rollups_mod._utcnow()
        since = now - timedelta(hours=24)
        if ctx is None:
            rows = build_cost_by_model(config, since=since, until=now)
            return group_cost_by_model_by_repo(
                [("", rows)], generated_at=now.isoformat()
            )
        per_repo = [
            (slug, build_cost_by_model(cfg, since=since, until=now))
            for cfg, slug in _runtimes(repo)
        ]
        return group_cost_by_model_by_repo(per_repo, generated_at=now.isoformat())

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
    def auto_agent_stats(repo: RepoSlugParam = None) -> dict[str, Any]:
        """Auto-agent dashboard payload (spec §6.2).

        The preflight audit is ONE shared JSONL whose rows carry a ``repo``
        stamp, so scoping filters by that stamp rather than unioning per-repo
        files: ``repo=__all__`` keeps every row, a slug (or the default repo)
        keeps its rows plus legacy unattributed rows for the host.
        """
        from preflight.audit import PreflightAuditStore  # noqa: PLC0415

        repos = _audit_repos(repo)
        audit = PreflightAuditStore(config.data_root)
        today = audit.query_24h(repos)
        week = audit.query_7d(repos)
        top = audit.top_spend(n=5, repos=repos)
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
