"""Observable fake for the per-worktree JSONL BeadsManager surface.

The fake deliberately reuses the production JSONL store implementation. This
keeps stable phase identity, validation, locking, and persistence semantics
identical while exposing convenient in-memory snapshots and transition events
for MockWorld assertions. No subprocess or database is involved.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from beads_manager import BeadsManager, BeadTask

if TYPE_CHECKING:
    from task_graph import TaskGraphPhase


@dataclass
class _FakeTask:
    task_id: str
    title: str
    status: str = "open"
    priority: int = 2
    depends_on: list[str] = field(default_factory=list)
    external_ref: str | None = None
    close_reason: str | None = None


class FakeBeads(BeadsManager):
    """Production-parity JSONL manager with scenario-observable snapshots."""

    _is_fake_adapter = True

    def __init__(self) -> None:
        self._tasks: dict[str, _FakeTask] = {}
        self._initialized = False
        self.transitions: list[tuple[str, str]] = []

    def task_ids(self) -> list[str]:
        """Return task IDs from the most recently observed worktree store."""
        return list(self._tasks)

    def task_count(self) -> int:
        return len(self._tasks)

    async def ensure_installed(self) -> None:
        await super().ensure_installed()

    async def init(self, cwd: Path) -> None:
        await super().init(cwd)
        self._initialized = True
        await self._refresh(cwd)

    async def export(self, cwd: Path) -> None:
        await super().export(cwd)
        await self._refresh(cwd)

    async def create_task(self, title: str, priority: str, cwd: Path) -> str:
        task_id = await super().create_task(title, priority, cwd)
        await self._refresh(cwd)
        return task_id

    async def add_dependency(self, child: str, parent: str, cwd: Path) -> None:
        await super().add_dependency(child, parent, cwd)
        await self._refresh(cwd)

    async def claim(self, bead_id: str, cwd: Path) -> None:
        await super().claim(bead_id, cwd)
        await self._refresh(cwd)
        self.transitions.append(("claim", bead_id))

    async def close(self, bead_id: str, reason: str, cwd: Path) -> None:
        await super().close(bead_id, reason, cwd)
        await self._refresh(cwd)
        self.transitions.append(("close", bead_id))

    async def list_ready(self, cwd: Path) -> list[BeadTask]:
        ready = await super().list_ready(cwd)
        await self._refresh(cwd)
        return ready

    async def show(self, bead_id: str, cwd: Path) -> BeadTask:
        task = await super().show(bead_id, cwd)
        await self._refresh(cwd)
        return task

    async def create_from_phases(
        self,
        phases: list[TaskGraphPhase],
        issue_number: int,
        cwd: Path,
    ) -> dict[str, str]:
        mapping = await super().create_from_phases(phases, issue_number, cwd)
        await self._refresh(cwd)
        return mapping

    async def _refresh(self, cwd: Path) -> None:
        await asyncio.to_thread(self._refresh_sync, cwd)

    def _refresh_sync(self, cwd: Path) -> None:
        with self._locked_store(cwd) as handle:
            records = self._read_validated_records(handle)
        self._tasks = {
            str(record["id"]): _FakeTask(
                task_id=str(record["id"]),
                title=str(record["title"]),
                status=str(record.get("status", "open")),
                priority=int(record.get("priority", 2)),
                depends_on=self._dependency_ids(record),
                external_ref=(
                    str(record["external_ref"])
                    if isinstance(record.get("external_ref"), str)
                    else None
                ),
                close_reason=(
                    str(record["close_reason"])
                    if isinstance(record.get("close_reason"), str)
                    else None
                ),
            )
            for record in records
            if self._is_issue(record)
        }
