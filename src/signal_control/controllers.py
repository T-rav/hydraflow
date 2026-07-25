"""Controllers — drive an actuator toward a setpoint with bounded, stable moves.

Pure policy objects: they compute the next actuator value from a scalar/boolean
signal. Wiring to a real actuator (max_workers, a rebase cycle) happens in later
stages. ``CircuitBreaker`` is re-exported from the existing src/circuit_breaker.py
so callers have a single import point.
"""

from __future__ import annotations

import enum
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from circuit_breaker import CircuitBreaker  # re-export; see Task 10

__all__ = [
    "AimdController",
    "CircuitBreaker",
    "PidController",
    "RetryController",
    "RetryOutcome",
    "RetryResult",
    "RetryStatus",
]


@dataclass
class AimdController:
    """Additive-increase / multiplicative-decrease controller (TCP-style).

    For a saturating actuator (e.g. concurrency): shed fast on breach, probe up
    slowly on sustained headroom. Bounded to ``[lo, hi]``; a dead-band (neither
    breached nor headroom) holds steady and resets the ramp streak.
    """

    lo: int
    hi: int
    start: int
    decrease_factor: float = 0.5
    increase_step: int = 1
    hold_ticks: int = 3
    _cap: int = field(init=False)
    _headroom_streak: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        if self.lo < 1 or self.hi < self.lo:
            raise ValueError(f"require 1 <= lo <= hi, got lo={self.lo} hi={self.hi}")
        if not self.lo <= self.start <= self.hi:
            raise ValueError(f"start {self.start} must be in [{self.lo}, {self.hi}]")
        if not 0.0 < self.decrease_factor < 1.0:
            raise ValueError(
                f"decrease_factor must be in (0, 1), got {self.decrease_factor}"
            )
        if self.increase_step < 0:
            raise ValueError(f"increase_step must be >= 0, got {self.increase_step}")
        if self.hold_ticks < 1:
            raise ValueError(f"hold_ticks must be >= 1, got {self.hold_ticks}")
        self._cap = self.start

    def update(self, *, breached: bool, headroom: bool) -> int:
        if breached:
            self._cap = max(self.lo, round(self._cap * self.decrease_factor))
            self._headroom_streak = 0
        elif headroom:
            self._headroom_streak += 1
            if self._headroom_streak >= self.hold_ticks:
                self._cap = min(self.hi, self._cap + self.increase_step)
                self._headroom_streak = 0
        else:
            self._headroom_streak = 0
        return self._cap

    @property
    def cap(self) -> int:
        return self._cap


@dataclass
class PidController:
    """PID controller with clamping anti-windup and output saturation.

    General controller for a continuous actuator (e.g. loop cadence). The
    integral term is clamped so it can never demand an output beyond
    ``[out_lo, out_hi]`` — preventing the "wind-up" lag where a saturated
    integrator keeps commanding past the limit long after the error flips.
    """

    kp: float
    ki: float
    kd: float
    out_lo: float
    out_hi: float
    _integral: float = field(default=0.0, init=False)
    _prev_error: float | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        if self.out_hi < self.out_lo:
            raise ValueError(
                f"out_hi ({self.out_hi}) must be >= out_lo ({self.out_lo})"
            )

    def update(self, error: float) -> float:
        self._integral += error
        # Anti-windup: clamp the integral so ki*integral stays within the span.
        if self.ki != 0.0:
            i_lo = self.out_lo / self.ki
            i_hi = self.out_hi / self.ki
            self._integral = max(min(self._integral, max(i_lo, i_hi)), min(i_lo, i_hi))
        derivative = 0.0 if self._prev_error is None else (error - self._prev_error)
        self._prev_error = error
        raw = self.kp * error + self.ki * self._integral + self.kd * derivative
        return max(self.out_lo, min(self.out_hi, raw))


class RetryStatus(enum.Enum):
    SUCCESS = "success"
    RETRYABLE = "retryable"
    TERMINAL = "terminal"


@dataclass(frozen=True)
class RetryOutcome:
    status: RetryStatus
    detail: str = ""


@dataclass(frozen=True)
class RetryResult:
    succeeded: bool
    attempts: int
    terminal: bool
    history: list[RetryOutcome]


@dataclass
class RetryController:
    """Bounded fix-retry policy — try up to ``max_attempts`` times.

    Each attempt returns a :class:`RetryOutcome`. SUCCESS stops immediately;
    TERMINAL short-circuits (don't burn remaining attempts on an unfixable
    failure); RETRYABLE loops until the budget is exhausted. The actual
    fix work (rebase, re-poll CI) is injected as the ``attempt`` coroutine.
    """

    max_attempts: int

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError(f"max_attempts must be >= 1, got {self.max_attempts}")

    async def run(
        self, attempt: Callable[[int], Awaitable[RetryOutcome]]
    ) -> RetryResult:
        history: list[RetryOutcome] = []
        for n in range(1, self.max_attempts + 1):
            outcome = await attempt(n)
            history.append(outcome)
            if outcome.status is RetryStatus.SUCCESS:
                return RetryResult(True, n, False, history)
            if outcome.status is RetryStatus.TERMINAL:
                return RetryResult(False, n, True, history)
        return RetryResult(False, self.max_attempts, False, history)
