"""HistoricSignalStore — bounded, windowed memory the control layer acts on.

One ring buffer per named signal, bounded by count AND age. Reads (ewma, mean,
mad, count_where, slope) are computed on demand. Sampled at control-tick
resolution and deliberately small — NOT a metrics/observability system.
Time is injected via ``clock`` for deterministic tests.
"""

from __future__ import annotations

import json
import statistics
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

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
        path: Path | None = None,
    ) -> None:
        if max_len < 1:
            raise ValueError(f"max_len must be >= 1, got {max_len}")
        self._max_len = max_len
        self._max_age_s = max_age_s
        self._clock = clock
        self._signals: dict[str, deque[Sample]] = {}
        self._path = path
        if path is not None:
            self._reload()

    def record(
        self, signal: str, value: float, tags: dict[str, str] | None = None
    ) -> None:
        buf = self._signals.get(signal)
        if buf is None:
            buf = self._signals[signal] = deque(maxlen=self._max_len)
        buf.append(Sample(self._clock(), float(value), dict(tags or {})))
        self._prune(buf)
        self._persist(signal, buf[-1])

    def _prune(self, buf: deque[Sample]) -> None:
        cutoff = self._clock() - self._max_age_s
        while buf and buf[0].ts < cutoff:
            buf.popleft()

    def _persist(self, signal: str, sample: Sample) -> None:
        if self._path is None:
            return
        line = json.dumps(
            {
                "signal": signal,
                "ts": sample.ts,
                "value": sample.value,
                "tags": sample.tags,
            }
        )
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def _reload(self) -> None:
        assert self._path is not None
        if not self._path.exists():
            return
        cutoff = self._clock() - self._max_age_s
        for line in self._path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                rec = json.loads(stripped)
                ts, value = float(rec["ts"]), float(rec["value"])
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue  # skip a corrupt line, never fail the boot
            if ts < cutoff:
                continue
            buf = self._signals.setdefault(rec["signal"], deque(maxlen=self._max_len))
            buf.append(Sample(ts, value, dict(rec.get("tags") or {})))

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
