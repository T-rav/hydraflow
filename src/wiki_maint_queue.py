"""Persistent queue of wiki maintenance tasks.

Phase 4 companion to ``RepoWikiLoop``.  Admin actions triggered from the
(future) wiki console — ``force-compile``, ``mark-stale``,
``rebuild-index`` — are enqueued here instead of acting on the wiki
directly.  The loop drains the queue on each tick and bundles the
resulting tracked-layout edits into the ordinary maintenance PR.

Runtime wiki-content writes that fire *outside* an issue worktree (the
reflection bridge, the shipped-with-known-gap persist, and the plan /
review ingest fallbacks) also land here as ``ingest-entry`` tasks
(#9836). They cannot write to the boot-time store because its roots live
under the operator's main checkout — see ``RepoWikiStore(read_only=True)``.
Routing them through the queue lets the loop apply them inside its
ephemeral worktree so the new entries ride the maintenance PR instead of
dirtying ``repo_root``.

This keeps the commit path single-track: every maintenance edit,
automated or human-triggered, goes through the same ``git commit`` that
produces the ``chore(wiki): maintenance`` PR.

Every public mutation reloads the backing file under an advisory lock
before mutating, so independent ``MaintenanceQueue`` instances pointed at
the same path (the loop's long-lived instance plus the transient ones
that the merge / phase paths construct) compose correctly instead of
clobbering one another's writes.

See docs/git-backed-wiki-design.md §Admin action flow.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from file_util import file_lock

if TYPE_CHECKING:
    from collections.abc import Iterable

    from config import HydraFlowConfig
    from repo_wiki import WikiEntry

logger = logging.getLogger("hydraflow.wiki_maint_queue")

MaintenanceKind = Literal[
    "force-compile", "mark-stale", "rebuild-index", "ingest-entry"
]

_ALLOWED_KINDS: tuple[str, ...] = (
    "force-compile",
    "mark-stale",
    "rebuild-index",
    "ingest-entry",
)

# Default on-disk location of the shared maintenance queue. Kept in one
# place so the loop's long-lived queue and the transient enqueue-only
# instances (merge / phase paths) always agree on the file.
_QUEUE_FILENAME = "wiki_maint_queue.json"


@dataclass
class MaintenanceTask:
    """One unit of wiki maintenance.

    ``params`` is a free-form dict whose expected shape depends on
    ``kind``:

    - ``force-compile`` → ``{"topic": str}``
    - ``mark-stale``    → ``{"entry_id": str, "reason": str}``
    - ``rebuild-index`` → ``{}``
    - ``ingest-entry``  → ``{"entry": <WikiEntry.model_dump(mode="json")>}``

    The loop is responsible for validating ``params`` before executing;
    the queue itself stores them opaquely.
    """

    kind: MaintenanceKind
    repo_slug: str
    params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in _ALLOWED_KINDS:
            raise ValueError(f"kind must be one of {_ALLOWED_KINDS}; got {self.kind!r}")


def make_ingest_entry_task(repo_slug: str, entry: WikiEntry) -> MaintenanceTask:
    """Build an ``ingest-entry`` task carrying a serialized ``WikiEntry``.

    The entry is dumped in JSON mode so the params survive the round-trip
    through the queue file and can be rebuilt with
    ``WikiEntry.model_validate(task.params["entry"])`` when the loop
    applies the task inside its worktree.
    """
    return MaintenanceTask(
        kind="ingest-entry",
        repo_slug=repo_slug,
        params={"entry": entry.model_dump(mode="json")},
    )


class MaintenanceQueue:
    """File-backed FIFO of wiki maintenance tasks.

    Multiple instances may point at the same path. Every mutation
    (``enqueue`` / ``drain`` / ``drain_kinds``) reloads the file under an
    advisory lock, mutates the freshly-loaded list, and writes it back —
    so a transient enqueue from the merge path is never lost to a
    concurrent drain by the loop's long-lived instance. Single-host per
    Phase 4; cross-host coordination is an open question in the design
    doc.
    """

    def __init__(self, *, path: Path) -> None:
        self._path = path
        self._lock_path = path.with_name(path.name + ".lock")
        self._tasks: list[MaintenanceTask] = self._load()

    def enqueue(self, task: MaintenanceTask) -> None:
        with file_lock(self._lock_path):
            self._tasks = self._load()
            self._tasks.append(task)
            self._save()

    def peek(self) -> list[MaintenanceTask]:
        """Return a copy of currently-queued tasks without removing them."""
        self._tasks = self._load()
        return list(self._tasks)

    def drain(self) -> list[MaintenanceTask]:
        """Remove and return every currently-queued task.

        Persistence is updated synchronously so a restart mid-drain
        does not double-process tasks. Returns ``[]`` without touching disk
        when the backing file does not exist yet, so a routine drain of an
        empty queue never materialises the file (or its lock).
        """
        if not self._path.exists():
            self._tasks = []
            return []
        with file_lock(self._lock_path):
            drained = self._load()
            self._tasks = []
            if drained:
                self._save()
        return drained

    def drain_kinds(self, kinds: Iterable[str]) -> list[MaintenanceTask]:
        """Remove and return only the tasks whose ``kind`` is in *kinds*.

        Tasks of other kinds stay queued. Lets the loop consume
        ``ingest-entry`` tasks inside the worktree heal without discarding
        console admin tasks (which are drained separately), and vice
        versa. Returns ``[]`` without touching disk when the backing file
        does not exist yet, and only rewrites the file when at least one
        task actually matched — a drain that removes nothing leaves the
        file (and lock) exactly as they were.
        """
        wanted = set(kinds)
        if not self._path.exists():
            return []
        with file_lock(self._lock_path):
            current = self._load()
            matched = [t for t in current if t.kind in wanted]
            if matched:
                self._tasks = [t for t in current if t.kind not in wanted]
                self._save()
            else:
                self._tasks = current
        return matched

    def _load(self) -> list[MaintenanceTask]:
        if not self._path.exists():
            return []
        try:
            raw = json.loads(self._path.read_text() or "[]")
        except json.JSONDecodeError:
            # Corrupt queue file — log and start clean.  Resetting the
            # queue is less disruptive than crashing the factory on
            # boot; admins can re-enqueue from the console.
            logger.warning(
                "Wiki maintenance queue at %s is not valid JSON — "
                "starting with an empty queue",
                self._path,
            )
            return []
        tasks: list[MaintenanceTask] = []
        for item in raw:
            try:
                tasks.append(MaintenanceTask(**item))
            except (TypeError, ValueError) as exc:
                logger.warning("Skipping malformed queue entry %r: %s", item, exc)
        return tasks

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps([asdict(t) for t in self._tasks], indent=2))


def default_queue_path(config: HydraFlowConfig) -> Path:
    """The shared maintenance-queue file under the gitignored data root."""
    return Path(config.data_path(_QUEUE_FILENAME))


def enqueue_wiki_ingest(
    config: HydraFlowConfig,
    repo_slug: str,
    entries: Iterable[WikiEntry],
) -> int:
    """Enqueue one ``ingest-entry`` task per entry onto the shared queue.

    Used by the runtime write paths that fire outside an issue worktree
    (reflection bridge, shipped-with-known-gap, plan / review ingest
    fallback). The ``RepoWikiLoop`` applies the tasks inside its ephemeral
    worktree so the new entries ride the maintenance PR (#9836). Returns
    the number of tasks enqueued. No-op (returns 0) when ``repo_slug`` is
    empty.
    """
    if not repo_slug:
        return 0
    queue = MaintenanceQueue(path=default_queue_path(config))
    count = 0
    for entry in entries:
        queue.enqueue(make_ingest_entry_task(repo_slug, entry))
        count += 1
    return count
