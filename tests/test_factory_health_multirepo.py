"""Factory-health summary aggregates across repos (Phase 3c-3).

``/api/factory-health/summary`` reads each repo's (D2-scoped) retrospective +
telemetry stores. ``repo=__all__`` unions every repo (sorting the merged
entries by timestamp so the positional health windows stay chronological); a
specific slug scopes to that repo. The router is wired with ``ctx`` via
``make_dashboard_router(registry=...)``.
"""

from __future__ import annotations

import json
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


def _retro(issue: int, ts: str) -> dict:
    return {
        "issue_number": issue,
        "pr_number": issue,
        "timestamp": ts,
        "plan_accuracy_pct": 90.0,
        "planned_files": [],
        "actual_files": [],
        "unplanned_files": [],
        "missed_files": [],
        "quality_fix_rounds": 1,
        "review_verdict": "approve",
        "reviewer_fixes_made": 0,
        "ci_fix_rounds": 0,
        "duration_seconds": 100.0,
    }


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


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
    return router


def _cohort_total(summary: dict) -> int:
    cohorts = summary["cohorts"]
    return cohorts["memory_available"]["count"] + cohorts["memory_unavailable"]["count"]


def test_factory_health_unions_retros_across_repos(config, event_bus, state, tmp_path):
    router = _two_repo_router(
        tmp_path,
        event_bus,
        state,
        config,
        seed_a=lambda c: _write_jsonl(
            c.retrospectives_path, [_retro(1, "2026-06-08T01:00:00Z")]
        ),
        seed_b=lambda c: _write_jsonl(
            c.retrospectives_path, [_retro(2, "2026-06-08T02:00:00Z")]
        ),
    )
    summary = find_endpoint(router, "/api/factory-health/summary")
    body = summary(repo=REPO_ALL)
    # Both repos' retrospectives are folded into the aggregate cohorts.
    assert _cohort_total(body) == 2


def test_factory_health_scopes_to_one_repo(config, event_bus, state, tmp_path):
    router = _two_repo_router(
        tmp_path,
        event_bus,
        state,
        config,
        seed_a=lambda c: _write_jsonl(
            c.retrospectives_path, [_retro(1, "2026-06-08T01:00:00Z")]
        ),
        seed_b=lambda c: _write_jsonl(
            c.retrospectives_path,
            [_retro(2, "2026-06-08T02:00:00Z"), _retro(3, "2026-06-08T03:00:00Z")],
        ),
    )
    summary = find_endpoint(router, "/api/factory-health/summary")
    assert _cohort_total(summary(repo="org-a")) == 1
    assert _cohort_total(summary(repo="org-b")) == 2


def test_factory_health_memory_cohort_uses_each_repos_telemetry(
    config, event_bus, state, tmp_path
):
    # org-a's issue has telemetry with context → memory_available; org-b's has
    # none → memory_unavailable. The union must read EACH repo's telemetry.
    def seed_a(c):
        _write_jsonl(c.retrospectives_path, [_retro(1, "2026-06-08T01:00:00Z")])
        _write_jsonl(
            c.cost_inferences_path,
            [
                {
                    "issue_number": 1,
                    "context_chars_before": 500,
                    "timestamp": "2026-06-08T00:59:00Z",
                }
            ],
        )

    def seed_b(c):
        _write_jsonl(c.retrospectives_path, [_retro(2, "2026-06-08T02:00:00Z")])

    router = _two_repo_router(
        tmp_path, event_bus, state, config, seed_a=seed_a, seed_b=seed_b
    )
    summary = find_endpoint(router, "/api/factory-health/summary")
    body = summary(repo=REPO_ALL)
    assert body["cohorts"]["memory_available"]["count"] == 1
    assert body["cohorts"]["memory_unavailable"]["count"] == 1


def test_factory_health_cohort_join_does_not_cross_repos(
    config, event_bus, state, tmp_path
):
    # Both repos own issue #1 (every repo numbers from 1). org-a has memory
    # telemetry for #1; org-b does not. org-b's #1 must NOT be marked
    # memory-available by org-a's telemetry — the join is keyed on (repo, issue).
    def seed_a(c):
        _write_jsonl(c.retrospectives_path, [_retro(1, "2026-06-08T01:00:00Z")])
        _write_jsonl(
            c.cost_inferences_path,
            [
                {
                    "issue_number": 1,
                    "context_chars_before": 500,
                    "timestamp": "2026-06-08T00:59:00Z",
                }
            ],
        )

    def seed_b(c):
        _write_jsonl(c.retrospectives_path, [_retro(1, "2026-06-08T02:00:00Z")])

    router = _two_repo_router(
        tmp_path, event_bus, state, config, seed_a=seed_a, seed_b=seed_b
    )
    summary = find_endpoint(router, "/api/factory-health/summary")
    body = summary(repo=REPO_ALL)
    assert body["cohorts"]["memory_available"]["count"] == 1
    assert body["cohorts"]["memory_unavailable"]["count"] == 1
