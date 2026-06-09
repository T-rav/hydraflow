"""/api/wiki/* endpoints — read + admin-enqueue routes for the git-backed repo wiki.

Phase 5 of ``docs/git-backed-wiki-design.md``.  Read endpoints traverse
the tracked ``repo_wiki/`` directory under ``config.repo_root`` (the
per-entry layout landed by Phase 2); admin endpoints enqueue
``MaintenanceTask`` entries that ``RepoWikiLoop`` drains on its next
tick.  Nothing here mutates the wiki directly — every write goes
through the single-track commit path that emits the
``chore(wiki): maintenance`` PR.

Follows the ``_memory_routes.py`` pattern: ``register(router, ctx)``
attaches ``@router.<method>`` handlers that close over ``ctx`` for
shared state (config, wiki queue, wiki loop).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException
from pydantic import BaseModel, Field

from route_types import REPO_ALL, RepoSlugParam
from wiki_maint_queue import MaintenanceTask

if TYPE_CHECKING:
    from fastapi import APIRouter

    from config import HydraFlowConfig
    from dashboard_routes._routes import RouteContext

logger = logging.getLogger("hydraflow.dashboard.wiki")

_TOPICS: tuple[str, ...] = (
    "architecture",
    "patterns",
    "gotchas",
    "testing",
    "dependencies",
)

# Filename pattern: ``{id:04d}-issue-{N|unknown}-{slug}.md``.  Parses both
# the id and the issue tag so the API can filter by either.
_ENTRY_FILENAME_RE = re.compile(r"^(\d+)-issue-(\S+?)-(.+)\.md$")


class ForceCompilePayload(BaseModel):
    owner: str = Field(min_length=1)
    repo: str = Field(min_length=1)
    topic: str = Field(min_length=1)


class MarkStalePayload(BaseModel):
    owner: str = Field(min_length=1)
    repo: str = Field(min_length=1)
    entry_id: str = Field(min_length=1)
    reason: str = Field(default="")


class RebuildIndexPayload(BaseModel):
    owner: str = Field(min_length=1)
    repo: str = Field(min_length=1)


def _wiki_loop(get_orch: Callable[[], Any]):
    """Return the ``RepoWikiLoop`` from the resolved orchestrator, or None.

    Takes the repo's zero-arg orchestrator getter (``resolve_runtime(repo)``'s
    4th element) rather than ``ctx`` so each repo's own loop/queue is reached.
    Services live inside ``ServiceRegistry`` on the orchestrator, which is
    constructed after the dashboard.  Looking them up lazily keeps the route
    module decoupled from ``service_registry`` import order.
    """
    orch = get_orch()
    if orch is None:
        return None
    svc = getattr(orch, "_svc", None)
    if svc is None:
        return None
    return getattr(svc, "repo_wiki_loop", None)


def _maintenance_queue(get_orch: Callable[[], Any]):
    """Return the loop's ``MaintenanceQueue``, or None if loop is down."""
    loop = _wiki_loop(get_orch)
    if loop is None:
        return None
    return getattr(loop, "_queue", None)


def _wiki_root(cfg: HydraFlowConfig) -> Path:
    """Absolute path to a repo's tracked ``repo_wiki/`` directory.

    Reads from ``config.repo_root / config.repo_wiki_path`` so the API
    sees what the migration script and phase runners wrote, not the
    legacy ``.hydraflow/repo_wiki/`` layout.
    """
    return (cfg.repo_root / cfg.repo_wiki_path).resolve()


def _repo_dir(cfg: HydraFlowConfig, owner: str, repo: str) -> Path | None:
    """Return the tracked dir for ``{owner}/{repo}`` or None when absent.

    Prevents path traversal via ``..`` or absolute paths in owner/repo.
    """
    if "/" in owner or "/" in repo or ".." in owner or ".." in repo:
        return None
    candidate = _wiki_root(cfg) / owner / repo
    try:
        candidate_resolved = candidate.resolve()
    except OSError:
        return None
    root = _wiki_root(cfg)
    if not str(candidate_resolved).startswith(str(root)):
        return None
    if not candidate_resolved.is_dir():
        return None
    return candidate_resolved


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Split a markdown file into (frontmatter-dict, body-str).

    Tolerates missing frontmatter: returns ``({}, text)`` so downstream
    callers still get the full text rendered as body.
    """
    if not text.startswith("---\n"):
        return {}, text
    try:
        end = text.index("\n---\n", 4)
    except ValueError:
        return {}, text
    block = text[4:end]
    body = text[end + len("\n---\n") :]
    frontmatter: dict[str, str] = {}
    for line in block.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        frontmatter[key.strip()] = value.strip()
    return frontmatter, body


def _entry_summary_from_path(
    *, topic: str, path: Path, owner: str, repo: str
) -> dict[str, Any] | None:
    """Cheap-to-compute summary (frontmatter only, no body) for list views."""
    match = _ENTRY_FILENAME_RE.match(path.name)
    if match is None:
        return None
    entry_id = match.group(1)
    issue_tag = match.group(2)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    frontmatter, _ = _parse_frontmatter(text)
    return {
        "id": entry_id,
        "issue": issue_tag,
        "topic": topic,
        "owner": owner,
        "repo": repo,
        "filename": path.name,
        "status": frontmatter.get("status", "active"),
        "source_phase": frontmatter.get("source_phase", ""),
        "source_issue": frontmatter.get("source_issue", issue_tag),
        "created_at": frontmatter.get("created_at", ""),
    }


def _match_filters(
    summary: dict[str, Any],
    *,
    status: str | None,
    q: str | None,
    body_fetcher,
) -> bool:
    """Apply status + substring filters.  ``body_fetcher`` is a 0-arg
    callable that returns the markdown body (lazily — free-text ``q``
    search loads body text only when status filter is satisfied)."""
    if status and summary["status"] != status:
        return False
    if q:
        needle = q.lower()
        if needle in summary["filename"].lower():
            return True
        if needle in summary.get("source_phase", "").lower():
            return True
        try:
            return needle in body_fetcher().lower()
        except OSError:
            return False
    return True


def register(router: APIRouter, ctx: RouteContext) -> None:
    """Attach /api/wiki/* handlers to ``router``.

    All reads go through the tracked ``repo_wiki/`` layout under
    ``config.repo_root``.  All writes happen via ``MaintenanceQueue``
    drains inside ``RepoWikiLoop`` — the admin endpoints here never
    mutate the wiki directly.
    """

    def _is_all(repo: str | None) -> bool:
        return repo is not None and repo.strip().lower() == REPO_ALL

    def _resolve(repo: str | None) -> tuple[HydraFlowConfig, Callable[[], Any]]:
        """``(config, get_orch)`` for the selected repo.

        ``__all__`` and ``None`` resolve the default/host runtime; a specific
        slug resolves that repo's config + orchestrator (so its own wiki dir
        and RepoWikiLoop/queue are reached).
        """
        cfg, _s, _b, get_orch = ctx.resolve_runtime(None if _is_all(repo) else repo)
        return cfg, get_orch

    def _reject_all(repo: str | None) -> None:
        if _is_all(repo):
            raise HTTPException(
                status_code=400,
                detail="repo=__all__ is not valid for wiki admin actions; pass a repo slug",
            )

    @router.get("/api/wiki/metrics")
    async def get_wiki_metrics(repo: RepoSlugParam = None) -> dict:
        """Return current knowledge-system counters as a JSON snapshot.

        ``knowledge_metrics`` is a process-wide singleton — its snapshot already
        spans every repo's activity, so ``repo`` is accepted for API symmetry
        but does NOT scope the counters (a per-repo split would need a
        knowledge_metrics refactor, out of scope for this slice).
        """
        from knowledge_metrics import metrics as _metrics  # noqa: PLC0415

        return _metrics.snapshot()

    def _health_snapshot(get_orch: Callable[[], Any]) -> dict:
        result: dict = {"store": "unconfigured", "tribal": "unconfigured"}
        loop = _wiki_loop(get_orch)
        if loop is None:
            return result
        store = getattr(loop, "_wiki_store", None)
        if store is not None:
            try:
                repos = store.list_repos()
            except Exception:  # noqa: BLE001
                repos = []
            result["store"] = "populated" if repos else "empty"
            result["repos"] = len(repos)
        tribal = getattr(loop, "_tribal_store", None)
        if tribal is not None:
            try:
                out = tribal.query()
            except Exception:  # noqa: BLE001
                out = ""
            result["tribal"] = "populated" if out else "empty"
        return result

    @router.get("/api/wiki/health")
    async def get_wiki_health(repo: RepoSlugParam = None) -> dict:
        """Report wiki + tribal store presence and rough sizing.

        ``repo=__all__`` aggregates across every repo's RepoWikiLoop (summed
        ``repos`` count; a state is ``populated`` if any repo is); a specific
        slug (or ``None``) reports that repo's loop.
        """
        if _is_all(repo):
            _precedence = {"populated": 2, "empty": 1, "unconfigured": 0}
            total = 0
            store_state = "unconfigured"
            tribal_state = "unconfigured"
            for _c, _s, _b, get_orch, _slug in ctx.resolve_runtimes(repo):
                snap = _health_snapshot(get_orch)
                total += int(snap.get("repos", 0) or 0)
                if _precedence[snap["store"]] > _precedence[store_state]:
                    store_state = snap["store"]
                if _precedence[snap["tribal"]] > _precedence[tribal_state]:
                    tribal_state = snap["tribal"]
            return {"store": store_state, "tribal": tribal_state, "repos": total}
        return _health_snapshot(_resolve(repo)[1])

    @router.get("/api/wiki/repos")
    def list_wiki_repos(repo: RepoSlugParam = None) -> list[dict[str, str]]:
        def _repos(cfg: HydraFlowConfig) -> list[dict[str, str]]:
            root = _wiki_root(cfg)
            if not root.is_dir():
                return []
            out: list[dict[str, str]] = []
            for owner_dir in sorted(root.iterdir()):
                if not owner_dir.is_dir():
                    continue
                for repo_dir in sorted(owner_dir.iterdir()):
                    if not repo_dir.is_dir():
                        continue
                    if (repo_dir / "index.md").exists() or (
                        repo_dir / "index.json"
                    ).exists():
                        out.append({"owner": owner_dir.name, "repo": repo_dir.name})
            return out

        if _is_all(repo):
            seen: set[tuple[str, str]] = set()
            out: list[dict[str, str]] = []
            for cfg, _s, _b, _g, _slug in ctx.resolve_runtimes(repo):
                for row in _repos(cfg):
                    key = (row["owner"], row["repo"])
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append(row)
            return out
        return _repos(_resolve(repo)[0])

    # The wiki-SUBJECT repo is the `{owner}/{wiki_repo}` path; the OPERATED repo
    # is the `repo` query (which wiki store to read), resolved via _resolve. The
    # path placeholder is `wiki_repo` (not `repo`) so the two don't collide.
    @router.get("/api/wiki/repos/{owner}/{wiki_repo}/entries")
    def list_wiki_entries(
        owner: str,
        wiki_repo: str,
        topic: str | None = None,
        status: str | None = None,
        q: str | None = None,
        limit: int = 100,
        offset: int = 0,
        repo: RepoSlugParam = None,
    ) -> list[dict[str, Any]]:
        repo_dir = _repo_dir(_resolve(repo)[0], owner, wiki_repo)
        if repo_dir is None:
            return []
        topics: tuple[str, ...] = (topic,) if topic else _TOPICS
        out: list[dict[str, Any]] = []
        for t in topics:
            topic_dir = repo_dir / t
            if not topic_dir.is_dir():
                continue
            for entry_path in sorted(topic_dir.glob("*.md")):
                summary = _entry_summary_from_path(
                    topic=t, path=entry_path, owner=owner, repo=wiki_repo
                )
                if summary is None:
                    continue
                if not _match_filters(
                    summary,
                    status=status,
                    q=q,
                    body_fetcher=lambda p=entry_path: p.read_text(encoding="utf-8"),
                ):
                    continue
                out.append(summary)
        offset = max(offset, 0)
        limit = max(limit, 0)
        return out[offset : offset + limit]

    @router.get("/api/wiki/repos/{owner}/{wiki_repo}/entries/{entry_id}")
    def get_wiki_entry(
        owner: str, wiki_repo: str, entry_id: str, repo: RepoSlugParam = None
    ) -> dict[str, Any]:
        repo_dir = _repo_dir(_resolve(repo)[0], owner, wiki_repo)
        if repo_dir is None:
            raise HTTPException(status_code=404, detail="repo not found")
        if not re.fullmatch(r"\d{1,6}", entry_id):
            raise HTTPException(status_code=400, detail="invalid entry id")
        prefix = f"{int(entry_id):04d}-"
        for topic in _TOPICS:
            topic_dir = repo_dir / topic
            if not topic_dir.is_dir():
                continue
            for match in topic_dir.glob(f"{prefix}*.md"):
                text = match.read_text(encoding="utf-8")
                frontmatter, body = _parse_frontmatter(text)
                return {
                    "id": entry_id,
                    "topic": topic,
                    "owner": owner,
                    "repo": wiki_repo,
                    "filename": match.name,
                    "frontmatter": frontmatter,
                    "body": body,
                }
        raise HTTPException(status_code=404, detail="entry not found")

    @router.get("/api/wiki/repos/{owner}/{wiki_repo}/log")
    def get_wiki_log(
        owner: str,
        wiki_repo: str,
        issue: int | None = None,
        limit: int = 200,
        repo: RepoSlugParam = None,
    ) -> list[dict[str, Any]]:
        repo_dir = _repo_dir(_resolve(repo)[0], owner, wiki_repo)
        if repo_dir is None:
            return []
        log_dir = repo_dir / "log"
        if not log_dir.is_dir():
            return []
        if issue is not None:
            candidates = [log_dir / f"{issue}.jsonl"]
        else:
            candidates = sorted(log_dir.glob("*.jsonl"))
        records: list[dict[str, Any]] = []
        for path in candidates:
            if not path.is_file():
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    import json  # noqa: PLC0415

                    records.append(json.loads(stripped))
                except ValueError:
                    continue
        limit = max(limit, 0)
        return records[-limit:] if limit else []

    @router.get("/api/wiki/maintenance/status")
    def get_maintenance_status(repo: RepoSlugParam = None) -> dict[str, Any]:
        # Maintenance is a single-orchestrator concept (one queue + open PR per
        # repo); ``__all__``/``None`` report the host/default repo's loop, a
        # specific slug reports that repo's.
        cfg, get_orch = _resolve(repo)
        loop = _wiki_loop(get_orch)
        queue = _maintenance_queue(get_orch)
        queue_path = (
            queue._path  # noqa: SLF001 — read-only diagnostics
            if queue is not None
            else None
        )
        return {
            "open_pr_url": getattr(loop, "_open_pr_url", None) if loop else None,
            "open_pr_branch": getattr(loop, "_open_pr_branch", None) if loop else None,
            "queue_depth": len(queue.peek()) if queue is not None else 0,
            "queue_path": str(queue_path) if queue_path else None,
            "interval_seconds": cfg.repo_wiki_interval,
            "auto_merge": cfg.repo_wiki_maintenance_auto_merge,
            "coalesce": cfg.repo_wiki_maintenance_pr_coalesce,
        }

    def _admin_queue(repo: str | None):
        """The selected repo's maintenance queue; admin actions reject __all__."""
        _reject_all(repo)
        queue = _maintenance_queue(_resolve(repo)[1])
        if queue is None:
            raise HTTPException(status_code=503, detail="wiki queue unavailable")
        return queue

    @router.post("/api/wiki/admin/force-compile")
    def admin_force_compile(
        payload: ForceCompilePayload, repo: RepoSlugParam = None
    ) -> dict[str, str]:
        _admin_queue(repo).enqueue(
            MaintenanceTask(
                kind="force-compile",
                repo_slug=f"{payload.owner}/{payload.repo}",
                params={"topic": payload.topic},
            )
        )
        return {"status": "queued"}

    @router.post("/api/wiki/admin/mark-stale")
    def admin_mark_stale(
        payload: MarkStalePayload, repo: RepoSlugParam = None
    ) -> dict[str, str]:
        _admin_queue(repo).enqueue(
            MaintenanceTask(
                kind="mark-stale",
                repo_slug=f"{payload.owner}/{payload.repo}",
                params={
                    "entry_id": payload.entry_id,
                    "reason": payload.reason,
                },
            )
        )
        return {"status": "queued"}

    @router.post("/api/wiki/admin/rebuild-index")
    def admin_rebuild_index(
        payload: RebuildIndexPayload, repo: RepoSlugParam = None
    ) -> dict[str, str]:
        _admin_queue(repo).enqueue(
            MaintenanceTask(
                kind="rebuild-index",
                repo_slug=f"{payload.owner}/{payload.repo}",
                params={},
            )
        )
        return {"status": "queued"}

    @router.post("/api/wiki/admin/run-now")
    def admin_run_now(repo: RepoSlugParam = None) -> dict[str, str]:
        """Request that ``RepoWikiLoop`` runs on the next event-loop iteration.

        The loop itself decides timing — this endpoint only flips a flag
        the loop observes; it does not bypass the interval directly.
        Phase 5 delivers the queued-for-soon semantics; Phase 6 may add
        an interrupt path. ``repo=__all__`` is rejected (admin mutation).
        """
        _reject_all(repo)
        loop = _wiki_loop(_resolve(repo)[1])
        if loop is None:
            raise HTTPException(status_code=503, detail="wiki loop unavailable")
        # BaseBackgroundLoop exposes ``trigger_now`` / ``force_tick`` on
        # some loops; fall through to a log-only response if not.
        trigger = getattr(loop, "trigger_now", None) or getattr(
            loop, "force_tick", None
        )
        if callable(trigger):
            trigger()
            return {"status": "triggered"}
        logger.info("Wiki admin run-now received; loop has no trigger hook")
        return {"status": "acknowledged"}
