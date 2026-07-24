"""HistoricSignalStore — bounded, windowed memory the control layer acts on.

One ring buffer per named signal, bounded by count AND age. Reads (ewma, mean,
mad, count_where, slope) are computed on demand. Sampled at control-tick
resolution and deliberately small — NOT a metrics/observability system.
Time is injected via ``clock`` for deterministic tests.
"""

from __future__ import annotations

import statistics
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from signal_control.conditioners import Ewma


@dataclass(frozen=True)
class Sample:
    ts: float
    value: float
    tags: dict[str, str]


class HistoricSignalStore:
    def __init__(
        self,
        max_len: int = 512,
        max_age_s: float = 86_400.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_len < 1:
            raise ValueError(f"max_len must be >= 1, got {max_len}")
        self._max_len = max_len
        self._max_age_s = max_age_s
        self._clock = clock
        self._signals: dict[str, deque[Sample]] = {}

    def record(
        self, signal: str, value: float, tags: dict[str, str] | None = None
    ) -> None:
        buf = self._signals.get(signal)
        if buf is None:
            buf = self._signals[signal] = deque(maxlen=self._max_len)
        buf.append(Sample(self._clock(), float(value), dict(tags or {})))
        self._prune(buf)

    def _prune(self, buf: deque[Sample]) -> None:
        cutoff = self._clock() - self._max_age_s
        while buf and buf[0].ts < cutoff:
            buf.popleft()

    def _values(self, signal: str, age_s: float | None) -> list[float]:
        buf = self._signals.get(signal)
        if not buf:
            return []
        if age_s is None:
            return [s.value for s in buf]
        cutoff = self._clock() - age_s
        return [s.value for s in buf if s.ts >= cutoff]

    def window(self, signal: str, age_s: float | None = None) -> list[float]:
        return self._values(signal, age_s)

    def mean(self, signal: str, age_s: float | None = None) -> float | None:
        vals = self._values(signal, age_s)
        return statistics.fmean(vals) if vals else None

    def mad(self, signal: str, age_s: float | None = None) -> float | None:
        vals = self._values(signal, age_s)
        if not vals:
            return None
        med = statistics.median(vals)
        return statistics.median([abs(v - med) for v in vals])

    def count_where(
        self, signal: str, pred: Callable[[float], bool], age_s: float | None = None
    ) -> int:
        return sum(1 for v in self._values(signal, age_s) if pred(v))

    def ewma(self, signal: str, alpha: float) -> float | None:
        vals = self._values(signal, None)
        if not vals:
            return None
        e = Ewma(alpha=alpha)
        for v in vals:
            e.update(v)
        return e.value

    def slope(self, signal: str) -> float | None:
        vals = self._values(signal, None)
        if len(vals) < 2:
            return None
        xs = list(range(len(vals)))
        return statistics.linear_regression(xs, vals).slope
