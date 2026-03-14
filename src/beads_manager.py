"""Beads task decomposition manager — wraps the ``bd`` CLI."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from subprocess_util import run_subprocess

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from task_graph import TaskGraphPhase

logger = logging.getLogger("hydraflow.beads_manager")

# Priority mapping: Task Graph phases without deps are P0 (critical), others P1.
_PRIORITY_NO_DEPS = "0"
_PRIORITY_HAS_DEPS = "1"


class BeadTask(BaseModel):
    """A single bead task tracked by the ``bd`` CLI."""

    id: str  # hash-based ID, e.g. "bd-a1b2"
    title: str
    status: str = "open"
    priority: str = "1"
    depends_on: list[str] = Field(default_factory=list)


class BeadsManager:
    """Wraps the ``bd`` CLI for structured task decomposition.

    All methods are no-ops when ``beads_enabled`` is ``False`` in config.

    CLI reference (https://github.com/steveyegge/beads):
    - ``bd init`` — initialize project
    - ``bd create "title" -p <priority>`` — create task
    - ``bd dep add <child> <parent>`` — add dependency
    - ``bd update <id> --claim`` — claim task (assignee + in_progress)
    - ``bd close <id> "message"`` — complete task with summary
    - ``bd ready [--json]`` — list unblocked tasks
    - ``bd show <id>`` — view task details
    """

    def __init__(self, config: HydraFlowConfig) -> None:
        self._config = config
        self._enabled = config.beads_enabled

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def is_available(self) -> bool:
        """Check if the ``bd`` CLI is installed and accessible."""
        if not self._enabled:
            return False
        try:
            await run_subprocess("bd", "ready", timeout=10.0)
            return True
        except (RuntimeError, FileNotFoundError, OSError):
            logger.warning("bd CLI not found — beads features disabled")
            return False

    async def init(self, cwd: Path) -> bool:
        """Initialize a beads project in *cwd* (idempotent).

        Returns ``True`` on success, ``False`` on failure or when disabled.
        """
        if not self._enabled:
            return False
        try:
            await run_subprocess("bd", "init", cwd=cwd, timeout=30.0)
            return True
        except (RuntimeError, FileNotFoundError, OSError):
            logger.warning("bd init failed in %s", cwd, exc_info=True)
            return False

    async def create_task(self, title: str, priority: str, cwd: Path) -> str | None:
        """Create a bead task, returning the bead ID or ``None``.

        Uses ``bd create "title" -p <priority>``.
        """
        if not self._enabled:
            return None
        try:
            output = await run_subprocess(
                "bd", "create", title, "-p", priority, cwd=cwd, timeout=30.0
            )
            # Parse bead ID from output — bd uses hash-based IDs like "bd-a1b2"
            match = re.search(r"(bd-[a-f0-9]+(?:\.\d+)*)", output)
            if match:
                return match.group(1)
            # Fallback: try numeric ID
            num_match = re.search(r"#?(\d+)", output)
            if num_match:
                return num_match.group(1)
            logger.warning("Could not parse bead ID from output: %s", output)
            return None
        except (RuntimeError, FileNotFoundError, OSError):
            logger.warning("bd create failed for %r", title, exc_info=True)
            return None

    async def add_dependency(self, child: str, parent: str, cwd: Path) -> bool:
        """Add a dependency: *child* depends on *parent*.

        Returns ``True`` on success.
        """
        if not self._enabled:
            return False
        try:
            await run_subprocess(
                "bd", "dep", "add", child, parent, cwd=cwd, timeout=30.0
            )
            return True
        except (RuntimeError, FileNotFoundError, OSError):
            logger.warning("bd dep add %s %s failed", child, parent, exc_info=True)
            return False

    async def claim(self, bead_id: str, cwd: Path) -> bool:
        """Claim a bead task (mark as in-progress).

        Returns ``True`` on success.
        """
        if not self._enabled:
            return False
        try:
            await run_subprocess(
                "bd", "update", bead_id, "--claim", cwd=cwd, timeout=30.0
            )
            return True
        except (RuntimeError, FileNotFoundError, OSError):
            logger.warning("bd update %s --claim failed", bead_id, exc_info=True)
            return False

    async def close(self, bead_id: str, reason: str, cwd: Path) -> bool:
        """Close a bead task with a summary message.

        Uses ``bd close <id> "message"`` (positional, not a flag).
        Returns ``True`` on success.
        """
        if not self._enabled:
            return False
        try:
            await run_subprocess("bd", "close", bead_id, reason, cwd=cwd, timeout=30.0)
            return True
        except (RuntimeError, FileNotFoundError, OSError):
            logger.warning("bd close %s failed", bead_id, exc_info=True)
            return False

    async def list_ready(self, cwd: Path) -> list[BeadTask]:
        """List unblocked (ready) bead tasks.

        Uses ``bd ready --json`` for reliable parsing.
        Returns an empty list when disabled or on failure.
        """
        if not self._enabled:
            return []
        try:
            output = await run_subprocess(
                "bd", "ready", "--json", cwd=cwd, timeout=30.0
            )
            return self._parse_task_list(output)
        except (RuntimeError, FileNotFoundError, OSError):
            logger.warning("bd ready failed", exc_info=True)
            return []

    async def show(self, bead_id: str, cwd: Path) -> BeadTask | None:
        """Show full details for a bead task.

        Returns ``None`` when disabled or on failure.
        """
        if not self._enabled:
            return None
        try:
            output = await run_subprocess("bd", "show", bead_id, cwd=cwd, timeout=30.0)
            return self._parse_show_output(bead_id, output)
        except (RuntimeError, FileNotFoundError, OSError):
            logger.warning("bd show %s failed", bead_id, exc_info=True)
            return None

    async def create_from_phases(
        self,
        phases: list[TaskGraphPhase],
        issue_number: int,
        cwd: Path,
    ) -> dict[str, str]:
        """Create bead tasks from Task Graph phases with dependency wiring.

        Returns a mapping of ``{phase_id: bead_id}``.
        """
        if not self._enabled:
            return {}

        mapping: dict[str, str] = {}

        # Create all tasks first
        for phase in phases:
            title = f"Issue #{issue_number} — {phase.name}"
            priority = _PRIORITY_NO_DEPS if not phase.depends_on else _PRIORITY_HAS_DEPS
            bead_id = await self.create_task(title, priority, cwd)
            if bead_id:
                mapping[phase.id] = bead_id
            else:
                logger.warning(
                    "Failed to create bead for phase %s of issue #%d",
                    phase.id,
                    issue_number,
                )

        # Wire dependencies
        for phase in phases:
            child_bead = mapping.get(phase.id)
            if not child_bead:
                continue
            for dep_id in phase.depends_on:
                parent_bead = mapping.get(dep_id)
                if parent_bead:
                    await self.add_dependency(child_bead, parent_bead, cwd)
                else:
                    logger.warning(
                        "Dependency %s not found in bead mapping for phase %s",
                        dep_id,
                        phase.id,
                    )

        return mapping

    @staticmethod
    def _parse_task_list(output: str) -> list[BeadTask]:
        """Parse ``bd ready`` output into :class:`BeadTask` instances."""
        tasks: list[BeadTask] = []
        for raw_line in output.strip().splitlines():
            stripped = raw_line.strip()
            if not stripped:
                continue
            # Match hash-based IDs: "bd-a1b2 Title [status]"
            match = re.match(
                r"(bd-[a-f0-9]+(?:\.\d+)*)\s+(.+?)(?:\s+\[(\w+)\])?\s*$",
                stripped,
            )
            if match:
                tasks.append(
                    BeadTask(
                        id=match.group(1),
                        title=match.group(2).strip(),
                        status=match.group(3) or "open",
                    )
                )
                continue
            # Fallback: numeric IDs "#<id> <title> [<status>]"
            num_match = re.match(r"#?(\d+)\s+(.+?)(?:\s+\[(\w+)\])?\s*$", stripped)
            if num_match:
                tasks.append(
                    BeadTask(
                        id=num_match.group(1),
                        title=num_match.group(2).strip(),
                        status=num_match.group(3) or "open",
                    )
                )
        return tasks

    @staticmethod
    def _parse_show_output(bead_id: str, output: str) -> BeadTask:
        """Parse ``bd show`` output into a :class:`BeadTask`."""
        title = ""
        status = "open"
        priority = "1"
        depends_on: list[str] = []

        for raw_line in output.strip().splitlines():
            stripped = raw_line.strip()
            if stripped.lower().startswith("title:"):
                title = stripped.split(":", 1)[1].strip()
            elif stripped.lower().startswith("status:"):
                status = stripped.split(":", 1)[1].strip()
            elif stripped.lower().startswith("priority:"):
                priority = stripped.split(":", 1)[1].strip()
            elif stripped.lower().startswith("depends"):
                deps_text = stripped.split(":", 1)[1].strip()
                depends_on = re.findall(r"(bd-[a-f0-9]+(?:\.\d+)*|\d+)", deps_text)

        return BeadTask(
            id=bead_id,
            title=title or f"Bead {bead_id}",
            status=status,
            priority=priority,
            depends_on=depends_on,
        )
