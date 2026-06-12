"""Atlas routes scope by repo (Phase 5a).

Terms/ADRs/graph are host-only compiled knowledge (D4): ``repo=__all__`` and
``None`` read the default/host repo's roots, a specific slug reads that repo's
roots (so a supervised repo that ships docs renders when selected). The wiki
``discovered`` bucket and the ``graph`` genuinely aggregate across repos under
``__all__`` (namespaced node ids; ``scope_repo``-tagged + deduped orphans).
"""

from __future__ import annotations

from pathlib import Path

from config import HydraFlowConfig
from state import StateTracker
from tests.helpers import find_endpoint, make_dashboard_router, make_registry
from ubiquitous_language import BoundedContext, Term, TermKind, TermStore


def _config_with_term(root: Path, term_name: str, term_id: str) -> HydraFlowConfig:
    repo_root = root
    repo_root.mkdir(parents=True, exist_ok=True)
    store = TermStore(repo_root / "docs" / "wiki" / "terms")
    store.write(
        Term(
            id=term_id,
            name=term_name,
            kind=TermKind.SERVICE,
            bounded_context=BoundedContext.SHARED_KERNEL,
            definition=f"{term_name} definition.",
            invariants=[],
            code_anchor=f"src/{term_name.lower()}.py",
            confidence="accepted",
        )
    )
    return HydraFlowConfig(repo_root=repo_root)


def _seed_orphan_wiki(cfg: HydraFlowConfig, entry_id: str, issue: str) -> None:
    d = cfg.repo_root / cfg.repo_wiki_path / "acme" / "widgets" / "architecture"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{entry_id}-issue-{issue}-note.md").write_text("# note\n", encoding="utf-8")


def _two_repo_router(tmp_path: Path):
    # App/host config == org-a; registry holds org-a (default) + org-b.
    cfg_a = _config_with_term(tmp_path / "a", "EventBus", "01A0000000000000000000")
    cfg_b = _config_with_term(tmp_path / "b", "WidgetFactory", "01B0000000000000000000")
    state_a = StateTracker(tmp_path / "state_a.json")
    state_b = StateTracker(tmp_path / "state_b.json")
    registry = make_registry(
        {"slug": "org-a", "config": cfg_a, "state": state_a, "orchestrator": None},
        {"slug": "org-b", "config": cfg_b, "state": state_b, "orchestrator": None},
    )
    router, _ = make_dashboard_router(
        cfg_a,
        None,
        state_a,
        tmp_path,
        registry=registry,
        default_repo_slug="org-a",
    )
    return router, cfg_a, cfg_b


def test_terms_scope_to_selected_repo(tmp_path: Path):
    router, _a, _b = _two_repo_router(tmp_path)
    terms = find_endpoint(router, "/api/atlas/terms", method="GET")
    assert {t["name"] for t in terms(repo="org-a")} == {"EventBus"}
    assert {t["name"] for t in terms(repo="org-b")} == {"WidgetFactory"}


def test_terms_all_and_none_are_host_only(tmp_path: Path):
    router, _a, _b = _two_repo_router(tmp_path)
    terms = find_endpoint(router, "/api/atlas/terms", method="GET")
    # D4: terms are host-only compiled knowledge — __all__ and None both read
    # the host/default (org-a) roots, NOT a union.
    assert {t["name"] for t in terms(repo="__all__")} == {"EventBus"}
    assert {t["name"] for t in terms(repo=None)} == {"EventBus"}


def test_graph_all_namespaces_node_ids_per_repo(tmp_path: Path):
    router, _a, _b = _two_repo_router(tmp_path)
    graph = find_endpoint(router, "/api/atlas/graph", method="GET")
    body = graph(include_adrs=False, include_entries=False, repo="__all__")
    ids = {n["id"] for n in body["nodes"]}
    # Every node is namespaced by its owning repo slug so ids can't collide.
    assert any(i.startswith("org-a/") for i in ids)
    assert any(i.startswith("org-b/") for i in ids)
    assert all(i.startswith(("org-a/", "org-b/")) for i in ids)
    # Contexts namespaced too (so the term's parent ref resolves within-repo).
    ctx_ids = {c["id"] for c in body["contexts"]}
    assert all(c.startswith(("org-a/", "org-b/")) for c in ctx_ids)


def test_graph_single_repo_keeps_unprefixed_ids(tmp_path: Path):
    router, _a, _b = _two_repo_router(tmp_path)
    graph = find_endpoint(router, "/api/atlas/graph", method="GET")
    body = graph(include_adrs=False, include_entries=False, repo="org-b")
    ids = {n["id"] for n in body["nodes"]}
    # A single repo keeps the legacy un-prefixed term ids.
    assert "01B0000000000000000000" in ids


def test_discovered_all_unions_and_tags_scope_repo(tmp_path: Path):
    router, cfg_a, cfg_b = _two_repo_router(tmp_path)
    # Seed an orphan wiki entry (no term evidence) in each repo, distinct ids.
    _seed_orphan_wiki(cfg_a, "1", "11")
    _seed_orphan_wiki(cfg_b, "2", "22")
    discovered = find_endpoint(router, "/api/atlas/discovered", method="GET")
    rows = discovered(repo="__all__")
    by_id = {r["id"]: r for r in rows}
    assert {"1", "2"} <= set(by_id)
    assert by_id["1"]["scope_repo"] == "org-a"
    assert by_id["2"]["scope_repo"] == "org-b"


def test_discovered_all_dedupes_same_entry_across_repos(tmp_path: Path):
    router, cfg_a, cfg_b = _two_repo_router(tmp_path)
    # The SAME wiki-layout key (owner=acme, repo=widgets, id=1) in both repos.
    _seed_orphan_wiki(cfg_a, "1", "42")
    _seed_orphan_wiki(cfg_b, "1", "42")
    discovered = find_endpoint(router, "/api/atlas/discovered", method="GET")
    rows = discovered(repo="__all__")
    # Dedup by (owner, repo, id): exactly one survives, the first repo wins.
    assert [r["id"] for r in rows].count("1") == 1
    assert next(r for r in rows if r["id"] == "1")["scope_repo"] == "org-a"


def test_term_loops_all_nests_per_repo(tmp_path: Path):
    router, _a, _b = _two_repo_router(tmp_path)
    status = find_endpoint(router, "/api/atlas/term-loops/status", method="GET")
    body = status(repo="__all__")
    assert {r["repo"] for r in body["repos"]} == {"org-a", "org-b"}
    # Each repo entry carries the loop snapshot.
    assert "term_proposer" in body["repos"][0]["loops"]


def test_term_loops_single_repo_is_flat(tmp_path: Path):
    router, _a, _b = _two_repo_router(tmp_path)
    status = find_endpoint(router, "/api/atlas/term-loops/status", method="GET")
    body = status(repo="org-a")
    # Specific slug → flat loop map (backward-compatible shape).
    assert "term_proposer" in body
    assert "repos" not in body
