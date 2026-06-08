"""Diagnostics factory-metrics endpoints aggregate across repos (Phase 3c).

``/api/diagnostics/*`` reads each repo's (D2-scoped) ``factory_metrics.jsonl``;
``repo=__all__`` unions every repo's events before aggregating, a specific slug
scopes to that repo, and the per-issue trace endpoints resolve a single repo.
The router is wired with ``ctx`` through ``create_router`` (see _routes.py).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from route_types import REPO_ALL
from tests.conftest import make_state
from tests.helpers import find_endpoint, make_dashboard_router, make_registry


def _recent_ts() -> str:
    return (datetime.now(UTC) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")


def _event(issue: int) -> dict:
    return {
        "timestamp": _recent_ts(),
        "issue": issue,
        "phase": "implement",
        "run_id": 1,
        "tokens": {
            "input": 1000,
            "output": 500,
            "cache_read": 200,
            "cache_creation": 0,
        },
        "tools": {"Read": 5, "Bash": 2},
        "skills": [{"name": "diff-sanity", "passed": True, "attempts": 1}],
        "subagents": 1,
        "duration_seconds": 12.0,
        "crashed": False,
    }


def _repo_metrics_config(tmp_path: Path, name: str, issue: int) -> MagicMock:
    cfg = MagicMock()
    repo_root = tmp_path / name
    # Mirror the D2 layout: per-repo operational stores live under the repo's
    # data_root; factory metrics under data_root/diagnostics. data_root is set
    # explicitly so per-issue trace endpoints (which read cfg.data_root) resolve
    # a real directory rather than a truthy MagicMock that hides path bugs.
    cfg.data_root = repo_root
    cfg.factory_metrics_path = repo_root / "diagnostics" / "factory_metrics.jsonl"
    cfg.factory_metrics_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.factory_metrics_path.write_text(json.dumps(_event(issue)) + "\n")
    return cfg


def _seed_trace(cfg: MagicMock, issue: int, phase: str, run_id: int) -> None:
    """Write a minimal per-run trace summary under the repo's data_root."""
    run_dir = cfg.data_root / "traces" / str(issue) / phase / f"run-{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "summary.json").write_text(
        json.dumps({"run_id": run_id, "tokens": 1700}), encoding="utf-8"
    )


def _registry(event_bus, tmp_path):
    return make_registry(
        {
            "slug": "org-a",
            "config": _repo_metrics_config(tmp_path, "a", 1),
            "state": make_state(tmp_path / "sa"),
            "event_bus": event_bus,
            "orchestrator": None,
        },
        {
            "slug": "org-b",
            "config": _repo_metrics_config(tmp_path, "b", 2),
            "state": make_state(tmp_path / "sb"),
            "event_bus": event_bus,
            "orchestrator": None,
        },
    )


@pytest.mark.asyncio
async def test_diagnostics_overview_unions_across_repos(
    config, event_bus, state, tmp_path
):
    router, _ = make_dashboard_router(
        config,
        event_bus,
        state,
        tmp_path,
        registry=_registry(event_bus, tmp_path),
        default_repo_slug="org-a",
    )
    overview = find_endpoint(router, "/api/diagnostics/overview")
    body = overview(range="7d", repo=REPO_ALL)
    # Two repos, one run each → unioned headline.
    assert body["total_runs"] == 2
    assert body["total_tokens"] == 3400


@pytest.mark.asyncio
async def test_diagnostics_overview_scopes_to_one_repo(
    config, event_bus, state, tmp_path
):
    router, _ = make_dashboard_router(
        config,
        event_bus,
        state,
        tmp_path,
        registry=_registry(event_bus, tmp_path),
        default_repo_slug="org-a",
    )
    overview = find_endpoint(router, "/api/diagnostics/overview")
    body = overview(range="7d", repo="org-b")
    assert body["total_runs"] == 1


@pytest.mark.asyncio
async def test_diagnostics_issues_union_keeps_both_repos(
    config, event_bus, state, tmp_path
):
    router, _ = make_dashboard_router(
        config,
        event_bus,
        state,
        tmp_path,
        registry=_registry(event_bus, tmp_path),
        default_repo_slug="org-a",
    )
    issues = find_endpoint(router, "/api/diagnostics/issues")
    rows = issues(range="7d", sort="tokens", repo=REPO_ALL)
    assert {r["issue"] for r in rows} == {1, 2}


@pytest.mark.asyncio
async def test_diagnostics_issues_rows_carry_repo_attribution(
    config, event_bus, state, tmp_path
):
    router, _ = make_dashboard_router(
        config,
        event_bus,
        state,
        tmp_path,
        registry=_registry(event_bus, tmp_path),
        default_repo_slug="org-a",
    )
    issues = find_endpoint(router, "/api/diagnostics/issues")
    rows = issues(range="7d", sort="tokens", repo=REPO_ALL)
    # Each unioned row knows its owning repo so the UI can disambiguate and the
    # drill-down can scope to the right repo's traces.
    assert {r["repo"] for r in rows} == {"org-a", "org-b"}


@pytest.mark.asyncio
async def test_diagnostics_issues_same_number_across_repos_stays_distinct(
    config, event_bus, state, tmp_path
):
    # Both repos own an issue #1 — they are different issues and must remain two
    # rows, distinguished by repo, not collapsed into one.
    registry = make_registry(
        {
            "slug": "org-a",
            "config": _repo_metrics_config(tmp_path, "a", 1),
            "state": make_state(tmp_path / "sa"),
            "event_bus": event_bus,
            "orchestrator": None,
        },
        {
            "slug": "org-b",
            "config": _repo_metrics_config(tmp_path, "b", 1),
            "state": make_state(tmp_path / "sb"),
            "event_bus": event_bus,
            "orchestrator": None,
        },
    )
    router, _ = make_dashboard_router(
        config, event_bus, state, tmp_path, registry=registry, default_repo_slug="org-a"
    )
    issues = find_endpoint(router, "/api/diagnostics/issues")
    rows = issues(range="7d", sort="tokens", repo=REPO_ALL)
    assert len(rows) == 2
    assert {(r["issue"], r["repo"]) for r in rows} == {(1, "org-a"), (1, "org-b")}


@pytest.mark.asyncio
async def test_diagnostics_issue_phase_scopes_traces_to_one_repo(
    config, event_bus, state, tmp_path
):
    registry = _registry(event_bus, tmp_path)
    # Seed a run trace only under org-b's data_root for issue 2.
    org_b_cfg = registry.get("org-b").config
    _seed_trace(org_b_cfg, issue=2, phase="implement", run_id=1)
    router, _ = make_dashboard_router(
        config, event_bus, state, tmp_path, registry=registry, default_repo_slug="org-a"
    )
    issue_phase = find_endpoint(router, "/api/diagnostics/issue/{issue}/{phase}")
    # Scoped to org-b → the seeded trace is found.
    summaries = issue_phase(issue=2, phase="implement", repo="org-b")
    assert [s["run_id"] for s in summaries] == [1]
    # Scoped to org-a → org-a has no such trace → 404 (proves per-repo scoping).
    with pytest.raises(HTTPException) as excinfo:
        issue_phase(issue=2, phase="implement", repo="org-a")
    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_diagnostics_issue_phase_rejects_repo_all(
    config, event_bus, state, tmp_path
):
    router, _ = make_dashboard_router(
        config,
        event_bus,
        state,
        tmp_path,
        registry=_registry(event_bus, tmp_path),
        default_repo_slug="org-a",
    )
    # Per-issue traces have no single home under __all__; the endpoint must
    # reject the aggregate sentinel rather than silently serving the host repo.
    issue_phase = find_endpoint(router, "/api/diagnostics/issue/{issue}/{phase}")
    with pytest.raises(HTTPException) as excinfo:
        issue_phase(issue=2, phase="implement", repo=REPO_ALL)
    assert excinfo.value.status_code == 400
