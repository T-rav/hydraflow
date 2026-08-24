"""Releasing an epic: the operator trigger, the guard, and the merge run.

``ReleaseEpicResultError`` is defined here because this is the only place
that raises it — a structured cause the dashboard route turns into an
error response. The layering (``trigger_release`` -> ``_execute_release``
-> ``release_epic`` -> ``_do_release_epic``) exists so the authorisation
check cannot be bypassed by an internal caller.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from config import HydraFlowConfig
from events import EventBus, EventType, HydraFlowEvent
from merge_policy import (
    ROLE_ORCHESTRATOR_REVIEWER,
    MergeApproval,
    enforce_merge_policy,
)
from models import (
    EpicProgress,
    EpicReleasedPayload,
    EpicReleasingPayload,
    EpicState,
)
from pr_manager import PRManager
from state import StateTracker

logger = logging.getLogger("hydraflow.epic")


class ReleaseEpicResultError(RuntimeError):
    """Structured cause for release_epic responses that include an error."""

    def __init__(self, epic_number: int, result: dict[str, object]) -> None:
        self.epic_number = epic_number
        self.result = result
        message = str(result.get("error", "unknown error"))
        super().__init__(f"epic {epic_number} release failed: {message}")


class EpicReleaseMixin:
    """Releasing an epic: the operator trigger, the guard, and the merge run."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``EpicManager.__init__`` or by a sibling
    # mixin. The method declarations are TYPE_CHECKING-only on purpose: a
    # runtime ``...`` body is a real class attribute and would win the MRO
    # over the sibling that really implements it (#11629).
    # ------------------------------------------------------------------
    _background_tasks: set[asyncio.Task[None]]
    _bus: EventBus
    _config: HydraFlowConfig
    _prs: PRManager
    _release_jobs: dict[int, str]
    _release_locks: dict[int, asyncio.Lock]
    _state: StateTracker

    if TYPE_CHECKING:

        def _get_merge_order(
            self, epic: EpicState
        ) -> list[int]: ...  # provided by _merge_order

        def _invalidate_cache(
            self, epic_number: int
        ) -> None: ...  # provided by _manager

        async def _publish_update(
            self, epic_number: int, action: str
        ) -> None: ...  # provided by _manager

        def get_progress(
            self, epic_number: int
        ) -> EpicProgress | None: ...  # provided by _progress

    async def trigger_release(self, epic_number: int) -> dict[str, object]:
        """Trigger async merge sequence and release creation for a bundled epic.

        Returns a dict with job_id and status. Completion is signalled via the
        EPIC_RELEASED WebSocket event (not a polling endpoint).
        """
        epic = self._state.get_epic_state(epic_number)
        if epic is None:
            return {"error": "epic not found", "status": "failed"}

        if epic.closed:
            return {"error": "epic already closed", "status": "failed"}

        if epic.released:
            return {"error": "epic already released", "status": "failed"}

        if epic_number in self._release_jobs:
            return {
                "job_id": self._release_jobs[epic_number],
                "status": "in_progress",
            }

        job_id = f"release-{epic_number}-{int(time.time())}"
        self._release_jobs[epic_number] = job_id

        # Launch background task — store reference to prevent premature GC
        task: asyncio.Task[None] = asyncio.create_task(
            self._execute_release(epic_number, job_id)
        )
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

        return {"job_id": job_id, "status": "started"}

    async def _execute_release(self, epic_number: int, job_id: str) -> None:
        """Background task to merge all child PRs and create a release."""
        try:
            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.EPIC_RELEASING,
                    data=EpicReleasingPayload(epic_number=epic_number, job_id=job_id),
                )
            )

            result = await self.release_epic(epic_number)
            if "error" in result:
                raise ReleaseEpicResultError(epic_number, result)

            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.EPIC_RELEASED,
                    data=EpicReleasedPayload(
                        epic_number=epic_number,
                        job_id=job_id,
                        status="completed",
                    ),
                )
            )
        except Exception as exc:  # noqa: BLE001
            # Background task — must always publish a failure event and clean
            # up state, even for unexpected exception types (#6404).
            logger.warning(
                "Release execution failed for epic #%d",
                epic_number,
                exc_info=True,
            )
            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.EPIC_RELEASED,
                    data=EpicReleasedPayload(
                        epic_number=epic_number,
                        job_id=job_id,
                        status="failed",
                        error=str(exc),
                    ),
                )
            )
        finally:
            self._release_jobs.pop(epic_number, None)

    async def release_epic(self, epic_number: int) -> dict[str, object]:
        """Trigger sequential merge for a bundled epic (called from API).

        Returns a summary dict with merge results.  Idempotent: a second
        call after a successful release returns an error instead of
        attempting duplicate merges.  A per-epic asyncio.Lock prevents
        concurrent invocations from both passing the ``released`` guard.
        """
        async with self._release_locks.setdefault(epic_number, asyncio.Lock()):
            return await self._do_release_epic(epic_number)

    async def _do_release_epic(self, epic_number: int) -> dict[str, object]:
        """Inner (lock-protected) implementation of release_epic."""
        epic = self._state.get_epic_state(epic_number)
        if epic is None:
            return {"error": "epic not found"}

        if epic.released:
            return {"error": "epic has already been released"}

        progress = self.get_progress(epic_number)
        if progress is None or not progress.ready_to_merge:
            return {"error": "epic is not ready to merge"}

        merge_order = self._get_merge_order(epic)
        results: list[dict[str, object]] = []
        for child_num in merge_order:
            halt_msg: str | None = None
            try:
                pr_number = await self._prs.find_pr_for_issue(child_num)
                if not pr_number:
                    # Halt on missing PR — bundle guarantee requires all PRs to merge
                    results.append({"issue": child_num, "status": "no_pr"})
                    halt_msg = f"no PR found for child #{child_num}; bundle halted"
                elif not (
                    policy_verdict := await enforce_merge_policy(
                        config=self._config,
                        prs=self._prs,
                        pr_number=pr_number,
                        actor="hydraflow:epic_release",
                        approvals=[
                            MergeApproval(
                                actor=f"epic-{epic_number}",
                                role=ROLE_ORCHESTRATOR_REVIEWER,
                                source="epic_children_approved",
                            )
                        ],
                        lane="epic_release",
                    )
                ).allowed:
                    # CH-3 (#9731): the bundle only releases when every child
                    # passed review (ready_to_merge) — that approval is this
                    # lane's evidence. A policy deny halts the bundle.
                    results.append(
                        {"issue": child_num, "pr": pr_number, "status": "policy_denied"}
                    )
                    halt_msg = (
                        f"merge policy denied child #{child_num} "
                        f"(PR #{pr_number}): {policy_verdict.reason}; bundle halted"
                    )
                else:
                    merged = await self._prs.merge_pr(pr_number)
                    if merged:
                        self._state.mark_epic_child_complete(epic_number, child_num)
                        results.append(
                            {"issue": child_num, "pr": pr_number, "status": "merged"}
                        )
                    else:
                        results.append(
                            {"issue": child_num, "pr": pr_number, "status": "failed"}
                        )
                        halt_msg = f"merge failed for child #{child_num} (PR #{pr_number}); bundle halted"
            except RuntimeError:
                logger.warning(
                    "Failed to merge child #%d of epic #%d",
                    child_num,
                    epic_number,
                    exc_info=True,
                )
                results.append({"issue": child_num, "status": "error"})
                halt_msg = f"exception merging child #{child_num}; bundle halted"
            if halt_msg:
                await self._publish_update(epic_number, "release_failed")
                return {
                    "epic_number": epic_number,
                    "merges": results,
                    "error": halt_msg,
                }

        # Mark epic as released to prevent duplicate release attempts
        epic = self._state.get_epic_state(epic_number)
        if epic is not None:
            epic.released = True
            self._state.upsert_epic_state(epic)
        self._invalidate_cache(epic_number)

        await self._publish_update(epic_number, "released")
        return {"epic_number": epic_number, "merges": results}
