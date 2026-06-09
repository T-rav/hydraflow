"""Factory Cost rollup endpoints aggregate across repos (Phase 3c-2).

The ``/api/diagnostics/cost/*`` and ``/loops/cost`` endpoints read each repo's
(D2-scoped) cost stores. ``repo=__all__`` unions every repo before aggregating;
a specific slug scopes to that repo. The router is wired with ``ctx`` via
``make_dashboard_router(registry=...)``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from config import HydraFlowConfig
from route_types import REPO_ALL
from tests.conftest import make_state
from tests.helpers import (
    ConfigFactory,
    find_endpoint,
    make_dashboard_router,
    make_registry,
)


def _recent() -> str:
    return (datetime.now(UTC) - timedelta(hours=1)).isoformat()


def _write_inference(config: HydraFlowConfig, **fields) -> None:
    config.cost_inferences_path.parent.mkdir(parents=True, exist_ok=True)
    with config.cost_inferences_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(fields) + "\n")


def _write_loop_trace(config: HydraFlowConfig, loop: str, **fields) -> None:
    from trace_collector import _slug_for_loop  # noqa: PLC0415

    d = config.data_root / "traces" / "_loops" / _slug_for_loop(loop)
    d.mkdir(parents=True, exist_ok=True)
    payload = {"kind": "loop", "loop": loop, **fields}
    (d / f"run-{fields['started_at'].replace(':', '')}.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _seed_inference(
    config: HydraFlowConfig, *, issue: int, model: str, tokens_in: int
) -> None:
    _write_inference(
        config,
        timestamp=_recent(),
        source="implementer",
        tool="claude",
        model=model,
        issue_number=issue,
        input_tokens=tokens_in,
        output_tokens=tokens_in // 2,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
        duration_seconds=float(issue),
        status="success",
    )


def _repo_config(tmp_path: Path, name: str) -> HydraFlowConfig:
    repo_root = tmp_path / name / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    return ConfigFactory.create(repo_root=repo_root, repo=f"org/{name}")


def _two_repo_router(tmp_path, event_bus, state, config, *, seed_a, seed_b):
    cfg_a = _repo_config(tmp_path, "a")
    cfg_b = _repo_config(tmp_path, "b")
    seed_a(cfg_a)
    seed_b(cfg_b)
    registry = make_registry(
        {
            "slug": "org-a",
            "config": cfg_a,
            "state": make_state(tmp_path / "sa"),
            "event_bus": event_bus,
            "orchestrator": None,
        },
        {
            "slug": "org-b",
            "config": cfg_b,
            "state": make_state(tmp_path / "sb"),
            "event_bus": event_bus,
            "orchestrator": None,
        },
    )
    router, _ = make_dashboard_router(
        config, event_bus, state, tmp_path, registry=registry, default_repo_slug="org-a"
    )
    return router, cfg_a, cfg_b


def test_cost_by_model_unions_across_repos(config, event_bus, state, tmp_path):
    router, _a, _b = _two_repo_router(
        tmp_path,
        event_bus,
        state,
        config,
        seed_a=lambda c: _seed_inference(
            c, issue=1, model="claude-sonnet-4-6", tokens_in=100
        ),
        seed_b=lambda c: (
            _seed_inference(c, issue=2, model="claude-sonnet-4-6", tokens_in=200),
            _seed_inference(c, issue=3, model="claude-haiku-4-5", tokens_in=40),
        ),
    )
    by_model = find_endpoint(router, "/api/diagnostics/cost/by-model")
    rows = by_model(range="7d", repo=REPO_ALL)
    by_name = {r["model"]: r for r in rows}
    # Sonnet appears in both repos → calls summed; haiku only in org-b.
    assert by_name["claude-sonnet-4-6"]["calls"] == 2
    assert by_name["claude-sonnet-4-6"]["input_tokens"] == 300
    assert "claude-haiku-4-5" in by_name


def test_cost_by_model_scopes_to_one_repo(config, event_bus, state, tmp_path):
    router, _a, _b = _two_repo_router(
        tmp_path,
        event_bus,
        state,
        config,
        seed_a=lambda c: _seed_inference(
            c, issue=1, model="claude-sonnet-4-6", tokens_in=100
        ),
        seed_b=lambda c: _seed_inference(
            c, issue=2, model="claude-haiku-4-5", tokens_in=40
        ),
    )
    by_model = find_endpoint(router, "/api/diagnostics/cost/by-model")
    rows = by_model(range="7d", repo="org-b")
    assert {r["model"] for r in rows} == {"claude-haiku-4-5"}


def test_top_issues_unions_and_tags_repo(config, event_bus, state, tmp_path):
    # Both repos own an issue #1 — distinct issues, must stay two repo-tagged rows.
    router, _a, _b = _two_repo_router(
        tmp_path,
        event_bus,
        state,
        config,
        seed_a=lambda c: _seed_inference(
            c, issue=1, model="claude-sonnet-4-6", tokens_in=500
        ),
        seed_b=lambda c: _seed_inference(
            c, issue=1, model="claude-sonnet-4-6", tokens_in=300
        ),
    )
    top = find_endpoint(router, "/api/diagnostics/cost/top-issues")
    rows = top(range="7d", limit=10, repo=REPO_ALL)
    assert {(r["issue"], r["repo"]) for r in rows} == {(1, "org-a"), (1, "org-b")}


def test_rolling_24h_unions_totals(config, event_bus, state, tmp_path):
    router, _a, _b = _two_repo_router(
        tmp_path,
        event_bus,
        state,
        config,
        seed_a=lambda c: _seed_inference(
            c, issue=1, model="claude-sonnet-4-6", tokens_in=100
        ),
        seed_b=lambda c: _seed_inference(
            c, issue=2, model="claude-sonnet-4-6", tokens_in=200
        ),
    )
    rolling = find_endpoint(router, "/api/diagnostics/cost/rolling-24h")
    body = rolling(repo=REPO_ALL)
    assert body["window_hours"] == 24
    assert body["total"]["tokens_in"] == 300


def test_cost_by_loop_unions_across_repos(config, event_bus, state, tmp_path):
    def seed(c):
        _write_loop_trace(
            c,
            "rc_budget",
            command=["gh"],
            exit_code=0,
            duration_ms=1000,
            started_at=_recent(),
        )

    router, _a, _b = _two_repo_router(
        tmp_path, event_bus, state, config, seed_a=seed, seed_b=seed
    )
    by_loop = find_endpoint(router, "/api/diagnostics/cost/by-loop")
    rows = by_loop(range="7d", repo=REPO_ALL)
    rc = next(r for r in rows if r["loop"] == "rc_budget")
    # One tick per repo → two ticks unioned; sole loop owns the full share.
    assert rc["ticks"] == 2
    assert rc["share_of_ticks"] == 1.0


def test_loops_cost_unions_across_repos(config, event_bus, state, tmp_path):
    def seed(c):
        _write_loop_trace(
            c,
            "rc_budget",
            command=["gh"],
            exit_code=0,
            duration_ms=2000,
            started_at=_recent(),
        )

    router, _a, _b = _two_repo_router(
        tmp_path, event_bus, state, config, seed_a=seed, seed_b=seed
    )
    loops_cost = find_endpoint(router, "/api/diagnostics/loops/cost")
    rows = loops_cost(range="7d", repo=REPO_ALL)
    rc = next(r for r in rows if r["loop"] == "rc_budget")
    assert rc["ticks"] == 2
    assert rc["wall_clock_seconds"] == 4
