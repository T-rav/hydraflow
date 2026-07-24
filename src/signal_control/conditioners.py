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
