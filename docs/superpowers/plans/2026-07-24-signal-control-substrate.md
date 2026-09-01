# signal_control Substrate (Stage 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the pure, reusable `src/signal_control` toolkit — conditioners (smoothing / hysteresis / change-point / adaptive-threshold / corroboration), controllers (AIMD / PID / retry / circuit-breaker), and a historic signal store — with zero factory integration and zero behavior change.

**Architecture:** A leaf package of small, pure, independently-testable units. Conditioners turn noisy signals into trustworthy state; controllers drive an actuator toward a setpoint; the store is the shared windowed memory. Nothing here imports factory modules, spawns processes, or touches the network. Anything time-dependent takes an injected `clock: Callable[[], float]` (default `time.monotonic`) so property tests are deterministic. This is Stage 1 of the 5-stage rollout in `docs/superpowers/specs/2026-07-23-bg-worker-control-theory-design.md`; Stages 2–5 (RC RetryController wiring, concurrency governor, detector migration, observability) each get their own plan and consume this substrate.

**Tech Stack:** Python 3.11, stdlib only for the runtime code (`dataclasses`, `collections.deque`, `statistics`, `json`, `pathlib`, `time`). Tests use `pytest` + `hypothesis` (both already in `[project.optional-dependencies] test`).

## Global Constraints

- **Never commit to `main` or `staging`.** Work in a git worktree branch; PR targets `staging` (`gh pr create --base staging`).
- **Never `git commit --no-verify`.** The pre-commit hook runs lint + arch-check; fix issues, don't bypass.
- **Pure modules only.** `src/signal_control/{store,conditioners,controllers}.py` must not import any factory module (no `config`, `orchestrator`, `pr_manager`, `state`, etc.) except `controllers.py` re-exporting the existing `src/circuit_breaker.py`. No process spawning, no network, no filesystem writes except `HistoricSignalStore`'s explicit opt-in JSONL path.
- **Time is injected.** Every unit that needs "now" accepts `clock: Callable[[], float] = time.monotonic`. Runtime code must not call `time.monotonic()`/`time.time()` inline (keeps property tests deterministic and dodges the repo's no-inline-clock test conventions).
- **Test command:** `PYTHONPATH=src uv run pytest tests/signal_control/ -q`. Lint: `uv run ruff check src/signal_control tests/signal_control`. Types: `PYTHONPATH=src uv run pyright src/signal_control`.
- **Commit trailer** on every commit: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- **Naming:** package `signal_control`; classes `Ewma`, `SchmittHysteresis`, `Persistence`, `Cusum`, `AdaptiveThreshold`, `Corroborator`, `AimdController`, `PidController`, `RetryController`, `HistoricSignalStore`; `RetryOutcome`/`RetryStatus` for the retry policy types. Do not paraphrase these — later stages import them by name.

---

### Task 1: Package scaffold + `Ewma` conditioner

**Files:**
- Create: `src/signal_control/__init__.py`
- Create: `src/signal_control/conditioners.py`
- Create: `tests/signal_control/__init__.py` (empty)
- Test: `tests/signal_control/test_conditioners.py`

**Interfaces:**
- Produces: `Ewma(alpha: float)` with `.update(x: float) -> float` and `.value: float | None`. First `update` seeds the estimate to `x`.

- [ ] **Step 1: Write the failing test**

```python
# tests/signal_control/test_conditioners.py
from __future__ import annotations

import pytest
from hypothesis import given, strategies as st

from signal_control.conditioners import Ewma


def test_ewma_seeds_to_first_value():
    e = Ewma(alpha=0.3)
    assert e.value is None
    assert e.update(10.0) == 10.0
    assert e.value == 10.0


def test_ewma_alpha_one_tracks_latest():
    e = Ewma(alpha=1.0)
    e.update(1.0)
    assert e.update(7.0) == 7.0


@given(
    alpha=st.floats(min_value=0.01, max_value=1.0),
    xs=st.lists(st.floats(min_value=-1e6, max_value=1e6), min_size=1, max_size=200),
)
def test_ewma_stays_within_input_bounds(alpha, xs):
    e = Ewma(alpha=alpha)
    for x in xs:
        e.update(x)
    assert min(xs) - 1e-6 <= e.value <= max(xs) + 1e-6


def test_ewma_rejects_bad_alpha():
    with pytest.raises(ValueError):
        Ewma(alpha=0.0)
    with pytest.raises(ValueError):
        Ewma(alpha=1.5)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src uv run pytest tests/signal_control/test_conditioners.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'signal_control'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/signal_control/__init__.py
"""Pure control-theory substrate for background workers (Stage 1).

Conditioners turn noisy signals into trustworthy state; controllers drive an
actuator toward a setpoint; HistoricSignalStore is the shared windowed memory.
No module here imports factory code or performs I/O (except the store's opt-in
JSONL path). See docs/superpowers/specs/2026-07-23-bg-worker-control-theory-design.md.
"""
```

```python
# src/signal_control/conditioners.py
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
        self._value = x if self._value is None else self.alpha * x + (1.0 - self.alpha) * self._value
        return self._value

    @property
    def value(self) -> float | None:
        return self._value
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src uv run pytest tests/signal_control/test_conditioners.py -q`
Expected: PASS (4 tests / hypothesis examples)

- [ ] **Step 5: Commit**

```bash
git add src/signal_control/__init__.py src/signal_control/conditioners.py tests/signal_control/__init__.py tests/signal_control/test_conditioners.py
git commit -m "feat(signal-control): package scaffold + Ewma conditioner

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `SchmittHysteresis` conditioner

**Files:**
- Modify: `src/signal_control/conditioners.py`
- Test: `tests/signal_control/test_conditioners.py`

**Interfaces:**
- Produces: `SchmittHysteresis(trip_high: float, clear_low: float)` with `.update(x: float) -> bool` (returns current tripped state) and `.tripped: bool`. Requires `clear_low < trip_high`.

- [ ] **Step 1: Write the failing test** (append to `tests/signal_control/test_conditioners.py`)

```python
from signal_control.conditioners import SchmittHysteresis


def test_hysteresis_trips_high_clears_low():
    h = SchmittHysteresis(trip_high=10.0, clear_low=4.0)
    assert h.update(9.9) is False          # below trip
    assert h.update(10.0) is True          # trips
    assert h.update(5.0) is True           # in the band -> stays tripped
    assert h.update(4.0) is False          # clears at/below clear_low


def test_hysteresis_rejects_inverted_band():
    with pytest.raises(ValueError):
        SchmittHysteresis(trip_high=4.0, clear_low=10.0)


@given(xs=st.lists(st.floats(min_value=4.0001, max_value=9.9999), min_size=1, max_size=100))
def test_hysteresis_never_flaps_inside_the_band(xs):
    # Values strictly inside (clear_low, trip_high) must never change state.
    h = SchmittHysteresis(trip_high=10.0, clear_low=4.0)
    start = h.tripped
    for x in xs:
        assert h.update(x) is start
```

- [ ] **Step 2: Run to verify fail**

Run: `PYTHONPATH=src uv run pytest tests/signal_control/test_conditioners.py -k hysteresis -q`
Expected: FAIL — `ImportError: cannot import name 'SchmittHysteresis'`

- [ ] **Step 3: Implement** (append to `src/signal_control/conditioners.py`)

```python
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
            raise ValueError(f"clear_low ({self.clear_low}) must be < trip_high ({self.trip_high})")

    def update(self, x: float) -> bool:
        if not self._tripped and x >= self.trip_high:
            self._tripped = True
        elif self._tripped and x <= self.clear_low:
            self._tripped = False
        return self._tripped

    @property
    def tripped(self) -> bool:
        return self._tripped
```

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONPATH=src uv run pytest tests/signal_control/test_conditioners.py -k hysteresis -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/signal_control/conditioners.py tests/signal_control/test_conditioners.py
git commit -m "feat(signal-control): SchmittHysteresis conditioner

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: `Persistence` conditioner

**Files:**
- Modify: `src/signal_control/conditioners.py`
- Test: `tests/signal_control/test_conditioners.py`

**Interfaces:**
- Produces: `Persistence(k: int)` with `.update(breached: bool) -> bool` — returns `True` only after `k` consecutive `True` inputs; any `False` resets the streak. `.streak: int`.

- [ ] **Step 1: Write the failing test** (append)

```python
from signal_control.conditioners import Persistence


def test_persistence_requires_k_consecutive():
    p = Persistence(k=3)
    assert p.update(True) is False
    assert p.update(True) is False
    assert p.update(True) is True
    assert p.update(False) is False   # reset
    assert p.update(True) is False


def test_persistence_rejects_bad_k():
    with pytest.raises(ValueError):
        Persistence(k=0)


@given(n=st.integers(min_value=1, max_value=50), k=st.integers(min_value=1, max_value=10))
def test_persistence_fires_iff_streak_reaches_k(n, k):
    p = Persistence(k=k)
    fired = [p.update(True) for _ in range(n)]
    assert all(fired[i] == (i + 1 >= k) for i in range(n))
```

- [ ] **Step 2: Run to verify fail** — `ImportError: cannot import name 'Persistence'`

- [ ] **Step 3: Implement** (append)

```python
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
```

- [ ] **Step 4: Run to verify pass** — PASS

- [ ] **Step 5: Commit**

```bash
git add src/signal_control/conditioners.py tests/signal_control/test_conditioners.py
git commit -m "feat(signal-control): Persistence conditioner

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: `Cusum` change-point detector

**Files:**
- Modify: `src/signal_control/conditioners.py`
- Test: `tests/signal_control/test_conditioners.py`

**Interfaces:**
- Produces: `Cusum(threshold: float, slack: float = 0.0)` with `.update(x: float, mean: float) -> bool` — accumulates two-sided deviation from `mean`, fires (and resets both accumulators) when either side exceeds `threshold`. `.pos: float`, `.neg: float`.

- [ ] **Step 1: Write the failing test** (append)

```python
from signal_control.conditioners import Cusum


def test_cusum_ignores_zero_mean_noise():
    c = Cusum(threshold=5.0, slack=0.5)
    # Alternating +/-1 around mean 0 never accumulates past the slack.
    fired = [c.update(1.0 if i % 2 == 0 else -1.0, mean=0.0) for i in range(200)]
    assert not any(fired)


def test_cusum_fires_on_sustained_upward_shift():
    c = Cusum(threshold=5.0, slack=0.5)
    fired = [c.update(2.0, mean=0.0) for _ in range(10)]  # sustained +2 vs mean 0
    assert any(fired)


def test_cusum_resets_after_firing():
    c = Cusum(threshold=3.0, slack=0.0)
    for _ in range(10):
        c.update(2.0, mean=0.0)
    # after a fire, accumulators are cleared
    assert c.pos == 0.0 and c.neg == 0.0
```

- [ ] **Step 2: Run to verify fail** — `ImportError: cannot import name 'Cusum'`

- [ ] **Step 3: Implement** (append)

```python
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
```

- [ ] **Step 4: Run to verify pass** — PASS

- [ ] **Step 5: Commit**

```bash
git add src/signal_control/conditioners.py tests/signal_control/test_conditioners.py
git commit -m "feat(signal-control): Cusum change-point detector

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: `AdaptiveThreshold` (robust historic baseline)

**Files:**
- Modify: `src/signal_control/conditioners.py`
- Test: `tests/signal_control/test_conditioners.py`

**Interfaces:**
- Produces: `AdaptiveThreshold(z: float, min_samples: int = 8)` with `.is_anomalous(x: float, baseline: Sequence[float]) -> bool` using a robust (median + MAD) z-score. Returns `False` when `len(baseline) < min_samples` (insufficient history — fail safe) or when MAD is 0 and `x == median`.

- [ ] **Step 1: Write the failing test** (append)

```python
from signal_control.conditioners import AdaptiveThreshold


def test_adaptive_threshold_insufficient_history_is_not_anomalous():
    at = AdaptiveThreshold(z=3.0, min_samples=8)
    assert at.is_anomalous(1000.0, baseline=[1.0, 2.0, 3.0]) is False


def test_adaptive_threshold_flags_robust_outlier():
    at = AdaptiveThreshold(z=3.0, min_samples=8)
    baseline = [10.0, 11.0, 9.0, 10.5, 9.5, 10.2, 9.8, 10.1]
    assert at.is_anomalous(50.0, baseline) is True
    assert at.is_anomalous(10.3, baseline) is False


def test_adaptive_threshold_ignores_single_outlier_in_baseline():
    # MAD is robust: one wild value in the baseline must not blow up the scale.
    at = AdaptiveThreshold(z=3.0, min_samples=8)
    baseline = [10.0, 11.0, 9.0, 10.5, 9.5, 10.2, 9.8, 999.0]
    assert at.is_anomalous(20.0, baseline) is True
```

- [ ] **Step 2: Run to verify fail** — `ImportError: cannot import name 'AdaptiveThreshold'`

- [ ] **Step 3: Implement** (append; add `import statistics` and `from collections.abc import Sequence` to the top of the file)

```python
@dataclass
class AdaptiveThreshold:
    """Anomaly = far from the baseline's robust center, in MAD units.

    Uses median + MAD (median absolute deviation) so a handful of outliers in
    the baseline can't inflate the scale. Below ``min_samples`` it returns
    ``False`` (fail safe: thin history never reads as anomalous).
    """

    z: float
    min_samples: int = 8
    _MAD_TO_SIGMA: float = 1.4826  # MAD * this ~= stddev for normal data

    def is_anomalous(self, x: float, baseline: Sequence[float]) -> bool:
        if len(baseline) < self.min_samples:
            return False
        med = statistics.median(baseline)
        mad = statistics.median([abs(s - med) for s in baseline])
        if mad == 0.0:
            return x != med
        robust_sigma = mad * self._MAD_TO_SIGMA
        return abs(x - med) / robust_sigma >= self.z
```

- [ ] **Step 4: Run to verify pass** — PASS

- [ ] **Step 5: Commit**

```bash
git add src/signal_control/conditioners.py tests/signal_control/test_conditioners.py
git commit -m "feat(signal-control): AdaptiveThreshold robust-baseline conditioner

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: `Corroborator` conditioner

**Files:**
- Modify: `src/signal_control/conditioners.py`
- Test: `tests/signal_control/test_conditioners.py`

**Interfaces:**
- Produces: `Corroborator(probe: Callable[[], bool], required: int)` with `.confirm() -> bool` — calls `probe` up to `required` times and returns `True` only if it observes `required` `True` results (short-circuits on the first `False`). `required >= 1`.

- [ ] **Step 1: Write the failing test** (append)

```python
from signal_control.conditioners import Corroborator


def test_corroborator_confirms_when_all_probes_true():
    calls = {"n": 0}

    def probe() -> bool:
        calls["n"] += 1
        return True

    c = Corroborator(probe=probe, required=3)
    assert c.confirm() is True
    assert calls["n"] == 3


def test_corroborator_short_circuits_on_first_false():
    seq = iter([True, False, True])
    calls = {"n": 0}

    def probe() -> bool:
        calls["n"] += 1
        return next(seq)

    c = Corroborator(probe=probe, required=3)
    assert c.confirm() is False
    assert calls["n"] == 2  # stopped at the False


def test_corroborator_rejects_bad_required():
    with pytest.raises(ValueError):
        Corroborator(probe=lambda: True, required=0)
```

- [ ] **Step 2: Run to verify fail** — `ImportError: cannot import name 'Corroborator'`

- [ ] **Step 3: Implement** (append; add `from collections.abc import Callable` to the imports)

```python
@dataclass
class Corroborator:
    """Independently re-observe a signal before acting on it.

    ``probe`` is a cheap live check; ``confirm()`` requires ``required``
    consecutive ``True`` observations. Any high-blast-radius signal (credit
    exhaustion, "sensor broke", "loop wedged") must corroborate before driving
    an irreversible action.
    """

    probe: Callable[[], bool]
    required: int

    def __post_init__(self) -> None:
        if self.required < 1:
            raise ValueError(f"required must be >= 1, got {self.required}")

    def confirm(self) -> bool:
        for _ in range(self.required):
            if not self.probe():
                return False
        return True
```

- [ ] **Step 4: Run to verify pass** — PASS

- [ ] **Step 5: Commit**

```bash
git add src/signal_control/conditioners.py tests/signal_control/test_conditioners.py
git commit -m "feat(signal-control): Corroborator conditioner

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: `AimdController`

**Files:**
- Create: `src/signal_control/controllers.py`
- Test: `tests/signal_control/test_controllers.py`

**Interfaces:**
- Produces: `AimdController(lo: int, hi: int, start: int, decrease_factor: float = 0.5, increase_step: int = 1, hold_ticks: int = 3)` with `.update(*, breached: bool, headroom: bool) -> int` and `.cap: int`. Breach → multiplicative decrease (immediate); sustained headroom for `hold_ticks` → additive increase; cap always clamped to `[lo, hi]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/signal_control/test_controllers.py
from __future__ import annotations

import pytest
from hypothesis import given, strategies as st

from signal_control.controllers import AimdController


def test_aimd_multiplicative_decrease_on_breach():
    a = AimdController(lo=1, hi=16, start=16, decrease_factor=0.5)
    assert a.update(breached=True, headroom=False) == 8
    assert a.update(breached=True, headroom=False) == 4


def test_aimd_additive_increase_after_sustained_headroom():
    a = AimdController(lo=1, hi=16, start=4, increase_step=1, hold_ticks=3)
    assert a.update(breached=False, headroom=True) == 4   # streak 1
    assert a.update(breached=False, headroom=True) == 4   # streak 2
    assert a.update(breached=False, headroom=True) == 5   # streak 3 -> +1
    assert a.update(breached=False, headroom=True) == 5   # streak resets, back to 1


def test_aimd_neutral_tick_resets_headroom_streak():
    a = AimdController(lo=1, hi=16, start=4, hold_ticks=2)
    a.update(breached=False, headroom=True)               # streak 1
    a.update(breached=False, headroom=False)              # neutral -> reset
    assert a.update(breached=False, headroom=True) == 4   # streak 1 again, no bump


@given(
    steps=st.lists(st.tuples(st.booleans(), st.booleans()), min_size=1, max_size=300),
)
def test_aimd_cap_always_within_bounds(steps):
    a = AimdController(lo=1, hi=8, start=8)
    for breached, headroom in steps:
        cap = a.update(breached=breached, headroom=headroom)
        assert 1 <= cap <= 8


def test_aimd_rejects_bad_bounds():
    with pytest.raises(ValueError):
        AimdController(lo=5, hi=1, start=3)
    with pytest.raises(ValueError):
        AimdController(lo=1, hi=8, start=99)
```

- [ ] **Step 2: Run to verify fail** — `ModuleNotFoundError: No module named 'signal_control.controllers'`

- [ ] **Step 3: Implement**

```python
# src/signal_control/controllers.py
"""Controllers — drive an actuator toward a setpoint with bounded, stable moves.

Pure policy objects: they compute the next actuator value from a scalar/boolean
signal. Wiring to a real actuator (max_workers, a rebase cycle) happens in later
stages. ``CircuitBreaker`` is re-exported from the existing src/circuit_breaker.py
so callers have a single import point.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from circuit_breaker import CircuitBreaker  # re-export; see Task 10

__all__ = ["AimdController", "CircuitBreaker"]


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
            raise ValueError(f"decrease_factor must be in (0, 1), got {self.decrease_factor}")
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
```

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONPATH=src uv run pytest tests/signal_control/test_controllers.py -k aimd -q`
Expected: PASS (note: `CircuitBreaker` import already works since `src/circuit_breaker.py` exists)

- [ ] **Step 5: Commit**

```bash
git add src/signal_control/controllers.py tests/signal_control/test_controllers.py
git commit -m "feat(signal-control): AimdController + CircuitBreaker re-export

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: `PidController` (with anti-windup)

**Files:**
- Modify: `src/signal_control/controllers.py`
- Test: `tests/signal_control/test_controllers.py`

**Interfaces:**
- Produces: `PidController(kp: float, ki: float, kd: float, out_lo: float, out_hi: float)` with `.update(error: float) -> float`. Output clamped to `[out_lo, out_hi]`; integral clamped (anti-windup) so it can never push the output past the bounds and back-winds when saturated.

- [ ] **Step 1: Write the failing test** (append to `tests/signal_control/test_controllers.py`)

```python
from signal_control.controllers import PidController


def test_pid_proportional_response_sign():
    pid = PidController(kp=1.0, ki=0.0, kd=0.0, out_lo=-10.0, out_hi=10.0)
    assert pid.update(3.0) == 3.0
    assert pid.update(-3.0) == -3.0


def test_pid_output_clamped_to_bounds():
    pid = PidController(kp=100.0, ki=0.0, kd=0.0, out_lo=-5.0, out_hi=5.0)
    assert pid.update(1.0) == 5.0
    assert pid.update(-1.0) == -5.0


@given(errors=st.lists(st.floats(min_value=-1e3, max_value=1e3), min_size=1, max_size=300))
def test_pid_output_always_within_bounds_and_no_windup(errors):
    pid = PidController(kp=0.5, ki=0.2, kd=0.1, out_lo=0.0, out_hi=10.0)
    for e in errors:
        out = pid.update(e)
        assert 0.0 <= out <= 10.0
    # anti-windup: after a long positive saturation, one big negative error
    # must bring the output off the ceiling within a bounded number of steps.
    for _ in range(1000):
        pid.update(100.0)  # saturate high
    assert pid.update(-100.0) < 10.0
```

- [ ] **Step 2: Run to verify fail** — `ImportError: cannot import name 'PidController'`

- [ ] **Step 3: Implement** (append; add `PidController` to `__all__`)

```python
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
            raise ValueError(f"out_hi ({self.out_hi}) must be >= out_lo ({self.out_lo})")

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
```

- [ ] **Step 4: Run to verify pass** — PASS

- [ ] **Step 5: Commit**

```bash
git add src/signal_control/controllers.py tests/signal_control/test_controllers.py
git commit -m "feat(signal-control): PidController with anti-windup

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: `RetryController` (bounded fix-retry policy)

**Files:**
- Modify: `src/signal_control/controllers.py`
- Test: `tests/signal_control/test_controllers.py`

**Interfaces:**
- Produces: `RetryStatus` (enum: `SUCCESS`, `RETRYABLE`, `TERMINAL`), `RetryOutcome(status: RetryStatus, detail: str = "")`, and `RetryController(max_attempts: int)` with `async def run(attempt: Callable[[int], Awaitable[RetryOutcome]]) -> RetryResult`. `RetryResult(succeeded: bool, attempts: int, terminal: bool, history: list[RetryOutcome])`. Stops on SUCCESS; short-circuits on TERMINAL; retries on RETRYABLE up to `max_attempts`.

- [ ] **Step 1: Write the failing test** (append)

```python
from signal_control.controllers import RetryController, RetryOutcome, RetryStatus


@pytest.mark.asyncio
async def test_retry_stops_on_success():
    async def attempt(n: int) -> RetryOutcome:
        return RetryOutcome(RetryStatus.SUCCESS)

    r = await RetryController(max_attempts=2).run(attempt)
    assert r.succeeded is True and r.attempts == 1 and r.terminal is False


@pytest.mark.asyncio
async def test_retry_exhausts_then_gives_up():
    calls = {"n": 0}

    async def attempt(n: int) -> RetryOutcome:
        calls["n"] += 1
        return RetryOutcome(RetryStatus.RETRYABLE, detail=f"try {n}")

    r = await RetryController(max_attempts=2).run(attempt)
    assert r.succeeded is False and r.attempts == 2 and r.terminal is False
    assert calls["n"] == 2
    assert [o.detail for o in r.history] == ["try 1", "try 2"]


@pytest.mark.asyncio
async def test_retry_short_circuits_on_terminal():
    calls = {"n": 0}

    async def attempt(n: int) -> RetryOutcome:
        calls["n"] += 1
        return RetryOutcome(RetryStatus.TERMINAL, detail="hard conflict")

    r = await RetryController(max_attempts=5).run(attempt)
    assert r.succeeded is False and r.terminal is True and r.attempts == 1
    assert calls["n"] == 1   # did not burn remaining attempts


def test_retry_rejects_bad_max_attempts():
    with pytest.raises(ValueError):
        RetryController(max_attempts=0)
```

- [ ] **Step 2: Run to verify fail** — `ImportError: cannot import name 'RetryController'`

- [ ] **Step 3: Implement** (append; add `RetryController`, `RetryOutcome`, `RetryStatus`, `RetryResult` to `__all__`; add `import enum`, `from collections.abc import Awaitable, Callable` to imports)

```python
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
```

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONPATH=src uv run pytest tests/signal_control/test_controllers.py -k retry -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/signal_control/controllers.py tests/signal_control/test_controllers.py
git commit -m "feat(signal-control): RetryController bounded fix-retry policy

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: Confirm `CircuitBreaker` re-export

**Files:**
- Modify: `src/signal_control/controllers.py` (already imports it in Task 7)
- Test: `tests/signal_control/test_controllers.py`

**Interfaces:**
- Consumes: existing `src/circuit_breaker.py:CircuitBreaker` (`record_success`, `record_failure`, `allow_request`, `state`, `reset`).
- Produces: `signal_control.controllers.CircuitBreaker` (same object, single import point).

- [ ] **Step 1: Write the failing test** (append)

```python
def test_circuit_breaker_reexported_is_the_canonical_one():
    import circuit_breaker as cb
    from signal_control.controllers import CircuitBreaker
    assert CircuitBreaker is cb.CircuitBreaker

    breaker = CircuitBreaker(name="t", max_failures=2)
    assert breaker.allow_request() is True
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.allow_request() is False  # OPEN
```

- [ ] **Step 2: Run to verify fail/pass**

Run: `PYTHONPATH=src uv run pytest tests/signal_control/test_controllers.py -k circuit -q`
Expected: PASS immediately (the re-export landed in Task 7). If it fails with ImportError, add `from circuit_breaker import CircuitBreaker` and `"CircuitBreaker"` to `__all__` in `controllers.py`.

- [ ] **Step 3: (no code change expected)** — the re-export exists from Task 7; this task pins it.

- [ ] **Step 4: Run to verify pass** — PASS

- [ ] **Step 5: Commit**

```bash
git add tests/signal_control/test_controllers.py
git commit -m "test(signal-control): pin CircuitBreaker re-export identity

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: `HistoricSignalStore` — in-memory ring buffers + reads

**Files:**
- Create: `src/signal_control/store.py`
- Test: `tests/signal_control/test_store.py`

**Interfaces:**
- Produces: `HistoricSignalStore(max_len: int = 512, max_age_s: float = 86_400.0, clock: Callable[[], float] = time.monotonic)` with:
  - `.record(signal: str, value: float, tags: dict | None = None) -> None`
  - `.window(signal: str, age_s: float | None = None) -> list[float]` (values, newest-inclusive, age-filtered)
  - `.ewma(signal: str, alpha: float) -> float | None`
  - `.mean(signal, age_s=None) -> float | None`, `.mad(signal, age_s=None) -> float | None`
  - `.count_where(signal, pred: Callable[[float], bool], age_s=None) -> int`
  - `.slope(signal) -> float | None` (least-squares slope over sample index)

- [ ] **Step 1: Write the failing test**

```python
# tests/signal_control/test_store.py
from __future__ import annotations

from signal_control.store import HistoricSignalStore


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def test_record_and_window():
    s = HistoricSignalStore(clock=FakeClock())
    for v in (1.0, 2.0, 3.0):
        s.record("x", v)
    assert s.window("x") == [1.0, 2.0, 3.0]
    assert s.window("unknown") == []


def test_ring_buffer_bounded_by_max_len():
    s = HistoricSignalStore(max_len=3, clock=FakeClock())
    for v in range(6):
        s.record("x", float(v))
    assert s.window("x") == [3.0, 4.0, 5.0]  # oldest dropped


def test_age_pruning():
    clk = FakeClock()
    s = HistoricSignalStore(max_age_s=10.0, clock=clk)
    s.record("x", 1.0)
    clk.advance(20.0)
    s.record("x", 2.0)      # recording prunes the stale 1.0
    assert s.window("x") == [2.0]


def test_reads():
    s = HistoricSignalStore(clock=FakeClock())
    for v in (2.0, 4.0, 6.0, 8.0):
        s.record("x", v)
    assert s.mean("x") == 5.0
    assert s.count_where("x", lambda v: v > 4.0) == 2
    assert s.ewma("x", alpha=1.0) == 8.0
    assert s.slope("x") == 2.0     # perfectly linear step of 2
    assert s.mean("missing") is None
```

- [ ] **Step 2: Run to verify fail** — `ModuleNotFoundError: No module named 'signal_control.store'`

- [ ] **Step 3: Implement**

```python
# src/signal_control/store.py
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
from dataclasses import dataclass, field

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

    def record(self, signal: str, value: float, tags: dict[str, str] | None = None) -> None:
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
```

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONPATH=src uv run pytest tests/signal_control/test_store.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/signal_control/store.py tests/signal_control/test_store.py
git commit -m "feat(signal-control): HistoricSignalStore ring buffers + reads

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 12: `HistoricSignalStore` — JSONL persistence + reload

**Files:**
- Modify: `src/signal_control/store.py`
- Test: `tests/signal_control/test_store.py`

**Interfaces:**
- Extends `HistoricSignalStore.__init__` with `path: Path | None = None`. When set: each `record` appends one JSON line `{"signal","ts","value","tags"}`; construction reloads existing lines (age+count pruned) so a restart resumes with warm history. `path=None` keeps the store purely in-memory.

- [ ] **Step 1: Write the failing test** (append to `tests/signal_control/test_store.py`)

```python
from pathlib import Path


def test_jsonl_round_trip(tmp_path: Path):
    clk = FakeClock()
    p = tmp_path / "sig.jsonl"
    s1 = HistoricSignalStore(clock=clk, path=p)
    s1.record("x", 1.0, tags={"k": "v"})
    s1.record("x", 2.0)
    # New store over the same file reloads history.
    s2 = HistoricSignalStore(clock=clk, path=p)
    assert s2.window("x") == [1.0, 2.0]


def test_reload_prunes_by_age(tmp_path: Path):
    clk = FakeClock()
    p = tmp_path / "sig.jsonl"
    s1 = HistoricSignalStore(max_age_s=10.0, clock=clk, path=p)
    s1.record("x", 1.0)
    clk.advance(100.0)
    s2 = HistoricSignalStore(max_age_s=10.0, clock=clk, path=p)
    assert s2.window("x") == []   # stale sample dropped on reload


def test_in_memory_when_no_path(tmp_path: Path):
    s = HistoricSignalStore(clock=FakeClock(), path=None)
    s.record("x", 1.0)
    assert not list(tmp_path.iterdir())   # nothing written
```

- [ ] **Step 2: Run to verify fail** — `TypeError: __init__() got an unexpected keyword argument 'path'`

- [ ] **Step 3: Implement** (modify `store.py`: add `import json`, `from pathlib import Path`; add `path` param, a `_persist` call in `record`, and a `_reload` call in `__init__`)

```python
    # --- in __init__ signature, add: path: Path | None = None
    #     and after self._signals = {} add:
    #         self._path = path
    #         if path is not None:
    #             self._reload()

    def _persist(self, signal: str, sample: Sample) -> None:
        if self._path is None:
            return
        line = json.dumps(
            {"signal": signal, "ts": sample.ts, "value": sample.value, "tags": sample.tags}
        )
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def _reload(self) -> None:
        assert self._path is not None
        if not self._path.exists():
            return
        cutoff = self._clock() - self._max_age_s
        for raw in self._path.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                rec = json.loads(raw)
                ts, value = float(rec["ts"]), float(rec["value"])
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue  # skip a corrupt line, never fail the boot
            if ts < cutoff:
                continue
            buf = self._signals.setdefault(rec["signal"], deque(maxlen=self._max_len))
            buf.append(Sample(ts, value, dict(rec.get("tags") or {})))
```

Then update `record` to call `self._persist(signal, buf[-1])` after `self._prune(buf)`.

- [ ] **Step 4: Run to verify pass** — PASS

- [ ] **Step 5: Commit**

```bash
git add src/signal_control/store.py tests/signal_control/test_store.py
git commit -m "feat(signal-control): HistoricSignalStore JSONL persistence + reload

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 13: Public API surface + full-substrate green gate

**Files:**
- Modify: `src/signal_control/__init__.py`
- Test: `tests/signal_control/test_api.py`

**Interfaces:**
- Produces: top-level re-exports so consumers write `from signal_control import Ewma, AimdController, HistoricSignalStore, ...` — the names later stages import.

- [ ] **Step 1: Write the failing test**

```python
# tests/signal_control/test_api.py
import signal_control as sc


def test_public_api_surface():
    for name in (
        "Ewma", "SchmittHysteresis", "Persistence", "Cusum",
        "AdaptiveThreshold", "Corroborator",
        "AimdController", "PidController", "RetryController",
        "RetryOutcome", "RetryStatus", "CircuitBreaker",
        "HistoricSignalStore",
    ):
        assert hasattr(sc, name), f"signal_control is missing {name}"
```

- [ ] **Step 2: Run to verify fail** — `AssertionError: signal_control is missing Ewma`

- [ ] **Step 3: Implement** (append to `src/signal_control/__init__.py`)

```python
from signal_control.conditioners import (
    AdaptiveThreshold,
    Corroborator,
    Cusum,
    Ewma,
    Persistence,
    SchmittHysteresis,
)
from signal_control.controllers import (
    AimdController,
    CircuitBreaker,
    PidController,
    RetryController,
    RetryOutcome,
    RetryStatus,
)
from signal_control.store import HistoricSignalStore

__all__ = [
    "Ewma", "SchmittHysteresis", "Persistence", "Cusum", "AdaptiveThreshold",
    "Corroborator", "AimdController", "PidController", "RetryController",
    "RetryOutcome", "RetryStatus", "CircuitBreaker", "HistoricSignalStore",
]
```

- [ ] **Step 4: Run the full substrate suite + lint + types**

Run:
```bash
PYTHONPATH=src uv run pytest tests/signal_control/ -q
uv run ruff check src/signal_control tests/signal_control
PYTHONPATH=src uv run pyright src/signal_control
```
Expected: all pass; ruff clean; pyright 0 errors.

- [ ] **Step 5: Commit**

```bash
git add src/signal_control/__init__.py tests/signal_control/test_api.py
git commit -m "feat(signal-control): public API surface + full-substrate gate

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage (Stage 1 = spec §7 module layout `store.py`/`conditioners.py`/`controllers.py`, plus the conditioner/controller vocabulary from §2–§4 and the `hypothesis` property tests from §7):**
- Conditioners §3 — Ewma (T1), SchmittHysteresis (T2), Persistence (T3), Cusum (T4), AdaptiveThreshold (T5), Corroborator (T6). ✅
- Controllers §2/§5 — AimdController (T7), PidController (T8), RetryController (T9), CircuitBreaker adapt (T7/T10). ✅
- HistoricSignalStore §4 — ring buffers + reads (T11), JSONL persist + reload with fail-safe skip of corrupt lines + cold-boot age-prune (T12). ✅
- §7 property-based tests — every conditioner/controller has a `hypothesis` property test asserting its invariant (bounds, no-flap, streak, CUSUM noise-immunity, AIMD bounds, PID bounds+anti-windup, retry termination). ✅
- Out of scope by design (own later plans): governor.py wiring to `max_workers` (Stage 3), RC RetryController wiring in StagingPromotionLoop (Stage 2), detector migration (Stage 4), observability/ADR/UL (Stage 5), Antithesis DST spike (#10361).

**Placeholder scan:** No TBD/TODO; every code step shows complete code. Task 10 is a pin-only task (re-export already landed in Task 7) — explicitly noted, not a placeholder. Task 12's diff is described against the exact `__init__`/`record` insertion points with full method bodies.

**Type consistency:** `Ewma(alpha)`, `.update`/`.value` consistent across T1/T11 (store reuses `Ewma`). `RetryStatus`/`RetryOutcome`/`RetryResult`/`RetryController.run` names consistent T9→T13. `HistoricSignalStore` ctor `(max_len, max_age_s, clock, path)` consistent T11→T12→T13. `CircuitBreaker` re-export identity pinned T7/T10/T13. All names match the Global Constraints naming list.
