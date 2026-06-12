"""/api/wiki/* maintenance surface scopes by repo (Phase 5b).

The RepoWikiLoop/queue is per-orchestrator, so ``maintenance``/``health``/admin
resolve the selected repo's orchestrator: a specific slug reaches that repo's
loop, ``health`` aggregates across repos for ``__all__``, ``/repos`` unions, and
admin mutations reject ``__all__``. ``metrics`` stays process-global.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from config import HydraFlowConfig
from state import StateTracker
from tests.helpers import find_endpoint, make_dashboard_router, make_registry
from wiki_maint_queue import MaintenanceQueue


def _fake_orch(n_repos: int, queue: MaintenanceQueue, pr_url: str) -> MagicMock:
    loop = MagicMock()
    loop._queue = queue
    loop._open_pr_url = pr_url
    loop._open_pr_branch = "wiki-maint"
    store = MagicMock()
    store.list_repos.return_value = [f"r{i}" for i in range(n_repos)]
    loop._wiki_store = store
    loop._tribal_store = None
    svc = MagicMock()
    svc.repo_wiki_loop = loop
    orch = MagicMock()
    orch._svc = svc
    return orch


def _seed_wiki_index(cfg: HydraFlowConfig, owner: str, repo: str) -> None:
    d = cfg.repo_root / cfg.repo_wiki_path / owner / repo
    d.mkdir(parents=True, exist_ok=True)
    (d / "index.md").write_text("# index\n", encoding="utf-8")


@pytest.fixture
def setup(tmp_path: Path):
    cfg_a = HydraFlowConfig(repo_root=tmp_path / "a")
    cfg_b = HydraFlowConfig(repo_root=tmp_path / "b")
    (tmp_path / "a").mkdir(parents=True, exist_ok=True)
    (tmp_path / "b").mkdir(parents=True, exist_ok=True)
    queue_a = MaintenanceQueue(path=tmp_path / "qa.json")
    queue_b = MaintenanceQueue(path=tmp_path / "qb.json")
    orch_a = _fake_orch(2, queue_a, "https://gh/x/pull/1")
    orch_b = _fake_orch(3, queue_b, "https://gh/x/pull/2")
    state_a = StateTracker(tmp_path / "sa.json")
    registry = make_registry(
        {"slug": "org-a", "config": cfg_a, "state": state_a, "orchestrator": orch_a},
        {"slug": "org-b", "config": cfg_b, "state": state_a, "orchestrator": orch_b},
    )
    router, _ = make_dashboard_router(
        cfg_a,
        None,
        state_a,
        tmp_path,
        registry=registry,
        default_repo_slug="org-a",
        get_orch=lambda: orch_a,
    )
    return router, cfg_a, cfg_b, queue_a, queue_b


@pytest.mark.asyncio
async def test_health_scopes_to_one_repo(setup):
    router, *_ = setup
    health = find_endpoint(router, "/api/wiki/health", "GET")
    assert (await health(repo="org-a"))["repos"] == 2
    assert (await health(repo="org-b"))["repos"] == 3


@pytest.mark.asyncio
async def test_health_all_aggregates(setup):
    router, *_ = setup
    health = find_endpoint(router, "/api/wiki/health", "GET")
    body = await health(repo="__all__")
    assert body["repos"] == 5  # 2 + 3 across repos
    assert body["store"] == "populated"


def test_maintenance_status_scopes_to_one_repo(setup):
    router, *_ = setup
    status = find_endpoint(router, "/api/wiki/maintenance/status", "GET")
    assert status(repo="org-a")["open_pr_url"] == "https://gh/x/pull/1"
    assert status(repo="org-b")["open_pr_url"] == "https://gh/x/pull/2"


def test_repos_all_unions_across_repos(setup):
    router, cfg_a, cfg_b, *_ = setup
    _seed_wiki_index(cfg_a, "acme", "alpha")
    _seed_wiki_index(cfg_b, "acme", "beta")
    repos = find_endpoint(router, "/api/wiki/repos", "GET")
    rows = repos(repo="__all__")
    pairs = {(r["owner"], r["repo"]) for r in rows}
    assert ("acme", "alpha") in pairs
    assert ("acme", "beta") in pairs


def _seed_entry(cfg, owner, wiki_repo, topic, entry_id, issue):
    d = cfg.repo_root / cfg.repo_wiki_path / owner / wiki_repo / topic
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{entry_id}-issue-{issue}-note.md").write_text(
        f"---\ntitle: n{issue}\ntopic: {topic}\nstatus: active\nsource_issue: {issue}\n---\nbody {issue}\n",
        encoding="utf-8",
    )


def test_entries_scope_to_the_operated_repo(setup):
    router, cfg_a, cfg_b, *_ = setup
    # Same wiki subject (acme/widgets), a distinct entry in each operated repo.
    _seed_entry(cfg_a, "acme", "widgets", "patterns", "0001", "10")
    _seed_entry(cfg_b, "acme", "widgets", "patterns", "0002", "20")
    entries = find_endpoint(
        router, "/api/wiki/repos/{owner}/{wiki_repo}/entries", "GET"
    )
    a_files = [
        e["filename"] for e in entries(owner="acme", wiki_repo="widgets", repo="org-a")
    ]
    b_files = [
        e["filename"] for e in entries(owner="acme", wiki_repo="widgets", repo="org-b")
    ]
    # Each operated repo's reads stay in its OWN wiki dir.
    assert a_files == ["0001-issue-10-note.md"]
    assert b_files == ["0002-issue-20-note.md"]


def test_admin_force_compile_targets_selected_repo(setup):
    router, _cfg_a, _cfg_b, queue_a, queue_b = setup
    force = find_endpoint(router, "/api/wiki/admin/force-compile", "POST")
    from dashboard_routes._wiki_routes import ForceCompilePayload

    force(
        payload=ForceCompilePayload(owner="acme", repo="alpha", topic="patterns"),
        repo="org-b",
    )
    # Only org-b's queue receives the task.
    assert len(queue_b.peek()) == 1
    assert len(queue_a.peek()) == 0


def test_admin_force_compile_rejects_all(setup):
    router, *_ = setup
    force = find_endpoint(router, "/api/wiki/admin/force-compile", "POST")
    from dashboard_routes._wiki_routes import ForceCompilePayload

    with pytest.raises(HTTPException) as exc:
        force(
            payload=ForceCompilePayload(owner="acme", repo="alpha", topic="patterns"),
            repo="__all__",
        )
    assert exc.value.status_code == 400
