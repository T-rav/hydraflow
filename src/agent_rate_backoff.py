"""Rate-aware agent-subprocess backoff (#10289).

Under concurrent agent load individual ``claude`` subprocesses fail *mid-run*
(``Process exited with code 1``, no terminal ``result`` frame, transcript ends
mid-exploration) while a *lone* ``claude -p`` with the identical command / auth /
model succeeds — the account's 5-hour rate window is depleted. This module fixes
the two compounding defects from the incident:

1. **No backpressure.** The factory kept spawning agents at full rate into a
   depleted window, so runs got truncated and produced nothing — burning the
   window on failures. :class:`AgentRateBackoff` watches the outcome stream and,
   once the repeated-mid-run-failure signature repeats within a short window,
   throttles spawning with exponential backoff, recovering as successes climb.

2. **Misdiagnosis as credit exhaustion.** A truncated run (rc != 0, *no* terminal
   ``result`` frame) is the depleted-rate-window signature, NOT credit
   exhaustion — a lone probe on the same auth succeeds, and the
   ``overageDisabledReason:"out_of_credits"`` overage flag the failures carry is
   *also* present on successful calls. :func:`classify_agent_outcome` keeps the
   two distinct so only a genuine billing signal
   (:func:`subprocess_util.is_credit_exhaustion`) trips credit-pause.

Design constraints (so it can never wedge the pipeline):

- **Conservatively disabled by default.** A fresh :class:`AgentRateBackoff` is
  ``enabled=False`` and fully inert — it records nothing and returns a zero
  delay regardless of how many failures arrive. Throttling is opt-in.
- **Bounded, self-recovering.** Even when enabled the throttle only *lengthens*
  the interval before a spawn (capped at ``max_delay_seconds``); it never halts
  the factory, and a short streak of successes fully resets it.

Threading: all record/query calls run on the single asyncio event-loop thread
(the central ``stream_claude_process`` path), so — like the gh circuit breaker
in :mod:`subprocess_util` — the mutations are atomic and need no lock.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Callable
from enum import StrEnum

from subprocess_util import is_credit_exhaustion

logger = logging.getLogger("hydraflow.agent_rate_backoff")


class AgentOutcomeKind(StrEnum):
    """Classification of a completed agent subprocess run."""

    #: rc == 0 and a terminal ``result`` frame was emitted.
    SUCCESS = "success"
    #: rc != 0 with no terminal ``result`` frame — a truncated mid-run failure.
    #: Under concurrent load this is the depleted-rate-window signature; it is
    #: NOT credit exhaustion (a lone probe on the same auth succeeds).
    MID_RUN_RATE_LIMIT = "mid_run_rate_limit"
    #: A genuine billing signal was present in the output.
    CREDIT_EXHAUSTION = "credit_exhaustion"
    #: Anything else — an intentional early-kill, a clean non-zero business exit,
    #: an rc==0 run with no result frame. Never feeds the rate backoff.
    OTHER = "other"


def classify_agent_outcome(
    *,
    returncode: int | None,
    has_result_frame: bool,
    output_text: str = "",
    early_killed: bool = False,
) -> AgentOutcomeKind:
    """Classify one completed agent run.

    The load-bearing distinction (defect 2): a run that exits non-zero with *no*
    terminal ``result`` frame is :attr:`AgentOutcomeKind.MID_RUN_RATE_LIMIT`, not
    :attr:`AgentOutcomeKind.CREDIT_EXHAUSTION` — unless the output carries a real
    billing signal that :func:`subprocess_util.is_credit_exhaustion` recognises.
    The ``overageDisabledReason:"out_of_credits"`` overage flag is deliberately
    *not* such a signal (it is present even on successful calls), so it never
    trips credit-pause on its own.

    Parameters
    ----------
    returncode:
        The subprocess exit code (``None`` if it never completed).
    has_result_frame:
        Whether the stream produced a terminal ``result`` frame
        (``result_text`` non-empty in :func:`runner_utils._post_stream_result`).
    output_text:
        Combined stderr + transcript text, scanned for the billing signal.
    early_killed:
        Whether the caller intentionally killed the process (an ``on_output``
        early-kill). Such runs are not a failure signal.
    """
    if early_killed:
        return AgentOutcomeKind.OTHER
    if returncode == 0 and has_result_frame:
        return AgentOutcomeKind.SUCCESS
    # A genuine billing signal takes precedence over the rate-limit signature.
    if output_text and is_credit_exhaustion(output_text):
        return AgentOutcomeKind.CREDIT_EXHAUSTION
    # rc != 0 (and not None) with no terminal result frame = truncated mid-run.
    if returncode not in (0, None) and not has_result_frame:
        return AgentOutcomeKind.MID_RUN_RATE_LIMIT
    return AgentOutcomeKind.OTHER


class AgentRateBackoff:
    """Sliding-window backoff engine for agent-subprocess spawning.

    Disabled by default. When enabled, once ``failure_threshold`` mid-run
    failures land within ``window_seconds`` the engine engages and each further
    failure escalates an exponential delay (``base_delay_seconds`` doubling,
    capped at ``max_delay_seconds``). ``recovery_successes`` consecutive
    successes fully reset it.
    """

    def __init__(
        self,
        *,
        enabled: bool = False,
        failure_threshold: int = 3,
        window_seconds: float = 300.0,
        base_delay_seconds: float = 30.0,
        max_delay_seconds: float = 600.0,
        recovery_successes: int = 2,
        time_source: Callable[[], float] | None = None,
    ) -> None:
        self.enabled = enabled
        self.failure_threshold = failure_threshold
        self.window_seconds = window_seconds
        self.base_delay_seconds = base_delay_seconds
        self.max_delay_seconds = max_delay_seconds
        self.recovery_successes = recovery_successes
        self._time_source: Callable[[], float] = time_source or time.monotonic
        self._failures: deque[float] = deque()
        self._level = 0
        self._consecutive_successes = 0

    # -- configuration -----------------------------------------------------

    def configure(
        self,
        *,
        enabled: bool | None = None,
        failure_threshold: int | None = None,
        window_seconds: float | None = None,
        base_delay_seconds: float | None = None,
        max_delay_seconds: float | None = None,
        recovery_successes: int | None = None,
        time_source: Callable[[], float] | None = None,
    ) -> None:
        """Update tunables in place (used by wiring / tests; never reassigns the
        singleton, so no module-global mutation is required)."""
        if enabled is not None:
            self.enabled = enabled
        if failure_threshold is not None:
            self.failure_threshold = failure_threshold
        if window_seconds is not None:
            self.window_seconds = window_seconds
        if base_delay_seconds is not None:
            self.base_delay_seconds = base_delay_seconds
        if max_delay_seconds is not None:
            self.max_delay_seconds = max_delay_seconds
        if recovery_successes is not None:
            self.recovery_successes = recovery_successes
        if time_source is not None:
            self._time_source = time_source

    def reset(self) -> None:
        """Clear all runtime state (failure window, backoff level, streak)."""
        self._failures.clear()
        self._level = 0
        self._consecutive_successes = 0

    # -- outcome recording -------------------------------------------------

    def record_outcome(self, kind: AgentOutcomeKind) -> None:
        """Route a classified outcome to the right counter.

        Only :attr:`AgentOutcomeKind.MID_RUN_RATE_LIMIT` feeds the backoff and
        only :attr:`AgentOutcomeKind.SUCCESS` drives recovery. Credit exhaustion
        is a separate billing signal (handled by ``CreditExhaustedError``) and
        must NOT count as either a rate-limit failure or a recovery success.
        """
        if kind == AgentOutcomeKind.MID_RUN_RATE_LIMIT:
            self.record_mid_run_failure()
        elif kind == AgentOutcomeKind.SUCCESS:
            self.record_success()

    def record_mid_run_failure(self) -> None:
        """Record one truncated mid-run failure; may engage/escalate backoff."""
        if not self.enabled:
            return
        self._consecutive_successes = 0
        now = self._time_source()
        self._failures.append(now)
        self._prune(now)
        if len(self._failures) >= self.failure_threshold:
            self._level = min(self._level + 1, self._max_level())

    def record_success(self) -> None:
        """Record one clean run; a full recovery streak resets the backoff."""
        if not self.enabled:
            return
        self._consecutive_successes += 1
        if self._consecutive_successes >= self.recovery_successes:
            self.reset()

    # -- queries -----------------------------------------------------------

    def current_delay_seconds(self) -> float:
        """The delay to apply before the next spawn (0.0 when not engaged)."""
        if not self.enabled or self._level <= 0:
            return 0.0
        delay = self.base_delay_seconds * (2 ** (self._level - 1))
        return float(min(delay, self.max_delay_seconds))

    @property
    def is_backing_off(self) -> bool:
        """Whether a non-zero throttle delay is currently in effect."""
        return self.current_delay_seconds() > 0.0

    async def wait_if_throttled(self) -> None:
        """Sleep for the current backoff delay before spawning, if engaged.

        A no-op when disabled or not engaged, so it is safe to ``await`` on
        every spawn. It only ever *delays* — it never blocks indefinitely.
        """
        delay = self.current_delay_seconds()
        if delay <= 0.0:
            return
        logger.warning(
            "Rate-aware agent backoff engaged — delaying spawn %.0fs "
            "(mid-run failures within %.0fs window)",
            delay,
            self.window_seconds,
        )
        await asyncio.sleep(delay)

    # -- internals ---------------------------------------------------------

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._failures and self._failures[0] < cutoff:
            self._failures.popleft()

    def _max_level(self) -> int:
        """Smallest backoff level whose delay reaches the cap (bounds ``_level``)."""
        if self.base_delay_seconds <= 0:
            return 1
        level = 1
        while self.base_delay_seconds * (2 ** (level - 1)) < self.max_delay_seconds:
            level += 1
        return level


#: Process-wide singleton consulted by the central ``stream_claude_process``
#: spawn path. Mutated in place (never reassigned) so no module-global write —
#: and hence no ``PLW0603`` suppression — is needed. Disabled by default.
_BACKOFF = AgentRateBackoff()


def get_agent_rate_backoff() -> AgentRateBackoff:
    """Return the process-wide backoff singleton."""
    return _BACKOFF


def configure_agent_rate_backoff(
    *,
    enabled: bool | None = None,
    failure_threshold: int | None = None,
    window_seconds: float | None = None,
    base_delay_seconds: float | None = None,
    max_delay_seconds: float | None = None,
    recovery_successes: int | None = None,
) -> None:
    """Configure the singleton at startup (thin wrapper over ``.configure``)."""
    _BACKOFF.configure(
        enabled=enabled,
        failure_threshold=failure_threshold,
        window_seconds=window_seconds,
        base_delay_seconds=base_delay_seconds,
        max_delay_seconds=max_delay_seconds,
        recovery_successes=recovery_successes,
    )
