"""Factory health dashboard routes.

Exposes a single endpoint that returns longitudinal analysis of
retrospective metrics: rolling averages, memory-impact cohorts,
and regression detection.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter

from factory_health import compute_summary
from route_types import RepoSlugParam

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from dashboard_routes._routes import RouteContext

logger = logging.getLogger("hydraflow.dashboard.factory_health")


def _load_jsonl(path: Any) -> list[dict[str, Any]]:
    """Load entries from a JSONL file, skipping malformed lines."""
    try:
        if not path.exists():
            return []
    except OSError:
        return []
    entries: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    entries.append(obj)
    except OSError as exc:
        logger.warning("Failed to read %s: %s", path, exc)
    return entries


def build_factory_health_router(
    config: HydraFlowConfig, ctx: RouteContext | None = None
) -> APIRouter:
    """Build the ``/api/factory-health`` router.

    With *ctx* the summary honors a ``repo`` query param: ``repo=__all__``
    unions every repo's (D2-scoped) retrospective + telemetry stores, a specific
    slug scopes to that repo, and ``None`` resolves the default. Without *ctx*
    (legacy single-repo callers) it reads the bare *config* stores unchanged.
    """

    router = APIRouter(prefix="/api/factory-health", tags=["factory-health"])

    def _tagged(path: Any, slug: str) -> list[dict[str, Any]]:
        """Load entries from *path*, tagging each with its owning repo slug.

        The slug keeps the cohort join (telemetry → retro, by issue) correct
        when the union spans repos whose issue numbers collide.
        """
        rows = _load_jsonl(path)
        for row in rows:
            row["repo"] = slug
        return rows

    @router.get("/summary")
    def get_factory_health(repo: RepoSlugParam = None) -> dict[str, Any]:
        if ctx is None:
            return compute_summary(
                _load_jsonl(config.retrospectives_path),
                _load_jsonl(config.cost_inferences_path),
            )
        retro_entries: list[dict[str, Any]] = []
        telemetry_entries: list[dict[str, Any]] = []
        for cfg, _s, _b, _g, slug in ctx.resolve_runtimes(repo):
            retro_entries.extend(_tagged(cfg.retrospectives_path, slug))
            telemetry_entries.extend(_tagged(cfg.cost_inferences_path, slug))
        # The union spans per-repo append-only files; the health windows are
        # positional (no timestamp sort downstream), so order by each entry's
        # timestamp to restore a chronological view — "recent N" then means
        # recent across all repos, not just the last file read.
        retro_entries.sort(key=lambda e: str(e.get("timestamp", "")))
        telemetry_entries.sort(key=lambda e: str(e.get("timestamp", "")))
        return compute_summary(retro_entries, telemetry_entries)

    return router
