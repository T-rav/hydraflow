"""Beads task-graph lifecycle for ``ImplementPhase``.

Extracted VERBATIM from ``src/implement_phase.py`` (god-class
decomposition, Refs #11547) as a mixin — the shape ``review_phase/`` already
uses. ``ImplementPhase`` inherits it, so every method here still resolves as
an attribute of ``ImplementPhase`` and instance/class-level patching in tests
still lands.

One concern: the per-worktree Beads JSONL store — creating the issue's phase
graph inside the agent's own worktree before the build, and closing it in
dependency order after a verified success. Both are best-effort: a Beads
failure never blocks implementation.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from beads_manager import BeadsManager
    from config import HydraFlowConfig
    from models import Task
    from state import StateTracker

logger = logging.getLogger("hydraflow.implement_phase")


class ImplementBeadsMixin:
    """Beads task-graph lifecycle for ``ImplementPhase``."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``ImplementPhase.__init__`` or by
    # a sibling mixin. The method declarations are TYPE_CHECKING-only
    # on purpose: a runtime ``...`` body would win over the
    # real implementation whenever this mixin precedes the
    # implementing one in ``ImplementPhase``'s MRO.
    # ------------------------------------------------------------------
    _beads_manager: BeadsManager | None
    _config: HydraFlowConfig
    _state: StateTracker

    if TYPE_CHECKING:

        def _read_plan_for_recording(
            self, issue_number: int
        ) -> str: ...  # provided by _build

    async def _create_beads_in_worktree(
        self, issue: Task, wt_path: Path
    ) -> dict[str, str] | None:
        """Create the issue's bead task graph in its own worktree store.

        Beads are created in the same per-worktree JSONL store that owns their
        lifecycle. The host ``bd`` CLI is deliberately excluded because its
        storage engine is database-backed. This replaces the old split where
        the planner created beads in a separate host store the agent's clone
        never saw. Best-effort: a beads failure must never block implementation.
        """
        from agent import AgentRunner  # noqa: PLC0415
        from task_graph import extract_phases, topological_sort  # noqa: PLC0415

        manager = self._beads_manager
        if manager is None:
            return None
        # The plan lives in the issue's "## Implementation Plan" comment (the
        # same source the agent reads); the issue was enriched with comments
        # just above. Fall back to the on-disk plan for safety.
        plan, _ = AgentRunner._extract_plan_comment(issue.comments)
        if not plan:
            plan = self._read_plan_for_recording(issue.id)
        if not plan:
            return None
        mapping: dict[str, str] | None = None
        try:
            phases = topological_sort(extract_phases(plan))
            if not phases:
                return None
            await manager.ensure_installed()
            await manager.init(wt_path)
            # The state mapping is only a cache for downstream prompt/review
            # context. It carries no stable task identity, so same-shaped IDs
            # may refer to an unrelated graph. Always ask the canonical JSONL
            # store to create-or-recover by issue/phase external refs.
            mapping = await manager.create_from_phases(phases, issue.id, wt_path)
            # Persist the identity of a successfully created/validated graph
            # before claiming roots. If one claim fails part-way through, the
            # next attempt can reuse this graph instead of appending another.
            self._state.set_bead_mapping(issue.id, mapping)
            if not self._config.dry_run:
                for phase in phases:
                    if not phase.depends_on:
                        root = await manager.show(mapping[phase.id], wt_path)
                        if root.status == "open":
                            await manager.claim(root.id, wt_path)
                        elif root.status not in {"in_progress", "closed"}:
                            raise RuntimeError(
                                f"root Beads task {root.id} has unexpected status "
                                f"{root.status!r}"
                            )
        except Exception as exc:  # noqa: BLE001
            from exception_classify import reraise_on_credit_or_bug  # noqa: PLC0415

            reraise_on_credit_or_bug(exc)
            logger.warning(
                "bead creation in worktree failed for #%d: %s", issue.id, exc
            )
            return mapping
        return mapping

    async def _complete_beads_after_success(
        self,
        mapping: dict[str, str],
        wt_path: Path,
    ) -> bool | None:
        """Close a successful phase graph in dependency order.

        AgentRunner is one opaque multi-phase session, so the factory can
        observe only the overall verified result. Root tasks are claimed
        before that session starts. Once it succeeds, this method repeatedly
        claims and closes the ready frontier, preserving dependency order and
        ensuring every task passes through ``in_progress``. Failed or
        interrupted runs never call this method, leaving roots in progress and
        untouched dependents open.
        """

        manager = self._beads_manager
        if manager is None:
            return None
        remaining = set(mapping.values())
        changed = False
        try:
            for bead_id in tuple(remaining):
                task = await manager.show(bead_id, wt_path)
                if task.status == "closed":
                    remaining.remove(bead_id)
                elif task.status not in {"open", "in_progress"}:
                    raise RuntimeError(
                        f"Beads task {task.id} has unexpected status {task.status!r}"
                    )
            while remaining:
                ready = await manager.list_ready(wt_path)
                frontier = [task for task in ready if task.id in remaining]
                if not frontier:
                    raise RuntimeError(
                        "successful implementation has no ready Beads tasks "
                        f"for remaining IDs: {sorted(remaining)}"
                    )
                for task in frontier:
                    if task.status == "open":
                        await manager.claim(task.id, wt_path)
                        changed = True
                    elif task.status != "in_progress":
                        raise RuntimeError(
                            f"ready Beads task {task.id} has unexpected status "
                            f"{task.status!r}"
                        )
                    await manager.close(
                        task.id,
                        "Phase complete",
                        wt_path,
                    )
                    changed = True
                    remaining.remove(task.id)
        except (KeyError, OSError, RuntimeError, ValueError) as exc:
            logger.warning(
                "bead lifecycle completion failed in %s: %s",
                wt_path,
                exc,
            )
            return None
        return changed
