"""Persistent queue of wiki maintenance tasks.

Phase 4 companion to ``RepoWikiLoop``.  Admin actions triggered from the
(future) wiki console — ``force-compile``, ``mark-stale``,
``rebuild-index`` — are enqueued here instead of acting on the wiki
directly.  The loop drains the queue on each tick and bundles the
resulting tracked-layout edits into the ordinary maintenance PR.

This keeps the commit path single-track: every maintenance edit,
automated or human-triggered, goes through the same ``git commit`` that
produces the ``chore(wiki): maintenance`` PR.

See docs/git-backed-wiki-design.md §Admin action flow.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger("hydraflow.wiki_maint_queue")

MaintenanceKind = Literal["force-compile", "mark-stale", "rebuild-index"]

_ALLOWED_KINDS: tuple[str, ...] = (
    "force-compile",
    "mark-stale",
    "rebuild-index",
)


@dataclass
class MaintenanceTask:
    """One unit of human-triggered wiki maintenance.

    ``params`` is a free-form dict whose expected shape depends on
    ``kind``:

    - ``force-compile`` → ``{"topic": str}``
    - ``mark-stale``    → ``{"entry_id": str, "reason": str}``
    - ``rebuild-index`` → ``{}``

    The loop is responsible for validating ``params`` before executing;
    the queue itself stores them opaquely.
    """

    kind: MaintenanceKind
    repo_slug: str
    params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in _ALLOWED_KINDS:
            raise ValueError(f"kind must be one of {_ALLOWED_KINDS}; got {self.kind!r}")


class MaintenanceQueue:
    """In-memory FIFO with JSON persistence.

    One queue per HydraFlow process.  The persistence file is gitignored
    operational state (``.hydraflow/wiki_maint_queue.json`` by default).
    Single-host / single-writer per Phase 4; multi-host coordination is
    listed as an open question in the design doc.
    """

    def __init__(self, *, path: Path) -> None:
        self._path = path
        self._tasks: list[MaintenanceTask] = self._load()

    def enqueue(self, task: MaintenanceTask) -> None:
        self._tasks.append(task)
        self._save()

    def peek(self) -> list[MaintenanceTask]:
        """Return a copy of currently-queued tasks without removing them."""
        return list(self._tasks)

    def drain(self) -> list[MaintenanceTask]:
        """Remove and return every currently-queued task.

        Persistence is updated synchronously so a restart mid-drain
        does not double-process tasks.
        """
        drained = list(self._tasks)
        self._tasks.clear()
        self._save()
        return drained

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
