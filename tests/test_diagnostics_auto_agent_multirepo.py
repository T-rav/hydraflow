"""Auto-agent stats scope by repo (Phase 3c-4).

Unlike the cost/health endpoints, the preflight audit is ONE shared
``auto_agent/audit.jsonl`` whose rows carry a ``repo`` stamp. So
``/api/diagnostics/auto-agent`` filters by that stamp rather than unioning
per-repo files: ``repo=__all__`` keeps every row, a slug (or the default repo)
keeps its rows plus legacy unattributed (``repo == ""``) rows for the host.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from config import HydraFlowConfig
from preflight.audit import PreflightAuditStore
from route_types import REPO_ALL
from tests.helpers import find_endpoint, make_dashboard_router, make_registry


def _recent() -> str:
    return (datetime.now(UTC) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")


def _entry(issue: int, repo: str, cost: float) -> dict:
    return {
        "ts": _recent(),
        "issue": issue,
        "sub_label": "hydraflow-ready",
        "attempt_n": 1,
        "prompt_hash": "",
        "cost_usd": cost,
        "wall_clock_s": 1.0,
        "tokens": 10,
        "status": "resolved",
        "pr_url": None,
        "diagnosis": "",
        "llm_summary": "",
        "repo": repo,
    }


def _seed_audit(config: HydraFlowConfig, entries: list[dict]) -> None:
    path = config.data_root / "auto_agent" / "audit.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n")


def _router(config, event_bus, state, tmp_path):
    registry = make_registry({"slug": "org-a"}, {"slug": "org-b"})
    router, _ = make_dashboard_router(
        config, event_bus, state, tmp_path, registry=registry, default_repo_slug="org-a"
    )
    return find_endpoint(router, "/api/diagnostics/auto-agent")


# 2 org-a rows, 1 org-b row, 1 legacy (pre-multi-repo, unattributed).
_ENTRIES = [
    _entry(1, "org-a", 1.0),
    _entry(2, "org-a", 2.0),
    _entry(3, "org-b", 3.0),
    _entry(4, "", 4.0),
]


def test_auto_agent_all_repos_counts_every_row(config, event_bus, state, tmp_path):
    _seed_audit(config, _ENTRIES)
    auto_agent = _router(config, event_bus, state, tmp_path)
    body = auto_agent(repo=REPO_ALL)
    assert body["today"]["attempts"] == 4


def test_auto_agent_default_repo_includes_legacy_host_rows(
    config, event_bus, state, tmp_path
):
    _seed_audit(config, _ENTRIES)
    auto_agent = _router(config, event_bus, state, tmp_path)
    # Default (org-a) → its 2 rows + the legacy unattributed row (host).
    assert auto_agent(repo=None)["today"]["attempts"] == 3
    assert auto_agent(repo="org-a")["today"]["attempts"] == 3


def test_auto_agent_non_default_repo_excludes_legacy(
    config, event_bus, state, tmp_path
):
    _seed_audit(config, _ENTRIES)
    auto_agent = _router(config, event_bus, state, tmp_path)
    # org-b is not the host → only its own row, no legacy.
    body = auto_agent(repo="org-b")
    assert body["today"]["attempts"] == 1
    assert body["top_spend"][0]["issue"] == 3


def test_auto_agent_legacy_only_single_repo(config, event_bus, state, tmp_path):
    # A pre-3c-4 store (all rows unattributed) still shows under the host/default.
    _seed_audit(config, [_entry(1, "", 1.0), _entry(2, "", 2.0)])
    auto_agent = _router(config, event_bus, state, tmp_path)
    assert auto_agent(repo=None)["today"]["attempts"] == 2
    assert auto_agent(repo=REPO_ALL)["today"]["attempts"] == 2


def test_store_repos_filter(tmp_path):
    # Store-level: repos=None keeps all; a frozenset keeps only those repos.
    cfg_root = tmp_path / "data"
    store = PreflightAuditStore(cfg_root)
    (cfg_root / "auto_agent").mkdir(parents=True, exist_ok=True)
    (cfg_root / "auto_agent" / "audit.jsonl").write_text(
        "\n".join(json.dumps(e) for e in _ENTRIES) + "\n"
    )
    assert store.query_24h().attempts == 4
    assert store.query_24h(frozenset({"org-a", ""})).attempts == 3
    assert store.query_24h(frozenset({"org-b"})).attempts == 1


def test_store_tolerates_forward_compat_extra_keys(tmp_path):
    # A row written by a future version with an unknown field must not crash the
    # reader — unknown keys are dropped, missing keys fall back to defaults.
    cfg_root = tmp_path / "data"
    (cfg_root / "auto_agent").mkdir(parents=True, exist_ok=True)
    row = _entry(1, "org-a", 1.0)
    row["future_field"] = "ignored"
    (cfg_root / "auto_agent" / "audit.jsonl").write_text(json.dumps(row) + "\n")
    store = PreflightAuditStore(cfg_root)
    assert store.query_24h().attempts == 1
