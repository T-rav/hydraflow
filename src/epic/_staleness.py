"""The stale-epic sweep: epics that stopped moving, and epics already closed
out from under us.

This is the caretaker path (ADR-0029) — it runs on a timer against every
registered epic, so it is the one place that talks to GitHub about epics
nobody asked about.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from config import HydraFlowConfig
from events import EventBus, EventType, HydraFlowEvent
from exception_classify import reraise_on_credit_or_bug
from issue_state import issue_state_is_resolved
from models import (
    EpicState,
    SystemAlertPayload,
)
from pr_manager import PRManager
from state import StateTracker

logger = logging.getLogger("hydraflow.epic")


class EpicStalenessMixin:
    """The stale-epic sweep: epics that stopped moving, and epics already closed out from under us."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``EpicManager.__init__`` or by a sibling
    # mixin. The method declarations are TYPE_CHECKING-only on purpose: a
    # runtime ``...`` body is a real class attribute and would win the MRO
    # over the sibling that really implements it (#11629).
    # ------------------------------------------------------------------
    _bus: EventBus
    _config: HydraFlowConfig
    _prs: PRManager
    _state: StateTracker

    if TYPE_CHECKING:

        def _is_stale(self, epic: EpicState) -> bool: ...  # provided by _progress

    async def _is_closed_on_github(self, epic_number: int) -> bool:
        """True when the epic issue is closed on GitHub (#11371).

        Fail-soft: an unreadable state returns False, so a transient API
        failure degrades to today's behaviour (alert) rather than
        silently suppressing a real stale epic.
        """
        try:
            state = await self._prs.get_issue_state(epic_number)
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.debug("Epic #%d GitHub state unreadable: %s", epic_number, exc)
            return False
        return issue_state_is_resolved(state)

    async def check_stale_epics(self) -> list[int]:
        """Find epics with no recent activity and post a warning comment."""
        stale: list[int] = []
        for epic in self._state.get_all_epic_states().values():
            if epic.closed:
                continue
            if not self._is_stale(epic):
                continue
            # #11371: local ``closed`` is a cache, GitHub is the source of
            # truth (ADR-0041). An epic closed on GitHub but still open in
            # state re-emitted its stale alert EVERY cycle forever — the
            # banner resurrected after every dismiss. Reconcile before
            # alerting and heal the flag; only a genuinely-open epic alarms.
            if await self._is_closed_on_github(epic.epic_number):
                logger.info(
                    "Epic #%d closed on GitHub — healing stale local state "
                    "instead of alerting (#11371)",
                    epic.epic_number,
                )
                self._state.close_epic(epic.epic_number)
                continue
            stale.append(epic.epic_number)
            try:
                await self._prs.post_comment(
                    epic.epic_number,
                    f"**Stale epic warning:** No activity on this epic for "
                    f"{self._config.epic_stale_days} days. "
                    f"Consider reviewing the status of child issues.\n\n"
                    f"---\n*HydraFlow Epic Monitor*",
                )
            except Exception as exc:
                reraise_on_credit_or_bug(exc)
                logger.warning(
                    "Failed to post stale warning for epic #%d, continuing",
                    epic.epic_number,
                    exc_info=True,
                )
            try:
                await self._bus.publish(
                    HydraFlowEvent(
                        type=EventType.SYSTEM_ALERT,
                        data=SystemAlertPayload(
                            message=f"Epic #{epic.epic_number} is stale "
                            f"(no activity for {self._config.epic_stale_days} days)",
                            source="epic_monitor",
                            # #11306: ADVISORY — routes to the notice bell,
                            # not the banner. A stale epic is information;
                            # the banner is reserved for things the operator
                            # must act on now (credit pause, fault, HITL).
                            severity="warning",
                            epic_number=epic.epic_number,
                        ),
                    )
                )
            except Exception as exc:
                reraise_on_credit_or_bug(exc)
                logger.warning(
                    "Failed to publish stale alert for epic #%d, continuing",
                    epic.epic_number,
                    exc_info=True,
                )
        return stale
