"""/api/atlas/* endpoints — the Atlas knowledge-graph dashboard surface (ADR-0059).

Reads from the existing TermStore at config.repo_root/docs/wiki/terms/ and from
docs/adr/*.md. Sibling to _wiki_routes.py; does not replace it. The Maintenance
sub-tab continues to call /api/wiki/* for run-status; term + ADR data lives here.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException

from route_types import REPO_ALL, RepoSlugParam
from ubiquitous_language import TermStore

if TYPE_CHECKING:
    from fastapi import APIRouter

    from config import HydraFlowConfig
    from dashboard_routes._routes import RouteContext

logger = logging.getLogger("hydraflow.dashboard.atlas")

_ADR_FILENAME_RE = re.compile(r"^(\d{4,5})-(.+)\.md$")
_ADR_TITLE_RE = re.compile(r"^#\s+ADR-\d{4,5}:\s+(.+?)\s*$", re.MULTILINE)
# Same shape as _ENTRY_FILENAME_RE in _wiki_routes.py — kept duplicated to
# avoid coupling _atlas_routes to wiki internals.
_ENTRY_FILENAME_RE = re.compile(r"^(\d+)-issue-(\S+?)-(.+)\.md$")
_WIKI_TOPICS: tuple[str, ...] = (
    "architecture",
    "patterns",
    "gotchas",
    "testing",
    "dependencies",
)


def _terms_root(cfg: HydraFlowConfig) -> Path:
    return (cfg.repo_root / "docs" / "wiki" / "terms").resolve()


def _adr_root(cfg: HydraFlowConfig) -> Path:
    return (cfg.repo_root / "docs" / "adr").resolve()


def _wiki_root(cfg: HydraFlowConfig) -> Path:
    return (cfg.repo_root / cfg.repo_wiki_path).resolve()


def _iter_wiki_entries(cfg: HydraFlowConfig):
    """Yield {id, owner, repo, topic, filename, status} for every wiki entry.

    Walks the tracked ``repo_wiki/`` layout. Used by the entry-graph and
    discovered-bucket endpoints. Yields no results when the directory is
    absent or empty.
    """
    root = _wiki_root(cfg)
    if not root.is_dir():
        return
    for owner_dir in sorted(root.iterdir()):
        if not owner_dir.is_dir():
            continue
        for repo_dir in sorted(owner_dir.iterdir()):
            if not repo_dir.is_dir():
                continue
            for topic in _WIKI_TOPICS:
                topic_dir = repo_dir / topic
                if not topic_dir.is_dir():
                    continue
                for path in sorted(topic_dir.glob("*.md")):
                    m = _ENTRY_FILENAME_RE.match(path.name)
                    if m is None:
                        continue
                    yield {
                        "id": m.group(1),
                        "issue": m.group(2),
                        "topic": topic,
                        "owner": owner_dir.name,
                        "repo": repo_dir.name,
                        "filename": path.name,
                    }


def _term_summary(term) -> dict[str, Any]:
    return {
        "id": term.id,
        "name": term.name,
        "kind": term.kind.value,
        "bounded_context": term.bounded_context.value,
        "code_anchor": term.code_anchor,
        "confidence": term.confidence,
    }


def _term_detail(term, by_id: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": term.id,
        "name": term.name,
        "kind": term.kind.value,
        "bounded_context": term.bounded_context.value,
        "code_anchor": term.code_anchor,
        "confidence": term.confidence,
        "definition": term.definition,
        "invariants": list(term.invariants),
        "aliases": list(term.aliases),
        "edges": [
            {
                "kind": rel.kind.value,
                "target_id": rel.target,
                "target_name": (
                    by_id[rel.target].name if rel.target in by_id else None
                ),
            }
            for rel in term.related
        ],
        "evidence": list(term.evidence),
        "superseded_by": term.superseded_by,
        "superseded_reason": term.superseded_reason,
        # Provenance fields from TermProposerLoop (ADR-0054). All None for
        # hand-authored terms; populated when the loop drafted the term.
        "proposed_by": term.proposed_by,
        "proposed_at": term.proposed_at,
        "proposal_signals": (
            list(term.proposal_signals) if term.proposal_signals is not None else None
        ),
        "proposal_imports_seen": term.proposal_imports_seen,
    }


def _adr_related_terms(body: str) -> list[str]:
    """Extract raw lines from the ADR's '## Related' section.

    Returns the line text (without the leading bullet) for each '- ' bullet.
    Lookup against term names/aliases happens at graph-assembly time.
    """
    out: list[str] = []
    related_match = re.search(r"^##\s+Related\s*$", body, re.MULTILINE)
    if not related_match:
        return out
    rest = body[related_match.end() :].lstrip("\n")
    for line in rest.splitlines():
        if line.startswith("## "):
            break
        stripped = line.strip()
        if stripped.startswith("- "):
            out.append(stripped[2:].strip())
    return out


def _parse_adr_field(body: str, heading: str) -> str:
    """Extract the first non-empty line following '## {heading}'."""
    pattern = re.compile(rf"^##\s+{re.escape(heading)}\s*$", re.MULTILINE)
    m = pattern.search(body)
    if not m:
        return ""
    rest = body[m.end() :].lstrip("\n")
    for line in rest.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            break
        if stripped:
            return stripped
    return ""


def _adr_summary_from_path(path: Path) -> dict[str, Any] | None:
    if path.name == "README.md":
        return None
    m = _ADR_FILENAME_RE.match(path.name)
    if m is None:
        return None
    number = int(m.group(1))
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    title_match = _ADR_TITLE_RE.search(text)
    title = title_match.group(1) if title_match else m.group(2).replace("-", " ")
    return {
        "number": number,
        "title": title,
        "status": _parse_adr_field(text, "Status"),
        "date": _parse_adr_field(text, "Date"),
    }


def _build_graph(
    cfg: HydraFlowConfig,
    *,
    include_adrs: bool,
    include_entries: bool,
    id_prefix: str = "",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, dict[str, str]]]:
    """Assemble one repo's term/ADR/entry graph.

    ``id_prefix`` namespaces every node id, parent ref, and edge endpoint so
    several repos can be unioned (``repo=__all__``) without id collisions; it is
    ``""`` for a single-repo graph (preserving the legacy un-prefixed ids).
    Edges stay within the repo because targets are prefixed identically.
    """

    def _nid(raw: str) -> str:
        return f"{id_prefix}{raw}"

    store = TermStore(_terms_root(cfg))
    terms = store.list()
    contexts_seen: dict[str, dict[str, str]] = {}
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    for term in terms:
        ctx_id = _nid(term.bounded_context.value)
        contexts_seen.setdefault(
            ctx_id, {"id": ctx_id, "label": term.bounded_context.value}
        )
        nodes.append(
            {
                "id": _nid(term.id),
                "type": "term",
                "name": term.name,
                "kind": term.kind.value,
                "confidence": term.confidence,
                "parent": ctx_id,
                "code_anchor": term.code_anchor,
            }
        )
        for rel in term.related:
            edges.append(
                {
                    "source": _nid(term.id),
                    "target": _nid(rel.target),
                    "kind": rel.kind.value,
                }
            )

    if include_adrs:
        adr_root = _adr_root(cfg)
        if adr_root.is_dir():
            term_lookup: dict[str, str] = {}
            for term in terms:
                term_lookup[term.name.lower()] = term.id
                for alias in term.aliases:
                    term_lookup.setdefault(alias.lower(), term.id)

            adr_context_added = False
            for path in sorted(adr_root.glob("*.md")):
                summary = _adr_summary_from_path(path)
                if summary is None:
                    continue
                if not adr_context_added:
                    adr_ctx = _nid("adrs")
                    contexts_seen.setdefault(adr_ctx, {"id": adr_ctx, "label": "adrs"})
                    adr_context_added = True
                adr_id = _nid(f"adr-{summary['number']}")
                nodes.append(
                    {
                        "id": adr_id,
                        "type": "adr",
                        "name": f"ADR-{summary['number']:04d}",
                        "title": summary["title"],
                        "status": summary["status"],
                        "parent": _nid("adrs"),
                    }
                )
                try:
                    text = path.read_text(encoding="utf-8")
                except OSError:
                    continue
                related_lines = _adr_related_terms(text)
                seen_targets: set[str] = set()
                for line in related_lines:
                    line_lower = line.lower()
                    for needle, term_id in term_lookup.items():
                        if term_id in seen_targets:
                            continue
                        pattern = rf"\b{re.escape(needle)}\b"
                        if re.search(pattern, line_lower):
                            edges.append(
                                {
                                    "source": adr_id,
                                    "target": _nid(term_id),
                                    "kind": "relates_to",
                                }
                            )
                            seen_targets.add(term_id)

    if include_entries:
        entry_to_term: dict[str, str] = {}
        term_by_id = {t.id: t for t in terms}
        for term in terms:
            for entry_id in term.evidence:
                entry_to_term.setdefault(entry_id, term.id)

        for entry in _iter_wiki_entries(cfg):
            eid = entry["id"]
            term_id = entry_to_term.get(eid)
            if term_id is None:
                continue
            anchor = term_by_id.get(term_id)
            parent = _nid(anchor.bounded_context.value) if anchor is not None else None
            node_id = _nid(f"entry-{entry['owner']}-{entry['repo']}-{eid}")
            nodes.append(
                {
                    "id": node_id,
                    "type": "entry",
                    "name": entry["filename"],
                    "topic": entry["topic"],
                    "parent": parent,
                    "owner": entry["owner"],
                    "repo": entry["repo"],
                    "entry_id": eid,
                }
            )
            edges.append(
                {
                    "source": node_id,
                    "target": _nid(term_id),
                    "kind": "evidence_for",
                }
            )

    return nodes, edges, contexts_seen


def register(router: APIRouter, ctx: RouteContext) -> None:
    """Attach /api/atlas/* handlers to ``router``."""

    def _is_all(repo: str | None) -> bool:
        return repo is not None and repo.strip().lower() == REPO_ALL

    def _cfg_for(repo: str | None) -> HydraFlowConfig:
        """Single config for a host-only-parameterized read.

        Atlas terms/ADRs are host-only compiled knowledge (D4): ``__all__`` and
        ``None`` both resolve the default/host repo's roots. A specific slug
        reads that repo's roots so a supervised repo that *does* ship
        ``docs/wiki/terms``/``docs/adr`` renders when selected.
        """
        cfg, _s, _b, _g = ctx.resolve_runtime(None if _is_all(repo) else repo)
        return cfg

    @router.get("/api/atlas/terms")
    def list_atlas_terms(repo: RepoSlugParam = None) -> list[dict[str, Any]]:
        store = TermStore(_terms_root(_cfg_for(repo)))
        return [_term_summary(t) for t in store.list()]

    @router.get("/api/atlas/terms/{term_id}")
    def get_atlas_term(term_id: str, repo: RepoSlugParam = None) -> dict[str, Any]:
        store = TermStore(_terms_root(_cfg_for(repo)))
        terms = store.list()
        by_id = {t.id: t for t in terms}
        if term_id not in by_id:
            raise HTTPException(status_code=404, detail="term not found")
        return _term_detail(by_id[term_id], by_id)

    @router.get("/api/atlas/graph")
    def get_atlas_graph(
        include_adrs: bool = True,
        include_entries: bool = False,
        repo: RepoSlugParam = None,
    ) -> dict[str, Any]:
        if _is_all(repo):
            # Union every repo's graph; namespace node ids by slug so terms
            # sharing an id across repos don't collide. Edges stay within a
            # repo because targets carry the same prefix.
            nodes: list[dict[str, Any]] = []
            edges: list[dict[str, Any]] = []
            contexts: dict[str, dict[str, str]] = {}
            for cfg, _s, _b, _g, slug in ctx.resolve_runtimes(repo):
                n, e, c = _build_graph(
                    cfg,
                    include_adrs=include_adrs,
                    include_entries=include_entries,
                    id_prefix=f"{slug}/",
                )
                nodes.extend(n)
                edges.extend(e)
                contexts.update(c)
            return {"nodes": nodes, "edges": edges, "contexts": list(contexts.values())}
        n, e, c = _build_graph(
            _cfg_for(repo),
            include_adrs=include_adrs,
            include_entries=include_entries,
        )
        return {"nodes": n, "edges": e, "contexts": list(c.values())}

    @router.get("/api/atlas/discovered")
    def list_atlas_discovered(repo: RepoSlugParam = None) -> list[dict[str, Any]]:
        """Wiki entries with no term-evidence backlink (the Discovered bucket).

        The frontend renders these inside a virtual 'discovered' subgraph
        with dashed-grey styling so operators can see what knowledge the
        term proposer hasn't classified yet (ADR-0061). ``repo=__all__`` unions
        every repo's orphans, tagging each with the runtime ``scope_repo`` and
        deduping by the wiki-layout ``(owner, repo, id)``.
        """

        def _orphans(cfg: HydraFlowConfig, slug: str | None = None):
            store = TermStore(_terms_root(cfg))
            linked: set[str] = set()
            for term in store.list():
                for entry_id in term.evidence:
                    linked.add(entry_id)
            for entry in _iter_wiki_entries(cfg):
                if entry["id"] in linked:
                    continue
                yield {**entry, "scope_repo": slug} if slug is not None else entry

        if _is_all(repo):
            seen: set[tuple[str, str, str]] = set()
            out: list[dict[str, Any]] = []
            for cfg, _s, _b, _g, slug in ctx.resolve_runtimes(repo):
                for entry in _orphans(cfg, slug):
                    key = (entry["owner"], entry["repo"], entry["id"])
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append(entry)
            return out
        return list(_orphans(_cfg_for(repo)))

    @router.get("/api/atlas/adrs")
    def list_atlas_adrs(repo: RepoSlugParam = None) -> list[dict[str, Any]]:
        root = _adr_root(_cfg_for(repo))
        if not root.is_dir():
            return []
        out: list[dict[str, Any]] = []
        for path in sorted(root.glob("*.md")):
            summary = _adr_summary_from_path(path)
            if summary is not None:
                out.append(summary)
        return out

    @router.get("/api/atlas/adrs/{number}")
    def get_atlas_adr(number: int, repo: RepoSlugParam = None) -> dict[str, Any]:
        root = _adr_root(_cfg_for(repo))
        if not root.is_dir():
            raise HTTPException(status_code=404, detail="adr dir not found")
        prefix = f"{number:04d}-"
        for path in sorted(root.glob(f"{prefix}*.md")):
            text = path.read_text(encoding="utf-8")
            title_match = _ADR_TITLE_RE.search(text)
            title = (
                title_match.group(1)
                if title_match
                else path.stem.split("-", 1)[-1].replace("-", " ")
            )
            related_lines = _adr_related_terms(text)
            return {
                "number": number,
                "title": title,
                "status": _parse_adr_field(text, "Status"),
                "date": _parse_adr_field(text, "Date"),
                "body": text,
                "related": related_lines,
            }
        raise HTTPException(status_code=404, detail="adr not found")

    def _loops_snapshot(state: Any) -> dict[str, Any]:
        loops = ("term_proposer", "term_pruner", "edge_proposer")
        try:
            heartbeats = state.get_worker_heartbeats()
        except Exception:  # noqa: BLE001 — diagnostics endpoint, never fail
            heartbeats = {}
        out: dict[str, Any] = {}
        for name in loops:
            hb = heartbeats.get(name) or {}
            details = hb.get("details") or {}
            out[name] = {
                "status": hb.get("status") or "unknown",
                "last_run": hb.get("last_run"),
                "last_pr_url": (details.get("open_pr_url") or details.get("pr_url")),
                "last_action_count": details.get("count"),
            }
        return out

    @router.get("/api/atlas/term-loops/status")
    def get_term_loops_status(repo: RepoSlugParam = None) -> dict[str, Any]:
        """Last-tick snapshot for the term-graph maintenance loops (P2-T6).

        Reads from StateTracker.get_worker_heartbeats() — same source the
        SystemPanel background-worker tiles consume. ``repo=__all__`` nests one
        snapshot per repo under ``repos[]``; a specific slug (or ``None``)
        returns that repo's flat loop map.
        """
        if _is_all(repo):
            return {
                "repos": [
                    {"repo": slug, "loops": _loops_snapshot(state)}
                    for _cfg, state, _b, _g, slug in ctx.resolve_runtimes(repo)
                ]
            }
        _cfg, state, _b, _g = ctx.resolve_runtime(repo)
        return _loops_snapshot(state)
