"""Formal give-up window — OTP restart-intensity for pipeline child-classes (#10735).

The factory's plan→ready hand-off historically had a retry loop with **no
give-up cap**: a plan whose adversarial review keeps flagging blocking findings
gets routed back to PLAN, re-planned, re-reviewed, and routed back again —
forever (the live #10731 stall). This is a missing OTP *restart-intensity*
window: ``N`` abnormal exits/retries within ``T`` seconds is the signal that a
child is not converging under retry and the supervisor must change strategy.

This module is the single source of truth for that threshold, per child-class
(``build`` / ``review`` / ``loop`` / ``plan_retry``). It consolidates the
scattered attempt counters (``implement`` + ``auto_agent`` + ``route_back``)
behind one explicit, config-driven window.

Design principle (ADR-0105, and Paul's beamlet ``ChildGaveUp → model``): when
the window is exhausted the machine's move is to **self-solve** — auto-decompose
the non-convergent issue into convergent children, or route it to the auto-agent
diagnose path — **not** to dump it on a human. ``human-required`` is the last
resort, emitted only when the self-solve path itself exhausts (and logged as a
break). Routing a convergence-solvable issue straight to a human is HITL
scatter, the anti-pattern this window fixes.

The window is pure policy: it records timestamped give-up events on a state
port and answers "has this issue tripped ``N``-in-``T`` for this class?". The
routing decision (decompose vs diagnose vs human) lives behind
:class:`SelfSolver`, so this module stays free of GitHub/LLM machinery and
is trivially unit-testable.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from config import HydraFlowConfig

__all__ = [
    "GiveUpClass",
    "GiveUpStore",
    "GiveUpTracker",
    "GiveUpWindow",
    "SelfSolveOutcome",
    "SelfSolver",
    "resolve_window",
]


class GiveUpClass(StrEnum):
    """Pipeline child-classes that carry their own restart-intensity window.

    The value is the config-field stem: a class ``X`` reads
    ``giveup_X_max_restarts`` (``N``) and ``giveup_X_window_secs`` (``T``).
    """

    BUILD = "build"
    REVIEW = "review"
    LOOP = "loop"
    PLAN_RETRY = "plan_retry"


@dataclass(frozen=True)
class GiveUpWindow:
    """An ``N``-in-``T`` restart-intensity threshold for one child-class.

    ``max_restarts`` (``N``) abnormal exits/retries within ``window_seconds``
    (``T``) means the child has given up under retry. A count strictly below
    ``N`` is still convergent retry — the common-cause path stays untouched.
    """

    child_class: GiveUpClass
    max_restarts: int
    window_seconds: int

    def is_exhausted(self, count_in_window: int) -> bool:
        """True when *count_in_window* has reached the give-up threshold."""
        return count_in_window >= self.max_restarts


def resolve_window(config: HydraFlowConfig, child_class: GiveUpClass) -> GiveUpWindow:
    """Return the configured window for *child_class* — the single threshold source.

    Reads ``giveup_<class>_max_restarts`` and ``giveup_<class>_window_secs`` off
    the config (both are env-overridable via the standard registry). Every
    consumer (route-back coordinator, build/review/loop supervisors) resolves
    its threshold here so there is exactly one place the numbers live.
    """
    n = int(getattr(config, f"giveup_{child_class.value}_max_restarts"))
    t = int(getattr(config, f"giveup_{child_class.value}_window_secs"))
    return GiveUpWindow(child_class=child_class, max_restarts=n, window_seconds=t)


class SelfSolveOutcome(StrEnum):
    """The disposition of a self-solve attempt after a window is exhausted."""

    # The issue was decomposed into convergent children (ADR-0105) — superseded
    # by an epic; NOT handed to a human.
    DECOMPOSED = "decompose"
    # The issue was routed to the auto-agent diagnose path for
    # resolve-or-dismiss-with-evidence — still a machine self-solve, NOT a human.
    DIAGNOSED = "diagnose"
    # The self-solve path itself exhausted (decompose declined AND diagnose
    # unavailable). Only now is ``human-required`` the correct move — a rare,
    # logged break.
    EXHAUSTED = "human-required"


@runtime_checkable
class SelfSolver(Protocol):
    """Port the give-up terminal calls to self-solve a non-convergent issue.

    The implementation (see :mod:`giveup_self_solve`) runs the ADR-0105
    decompose terminal and falls back to the diagnose label, returning which
    self-solve action fired. Kept a Protocol so the route-back coordinator
    stays decoupled from the epic/decomposer/council machinery and can be
    unit-tested with a trivial fake.
    """

    async def solve(
        self, issue_id: int, *, from_stage: str, reason: str, issue_body: str = ""
    ) -> SelfSolveOutcome:
        """Attempt to self-solve *issue_id*; return the action that fired."""
        ...


@runtime_checkable
class GiveUpStore(Protocol):
    """Persistence port for per-``(issue, class)`` give-up window events.

    Satisfied by ``StateTracker`` via ``GiveUpStateMixin``. Timestamps survive
    restart so an issue that thrashes across a crash still trips its window.
    """

    def record_give_up_event(
        self, issue_id: int, child_class: str, timestamp: float
    ) -> None: ...

    def get_give_up_timestamps(
        self, issue_id: int, child_class: str
    ) -> list[float]: ...

    def set_give_up_timestamps(
        self, issue_id: int, child_class: str, timestamps: list[float]
    ) -> None: ...

    def record_give_up_action(
        self, issue_id: int, child_class: str, action: str, timestamp: float
    ) -> None: ...

    def reset_give_up(self, issue_id: int, child_class: str) -> None: ...


class GiveUpTracker:
    """Records give-up events and answers the ``N``-in-``T`` question.

    Pure policy over a :class:`GiveUpStore` + an injectable clock (so tests
    can advance time deterministically). Events older than the window are
    pruned on every record so the persisted list stays bounded.
    """

    __slots__ = ("_clock", "_state")

    def __init__(
        self,
        state: GiveUpStore,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._state = state
        self._clock = clock

    def record_and_count(self, issue_id: int, window: GiveUpWindow) -> int:
        """Record a give-up event *now* and return the count within the window.

        Prunes events older than ``window.window_seconds`` before counting, so
        the return value is exactly the number of retries/abnormal exits inside
        the current ``T`` — the value compared against ``N``.
        """
        now = self._clock()
        cls = window.child_class.value
        self._state.record_give_up_event(issue_id, cls, now)
        cutoff = now - window.window_seconds
        kept = [
            t for t in self._state.get_give_up_timestamps(issue_id, cls) if t >= cutoff
        ]
        self._state.set_give_up_timestamps(issue_id, cls, kept)
        return len(kept)

    def count_in_window(self, issue_id: int, window: GiveUpWindow) -> int:
        """Return the current in-window event count WITHOUT recording a new one."""
        now = self._clock()
        cutoff = now - window.window_seconds
        cls = window.child_class.value
        return sum(
            1 for t in self._state.get_give_up_timestamps(issue_id, cls) if t >= cutoff
        )

    def record_action(
        self, issue_id: int, window: GiveUpWindow, action: SelfSolveOutcome
    ) -> None:
        """Persist which self-solve action fired for this issue/class (for /api)."""
        self._state.record_give_up_action(
            issue_id, window.child_class.value, action.value, self._clock()
        )

    def reset(self, issue_id: int, window: GiveUpWindow) -> None:
        """Clear the window for *issue_id*/class — called when the issue converges."""
        self._state.reset_give_up(issue_id, window.child_class.value)
