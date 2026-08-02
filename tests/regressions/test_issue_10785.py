"""Issue #10785: operator console cost/tokens panel — repo + per-repo
cost-per-model over a rolling 24h window.

Pins the ``/api/diagnostics/cost/by-model-by-repo`` endpoint the operator
console's cost panel reads. The endpoint reuses the existing per-repo
``build_cost_by_model`` builder and the ``merge_cost_by_model`` fold
(``group_cost_by_model_by_repo``) — no new cost math — and returns BOTH the
cross-repo aggregate (``all``) and the per-repo breakdown (``repos``) over the
last 24h. Per-run / per-issue cost is intentionally out of scope: the cost
store (``cost_inferences.jsonl``) carries no run/session id.

These tests fail fast if the payload shape the JS adapter (``model/cost.js``)
reads drifts, if the rolling-24h window stops filtering, or if per-repo grouping
regresses.
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

_ENDPOINT = "/api/diagnostics/cost/by-model-by-repo"


def _write_inference(config: HydraFlowConfig, **fields: object) -> None:
    config.cost_inferences_path.parent.mkdir(parents=True, exist_ok=True)
    with config.cost_inferences_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(fields) + "\n")


def _seed(
    config: HydraFlowConfig,
    *,
    issue: int,
    model: str,
    tokens_in: int,
    hours_ago: float = 1.0,
) -> None:
    ts = (datetime.now(UTC) - timedelta(hours=hours_ago)).isoformat()
    _write_inference(
        config,
        timestamp=ts,
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


def test_groups_all_and_per_repo(config, event_bus, state, tmp_path):
    # org-a spends on sonnet; org-b on sonnet + haiku. `all` sums the shared
    # model across repos; `repos` keeps each repo's own cost-per-model list.
    router, _a, _b = _two_repo_router(
        tmp_path,
        event_bus,
        state,
        config,
        seed_a=lambda c: _seed(c, issue=1, model="claude-sonnet-4-6", tokens_in=100),
        seed_b=lambda c: (
            _seed(c, issue=2, model="claude-sonnet-4-6", tokens_in=200),
            _seed(c, issue=3, model="claude-haiku-4-5", tokens_in=40),
        ),
    )
    endpoint = find_endpoint(router, _ENDPOINT)
    body = endpoint(repo=REPO_ALL)

    assert body["window_hours"] == 24
    assert body["window_label"] == "last 24h"

    all_by_model = {r["model"]: r for r in body["all"]}
    # Sonnet appears in both repos → calls + tokens summed into one aggregate row.
    assert all_by_model["claude-sonnet-4-6"]["calls"] == 2
    assert all_by_model["claude-sonnet-4-6"]["input_tokens"] == 300
    assert "claude-haiku-4-5" in all_by_model

    # Per-repo breakdown stays distinct.
    repos = {r["repo"]: r for r in body["repos"]}
    assert set(repos) == {"org-a", "org-b"}
    assert {r["model"] for r in repos["org-a"]["by_model"]} == {"claude-sonnet-4-6"}
    assert {r["model"] for r in repos["org-b"]["by_model"]} == {
        "claude-sonnet-4-6",
        "claude-haiku-4-5",
    }


def test_rolling_window_excludes_rows_older_than_24h(
    config, event_bus, state, tmp_path
):
    # A recent row (1h ago) counts; a 25h-old row is outside the rolling window
    # and must not appear — this is the window's whole job.
    def seed_a(c):
        _seed(c, issue=1, model="model-recent", tokens_in=100, hours_ago=1)
        _seed(c, issue=2, model="model-stale", tokens_in=999, hours_ago=25)

    router, _a, _b = _two_repo_router(
        tmp_path,
        event_bus,
        state,
        config,
        seed_a=seed_a,
        seed_b=lambda c: None,
    )
    body = find_endpoint(router, _ENDPOINT)(repo=REPO_ALL)

    models = {r["model"] for r in body["all"]}
    assert "model-recent" in models
    assert "model-stale" not in models
    recent = next(r for r in body["all"] if r["model"] == "model-recent")
    assert recent["input_tokens"] == 100


def test_empty_window_is_zeros_not_error(config, event_bus, state, tmp_path):
    # No inferences anywhere → aggregate empty, totals zero, each repo zeroed.
    router, _a, _b = _two_repo_router(
        tmp_path,
        event_bus,
        state,
        config,
        seed_a=lambda c: None,
        seed_b=lambda c: None,
    )
    body = find_endpoint(router, _ENDPOINT)(repo=REPO_ALL)

    assert body["all"] == []
    assert body["total_cost_usd"] == 0.0
    assert {r["repo"] for r in body["repos"]} == {"org-a", "org-b"}
    assert all(
        r["total_cost_usd"] == 0.0 and r["by_model"] == [] for r in body["repos"]
    )


def test_payload_contract_fields_are_stable(config, event_bus, state, tmp_path):
    # Contract pin (#10785 P6): the exact keys the JS adapter reads. If any of
    # these names drift, the operator panel silently renders nothing — fail here.
    router, _a, _b = _two_repo_router(
        tmp_path,
        event_bus,
        state,
        config,
        seed_a=lambda c: _seed(c, issue=1, model="claude-sonnet-4-6", tokens_in=100),
        seed_b=lambda c: None,
    )
    body = find_endpoint(router, _ENDPOINT)(repo=REPO_ALL)

    assert set(body) >= {
        "generated_at",
        "window_hours",
        "window_label",
        "total_cost_usd",
        "all",
        "repos",
    }
    row = next(r for r in body["all"] if r["model"] == "claude-sonnet-4-6")
    assert set(row) >= {
        "model",
        "cost_usd",
        "cost_unknown",
        "input_tokens",
        "output_tokens",
    }
    repo_entry = next(r for r in body["repos"] if r["repo"] == "org-a")
    assert set(repo_entry) >= {"repo", "total_cost_usd", "by_model"}


def test_single_repo_install_folds_into_one_repo_bucket(
    config, event_bus, state, tmp_path
):
    # Legacy single-repo path (no registry ctx): still returns the panel shape
    # with one repo bucket, so the frontend adapter needs no special-casing.
    cfg = _repo_config(tmp_path, "solo")
    _seed(cfg, issue=1, model="claude-sonnet-4-6", tokens_in=100)
    router, _ = make_dashboard_router(cfg, event_bus, state, tmp_path)
    body = find_endpoint(router, _ENDPOINT)()

    assert body["window_label"] == "last 24h"
    assert len(body["repos"]) == 1
    assert {r["model"] for r in body["all"]} == {"claude-sonnet-4-6"}
