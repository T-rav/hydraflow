"""Signal conditioners — turn a raw noisy metric into a belief you can act on.

Each unit is a small dataclass with an ``update(...)`` method returning its
current state. Pure: no I/O, no factory imports, no inline clock.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Ewma:
    """Exponentially-weighted moving average low-pass filter.

    ``ewma <- alpha*x + (1-alpha)*ewma``; the first sample seeds the estimate.
    """

    alpha: float
    _value: float | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        if not 0.0 < self.alpha <= 1.0:
            raise ValueError(f"alpha must be in (0, 1], got {self.alpha}")

    def update(self, x: float) -> float:
        self._value = (
            x
            if self._value is None
            else self.alpha * x + (1.0 - self.alpha) * self._value
        )
        return self._value

    @property
    def value(self) -> float | None:
        return self._value


@dataclass
class SchmittHysteresis:
    """Two-threshold trigger: trip at ``trip_high``, clear only at ``clear_low``.

    Kills flapping — a signal must decisively recover before the alarm resets.
    """

    trip_high: float
    clear_low: float
    _tripped: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if not self.clear_low < self.trip_high:
            raise ValueError(
                f"clear_low ({self.clear_low}) must be < trip_high ({self.trip_high})"
            )

    def update(self, x: float) -> bool:
        if not self._tripped and x >= self.trip_high:
            self._tripped = True
        elif self._tripped and x <= self.clear_low:
            self._tripped = False
        return self._tripped

    @property
    def tripped(self) -> bool:
        return self._tripped


@dataclass
class Persistence:
    """A breach must hold for ``k`` consecutive updates before it counts."""

    k: int
    _streak: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        if self.k < 1:
            raise ValueError(f"k must be >= 1, got {self.k}")

    def update(self, breached: bool) -> bool:
        self._streak = self._streak + 1 if breached else 0
        return self._streak >= self.k

    @property
    def streak(self) -> int:
        return self._streak


@dataclass
class Cusum:
    """Two-sided CUSUM change-point detector.

    Fires when the process sustainably shifts from ``mean`` — distinguishes a
    real regime change from noise, which a fixed threshold cannot. ``slack``
    (the reference value ``k``) is the per-step deadband absorbing normal noise.
    """

    threshold: float
    slack: float = 0.0
    _pos: float = field(default=0.0, init=False)
    _neg: float = field(default=0.0, init=False)

    def __post_init__(self) -> None:
        if self.threshold <= 0.0:
            raise ValueError(f"threshold must be > 0, got {self.threshold}")

    def update(self, x: float, mean: float) -> bool:
        dev = x - mean
        self._pos = max(0.0, self._pos + dev - self.slack)
        self._neg = min(0.0, self._neg + dev + self.slack)
        fired = self._pos > self.threshold or self._neg < -self.threshold
        if fired:
            self._pos = 0.0
            self._neg = 0.0
        return fired

    @property
    def pos(self) -> float:
        return self._pos

    @property
    def neg(self) -> float:
        return self._neg
