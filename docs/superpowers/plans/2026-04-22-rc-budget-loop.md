# RC Budget Loop — §4.8 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Land `RCBudgetLoop` (spec §4.8) — a 4h `BaseBackgroundLoop` subclass that reads the last 30 days of RC CI wall-clock durations via `gh run list`, detects bloat via two complementary signals (rolling-median ratio + spike-vs-recent-max ratio), files a `hydraflow-find` + `rc-duration-regression` issue per trip, and escalates to `hitl-escalation` + `rc-duration-stuck` after 3 unresolved attempts. Kill-switch via `LoopDeps.enabled_cb("rc_budget")` per spec §3.2 / §12.2 — **no `rc_budget_enabled` config field**.

**Architecture:** New `src/rc_budget_loop.py`; new state mixin `src/state/_rc_budget.py`; three config fields (`rc_budget_interval`, `rc_budget_threshold_ratio`, `rc_budget_spike_ratio`) + env overrides; five-checkpoint wiring (service registry, orchestrator `bg_loop_registry` + `loop_factories`, UI `constants.js`, dashboard `_INTERVAL_BOUNDS`, auto-covered `test_loop_wiring_completeness.py`). One MockWorld scenario plus a catalog builder. Dedup keys `rc_budget:median` and `rc_budget:spike`; per-signal attempt counters in `state.rc_budget_attempts`.

**Spec refs:** `docs/superpowers/specs/2026-04-22-trust-architecture-hardening-design.md` §4.8, §3.2, §12.2.

**Sibling plan carries (locked from caretaker-fleet-part-1):**

1. Lazy-import `trace_collector.emit_loop_subprocess_trace` via `try/except ImportError` (Plan 6 owns it; tolerate absence).
2. DedupStore clearance via `set_all(remaining)` — no `remove`/`discard` method (verified `src/dedup_store.py:19-65`).
3. Escalation key format `f"{worker_name}:{subject}"` → here `rc_budget:median` and `rc_budget:spike`.
4. Threshold comparisons are `>=` (matches §3.2 "3 attempts" convention).
5. No `rc_budget_enabled` config field — kill-switch through `LoopDeps.enabled_cb("rc_budget")` only.

**Decisions locked (spec deferred or implied):**

6. **Run source** is `.github/workflows/rc-promotion-scenario.yml` (RC gate workflow).
7. **"Current" run** = newest completed run regardless of conclusion. A bloated-but-red run is still signal.
8. **30-day window** filtered client-side from `gh run list --limit 100 --status completed` — the CLI does not accept a server-side `created` filter and 100 entries is plenty for a daily-cadence workflow.
9. **Duration units** stored as integer seconds (`(updatedAt - startedAt).total_seconds()`).
10. **Baselines exclude current.** `rolling_median` = `statistics.median(all_others)`. `recent_max` = `max(top-5 others by createdAt)`. Below 5 historical runs → `{"status": "warmup"}` — a newly-set-up repo has no signal.
11. **History cap** = 60 entries in `state.rc_budget_duration_history` (two-months safety margin); overwritten each tick — idempotent.
12. **Per-job breakdown** via `gh run view <id> --json jobs`; top 10 sorted slowest first.
13. **Top-10 slowest tests** from the `junit-scenario` artifact (prereq landed via caretaker-fleet Plan Task F0). If `gh run download` fails, the section is elided with a one-line note — tolerant.
14. **Both signals may fire** on the same tick — they dedup to two distinct keys and the loop files two issues if needed.
15. **Close-reconcile** polls `gh issue list --state closed --label hitl-escalation --label rc-duration-stuck --author @me`; title-tail match `(median)` / `(spike)` clears the matching dedup key and resets the attempt counter. Called at the top of each tick — no separate cron (spec §3.2).

---

## File Structure

| File | Role | C/M |
|---|---|---|
| `src/models.py:1757` | Append `rc_budget_duration_history: list[dict[str, Any]]` + `rc_budget_attempts: dict[str, int]` StateData fields | M |
| `src/state/_rc_budget.py` | New `RCBudgetStateMixin` — history getter/setter + attempt getter/inc/clear | C |
| `src/state/__init__.py:28-45, 55-75` | Import mixin + append to `StateTracker` MRO | M |
| `src/config.py:174` | Append `rc_budget_interval` env-override row | M |
| `src/config.py:214` | Append two float env-override rows (`threshold_ratio`, `spike_ratio`) | M |
| `src/config.py:1619` | Three `HydraFlowConfig` fields after `retrospective_interval` | M |
| `src/rc_budget_loop.py` | New loop — fetcher + baselines + signals + filing + escalation + reconcile | C |
| `src/service_registry.py:63,168,813,871` | Import + dataclass field + constructor block + `ServiceRegistry(...)` kwarg | M |
| `src/orchestrator.py:158,909` | `bg_loop_registry` entry + `loop_factories` tuple | M |
| `src/ui/src/constants.js:252,273,312` | `EDITABLE_INTERVAL_WORKERS` + `SYSTEM_WORKER_INTERVALS` + `BACKGROUND_WORKERS` entries | M |
| `src/dashboard_routes/_common.py:55` | `_INTERVAL_BOUNDS` entry | M |
| `tests/test_state_rc_budget.py` | Mixin unit tests | C |
| `tests/test_config_rc_budget.py` | Config unit tests | C |
| `tests/test_rc_budget_loop.py` | Loop unit tests (skeleton, warmup, baselines, signals, filing, escalation, reconcile, kill-switch, both-signal) | C |
| `tests/scenarios/catalog/loop_registrations.py:257` | `_build_rc_budget` + `_BUILDERS` entry | M |
| `tests/scenarios/catalog/test_loop_instantiation.py:22` | `"rc_budget",` | M |
| `tests/scenarios/catalog/test_loop_registrations.py:22` | `"rc_budget",` | M |
| `tests/scenarios/test_rc_budget_scenario.py` | MockWorld scenario — fabricate 30d of runs + spike + assert filing | C |
| `tests/test_loop_wiring_completeness.py` | Regex auto-discovery — no edit required | Covered |

---

## Task 1 — State schema for duration history

**Modify** `src/models.py:1757` — after `code_grooming_filed: list[str] = Field(default_factory=list)`, insert:

```python
    # Trust fleet — RCBudgetLoop (spec §4.8)
    rc_budget_duration_history: list[dict[str, Any]] = Field(default_factory=list)
    rc_budget_attempts: dict[str, int] = Field(default_factory=dict)
```

If `Any` isn't already imported at module top, add `from typing import Any`.

**Modify** `src/state/__init__.py:28-45` — add `from ._rc_budget import RCBudgetStateMixin` in alphabetical position; `src/state/__init__.py:55-75` — append `RCBudgetStateMixin` to the `StateTracker` MRO (before the closing `):`).

- [ ] **Step 1: Write failing mixin test** — `tests/test_state_rc_budget.py`:

```python
"""Tests for RCBudgetStateMixin (spec §4.8)."""

from __future__ import annotations

from pathlib import Path

from state import StateTracker


def _tracker(tmp_path: Path) -> StateTracker:
    return StateTracker(state_file=tmp_path / "state.json")


def test_set_and_get_duration_history(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    history = [
        {"run_id": 1, "created_at": "2026-04-01T00:00:00Z",
         "duration_s": 300, "conclusion": "success"},
        {"run_id": 2, "created_at": "2026-04-02T00:00:00Z",
         "duration_s": 480, "conclusion": "success"},
    ]
    st.set_rc_budget_duration_history(history)
    assert st.get_rc_budget_duration_history() == history


def test_inc_rc_budget_attempts_is_monotonic(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    assert st.get_rc_budget_attempts("median") == 0
    assert st.inc_rc_budget_attempts("median") == 1
    assert st.inc_rc_budget_attempts("median") == 2
    assert st.get_rc_budget_attempts("spike") == 0


def test_clear_rc_budget_attempts(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    st.inc_rc_budget_attempts("median")
    st.clear_rc_budget_attempts("median")
    assert st.get_rc_budget_attempts("median") == 0
```

- [ ] **Step 2: Run — expect FAIL** (`AttributeError`): `PYTHONPATH=src uv run pytest tests/test_state_rc_budget.py -v`

- [ ] **Step 3: Create** `src/state/_rc_budget.py`:

```python
"""State accessors for RCBudgetLoop (spec §4.8)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from models import StateData


class RCBudgetStateMixin:
    """Duration history + per-signal repair attempts."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    def get_rc_budget_duration_history(self) -> list[dict[str, Any]]:
        return [dict(entry) for entry in self._data.rc_budget_duration_history]

    def set_rc_budget_duration_history(
        self, history: list[dict[str, Any]]
    ) -> None:
        self._data.rc_budget_duration_history = [dict(entry) for entry in history]
        self.save()

    def get_rc_budget_attempts(self, subject: str) -> int:
        return int(self._data.rc_budget_attempts.get(subject, 0))

    def inc_rc_budget_attempts(self, subject: str) -> int:
        current = int(self._data.rc_budget_attempts.get(subject, 0)) + 1
        attempts = dict(self._data.rc_budget_attempts)
        attempts[subject] = current
        self._data.rc_budget_attempts = attempts
        self.save()
        return current

    def clear_rc_budget_attempts(self, subject: str) -> None:
        attempts = dict(self._data.rc_budget_attempts)
        attempts.pop(subject, None)
        self._data.rc_budget_attempts = attempts
        self.save()
```

- [ ] **Step 4: Apply models.py + state/__init__.py edits (above).**
- [ ] **Step 5: Re-run — expect 3 PASS.**
- [ ] **Step 6: Commit:** `git add src/models.py src/state/_rc_budget.py src/state/__init__.py tests/test_state_rc_budget.py && git commit -m "feat(state): RCBudgetStateMixin + duration_history/attempts fields (§4.8)"`

---

## Task 2 — Config fields + env overrides

**Modify** `src/config.py:1619` — after `retrospective_interval`'s closing `)`:

```python
    # Trust fleet — RCBudgetLoop (spec §4.8)
    rc_budget_interval: int = Field(
        default=14400, ge=3600, le=604800,
        description="Seconds between RCBudgetLoop ticks (default 4h)",
    )
    rc_budget_threshold_ratio: float = Field(
        default=1.5, ge=1.0, le=5.0,
        description="Multiplier vs. 30-day rolling median; current_s >= ratio * median_s fires.",
    )
    rc_budget_spike_ratio: float = Field(
        default=2.0, ge=1.0, le=10.0,
        description="Multiplier vs. max(recent 5 excl. current); current_s >= ratio * recent_max fires.",
    )
```

**Modify** `src/config.py:174` (`_ENV_INT_OVERRIDES`) — append: `("rc_budget_interval", "HYDRAFLOW_RC_BUDGET_INTERVAL", 14400),`

**Modify** `src/config.py:214` (`_ENV_FLOAT_OVERRIDES`) — append:

```python
    ("rc_budget_threshold_ratio", "HYDRAFLOW_RC_BUDGET_THRESHOLD_RATIO", 1.5),
    ("rc_budget_spike_ratio", "HYDRAFLOW_RC_BUDGET_SPIKE_RATIO", 2.0),
```

- [ ] **Step 1: Write failing test** — `tests/test_config_rc_budget.py`:

```python
"""Tests for RCBudgetLoop config fields (spec §4.8)."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from config import HydraFlowConfig


def test_rc_budget_defaults() -> None:
    cfg = HydraFlowConfig()
    assert cfg.rc_budget_interval == 14400
    assert cfg.rc_budget_threshold_ratio == 1.5
    assert cfg.rc_budget_spike_ratio == 2.0


def test_rc_budget_interval_env_override() -> None:
    with patch.dict(os.environ, {"HYDRAFLOW_RC_BUDGET_INTERVAL": "3600"}):
        assert HydraFlowConfig.from_env().rc_budget_interval == 3600


def test_rc_budget_ratios_env_override() -> None:
    env = {
        "HYDRAFLOW_RC_BUDGET_THRESHOLD_RATIO": "1.25",
        "HYDRAFLOW_RC_BUDGET_SPIKE_RATIO": "3.0",
    }
    with patch.dict(os.environ, env):
        cfg = HydraFlowConfig.from_env()
        assert cfg.rc_budget_threshold_ratio == 1.25
        assert cfg.rc_budget_spike_ratio == 3.0


def test_rc_budget_interval_bounds() -> None:
    with pytest.raises(ValueError):
        HydraFlowConfig(rc_budget_interval=30)
    with pytest.raises(ValueError):
        HydraFlowConfig(rc_budget_interval=10_000_000)
```

- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Apply config.py edits (above).**
- [ ] **Step 4: Re-run — expect 4 PASS.**
- [ ] **Step 5: Commit:** `git add src/config.py tests/test_config_rc_budget.py && git commit -m "feat(config): rc_budget_interval + threshold/spike ratios + env overrides (§4.8)"`

---

## Task 3 — Loop skeleton + tick stub

- [ ] **Step 1: Write failing test** — `tests/test_rc_budget_loop.py`:

```python
"""Tests for RCBudgetLoop (spec §4.8)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus
from rc_budget_loop import RCBudgetLoop


def _deps(stop: asyncio.Event, enabled: bool = True) -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(), stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: enabled,
    )


@pytest.fixture
def loop_env(tmp_path: Path):
    cfg = HydraFlowConfig(data_root=tmp_path, repo="hydra/hydraflow")
    state = MagicMock()
    state.get_rc_budget_duration_history.return_value = []
    state.get_rc_budget_attempts.return_value = 0
    state.inc_rc_budget_attempts.return_value = 1
    pr_manager = AsyncMock()
    pr_manager.create_issue = AsyncMock(return_value=42)
    dedup = MagicMock()
    dedup.get.return_value = set()
    return cfg, state, pr_manager, dedup


def _loop(env) -> RCBudgetLoop:
    cfg, state, pr, dedup = env
    return RCBudgetLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup,
        deps=_deps(asyncio.Event()),
    )


def test_skeleton_worker_name_and_interval(loop_env) -> None:
    loop = _loop(loop_env)
    assert loop._worker_name == "rc_budget"
    assert loop._get_default_interval() == 14400


async def test_do_work_warmup_when_history_short(loop_env) -> None:
    loop = _loop(loop_env)
    loop._fetch_recent_runs = AsyncMock(return_value=[
        {"databaseId": i, "duration_s": 300,
         "createdAt": f"2026-04-{i:02d}T00:00:00Z", "conclusion": "success"}
        for i in range(1, 4)
    ])
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    stats = await loop._do_work()
    assert stats["status"] == "warmup"
    _, _, pr, _ = loop_env
    pr.create_issue.assert_not_awaited()
```

- [ ] **Step 2: Run — expect FAIL (`ImportError`).**

- [ ] **Step 3: Create** `src/rc_budget_loop.py`:

```python
"""RCBudgetLoop — 4h RC CI wall-clock regression detector (spec §4.8).

Reads the last 30 days of ``rc-promotion-scenario.yml`` runs via ``gh
run list``, extracts per-run wall-clock duration, and emits a
``hydraflow-find`` + ``rc-duration-regression`` issue when the newest
run trips either:

- *Gradual bloat*: ``current_s >= rc_budget_threshold_ratio *
  rolling_median`` (default ratio ``1.5``).
- *Sudden spike*: ``current_s >= rc_budget_spike_ratio * max(recent-5,
  excluding current)`` (default ratio ``2.0``).

Signals are independent; both may fire on the same tick (two distinct
dedup keys). After 3 unresolved attempts per signal the loop files a
``hitl-escalation`` + ``rc-duration-stuck`` issue. Dedup keys clear on
escalation-close per spec §3.2.

Kill-switch: ``LoopDeps.enabled_cb("rc_budget")`` — **no
``rc_budget_enabled`` config field** (spec §12.2).
"""

from __future__ import annotations

import asyncio
import json
import logging
import statistics
import tempfile
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from models import WorkCycleResult

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from dedup_store import DedupStore
    from pr_manager import PRManager
    from state import StateTracker

logger = logging.getLogger("hydraflow.rc_budget_loop")

_MAX_ATTEMPTS = 3
_WINDOW_DAYS = 30
_HISTORY_CAP = 60
_RECENT_N = 5
_MIN_HISTORY = 5
_WORKFLOW = "rc-promotion-scenario.yml"


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class RCBudgetLoop(BaseBackgroundLoop):
    """Detects RC wall-clock bloat via median + spike signals (spec §4.8)."""

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        state: StateTracker,
        pr_manager: PRManager,
        dedup: DedupStore,
        deps: LoopDeps,
    ) -> None:
        super().__init__(
            worker_name="rc_budget", config=config, deps=deps,
            run_on_startup=False,
        )
        self._state = state
        self._pr = pr_manager
        self._dedup = dedup

    def _get_default_interval(self) -> int:
        return self._config.rc_budget_interval

    async def _do_work(self) -> WorkCycleResult:
        """Skeleton — Task 5 replaces with the full tick."""
        await self._reconcile_closed_escalations()
        runs = await self._fetch_recent_runs()
        if len(runs) < _MIN_HISTORY:
            return {"status": "warmup", "runs_seen": len(runs)}
        return {"status": "noop", "runs_seen": len(runs)}

    async def _fetch_recent_runs(self) -> list[dict[str, Any]]:
        """Task 4."""
        return []

    async def _reconcile_closed_escalations(self) -> None:
        """Task 5."""
        return None
```

- [ ] **Step 4: Re-run — expect 2 PASS.**
- [ ] **Step 5: Commit:** `git add src/rc_budget_loop.py tests/test_rc_budget_loop.py && git commit -m "feat(loop): RCBudgetLoop skeleton + warmup short-circuit (§4.8)"`

---

## Task 4 — Fetcher + baseline computation

- [ ] **Step 1: Append failing tests** to `tests/test_rc_budget_loop.py`:

```python
def test_compute_baselines_median_and_recent_max(loop_env) -> None:
    loop = _loop(loop_env)
    runs = [
        {"databaseId": 10, "duration_s": 900,
         "createdAt": "2026-04-20T00:00:00Z", "conclusion": "success"},
        {"databaseId": 9, "duration_s": 310,
         "createdAt": "2026-04-19T00:00:00Z", "conclusion": "success"},
        {"databaseId": 8, "duration_s": 300,
         "createdAt": "2026-04-18T00:00:00Z", "conclusion": "success"},
        {"databaseId": 7, "duration_s": 320,
         "createdAt": "2026-04-17T00:00:00Z", "conclusion": "success"},
        {"databaseId": 6, "duration_s": 290,
         "createdAt": "2026-04-16T00:00:00Z", "conclusion": "success"},
        {"databaseId": 5, "duration_s": 315,
         "createdAt": "2026-04-15T00:00:00Z", "conclusion": "success"},
    ]
    current, baselines = loop._compute_baselines(runs)
    assert current["databaseId"] == 10
    assert baselines["recent_max"] == 320
    assert baselines["rolling_median"] == 315  # median of 310,300,320,290,315
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Replace `_fetch_recent_runs` + append helpers** inside `RCBudgetLoop`:

```python
    async def _fetch_recent_runs(self) -> list[dict[str, Any]]:
        cmd = [
            "gh", "run", "list",
            "--repo", self._config.repo,
            "--workflow", _WORKFLOW,
            "--limit", "100",
            "--status", "completed",
            "--json", "databaseId,url,conclusion,createdAt,updatedAt,startedAt",
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.warning(
                "gh run list exit=%d: %s",
                proc.returncode, stderr.decode(errors="replace")[:400],
            )
            return []
        try:
            raw = json.loads(stdout.decode() or "[]")
        except json.JSONDecodeError:
            return []
        cutoff = datetime.now(UTC) - timedelta(days=_WINDOW_DAYS)
        out: list[dict[str, Any]] = []
        for run in raw:
            created = _parse_iso(run.get("createdAt"))
            started = _parse_iso(run.get("startedAt") or run.get("createdAt"))
            updated = _parse_iso(run.get("updatedAt"))
            if not created or not started or not updated or created < cutoff:
                continue
            out.append({**run, "duration_s":
                        max(0, int((updated - started).total_seconds()))})
        out.sort(key=lambda r: r.get("createdAt", ""), reverse=True)
        return out[:_HISTORY_CAP]

    def _compute_baselines(
        self, runs: list[dict[str, Any]]
    ) -> tuple[dict[str, Any], dict[str, int]]:
        current = max(runs, key=lambda r: r.get("createdAt", ""))
        others = [r for r in runs if r.get("databaseId") != current.get("databaseId")]
        others.sort(key=lambda r: r.get("createdAt", ""), reverse=True)
        durations = [int(r["duration_s"]) for r in others]
        recent = durations[:_RECENT_N]
        return current, {
            "rolling_median": int(statistics.median(durations)) if durations else 0,
            "recent_max": max(recent) if recent else 0,
        }
```

- [ ] **Step 4: Re-run — expect 3 PASS.**
- [ ] **Step 5: Commit:** `git add src/rc_budget_loop.py tests/test_rc_budget_loop.py && git commit -m "feat(loop): RCBudget fetch runs + median/max baselines (§4.8)"`

---

## Task 5 — Signal check, filing, escalation, reconcile

- [ ] **Step 1: Append failing tests** to `tests/test_rc_budget_loop.py`:

```python
def _history(seven_at_300: bool = True) -> list[dict[str, Any]]:
    """6 prior runs at 300s (or noted) + current at an overridable value."""
    return [
        {"databaseId": i, "duration_s": 300,
         "createdAt": f"2026-04-{10 + i:02d}T00:00:00Z",
         "conclusion": "success", "url": f"u{i}"}
        for i in range(1, 7)
    ]


async def test_do_work_files_issue_on_median_signal(loop_env) -> None:
    loop = _loop(loop_env)
    runs = [
        {"databaseId": 99, "duration_s": 600,
         "createdAt": "2026-04-20T00:00:00Z",
         "conclusion": "success", "url": "u99"},
        *_history(),
    ]
    loop._fetch_recent_runs = AsyncMock(return_value=runs)
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    loop._fetch_job_breakdown = AsyncMock(return_value=[])
    loop._fetch_junit_tests = AsyncMock(return_value=[])
    stats = await loop._do_work()
    assert stats["filed"] >= 1
    _, _, pr, _ = loop_env
    title = pr.create_issue.await_args.args[0]
    assert "RC gate duration regression" in title
    labels = pr.create_issue.await_args.args[2]
    assert "hydraflow-find" in labels and "rc-duration-regression" in labels


async def test_do_work_skips_when_dedup_key_present(loop_env) -> None:
    cfg, state, pr, dedup = loop_env
    dedup.get.return_value = {"rc_budget:median", "rc_budget:spike"}
    loop = _loop(loop_env)
    runs = [
        {"databaseId": 99, "duration_s": 9000,
         "createdAt": "2026-04-20T00:00:00Z",
         "conclusion": "success", "url": "u"},
        *_history(),
    ]
    loop._fetch_recent_runs = AsyncMock(return_value=runs)
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    loop._fetch_job_breakdown = AsyncMock(return_value=[])
    loop._fetch_junit_tests = AsyncMock(return_value=[])
    stats = await loop._do_work()
    assert stats["filed"] == 0
    pr.create_issue.assert_not_awaited()


async def test_escalation_fires_after_three_attempts(loop_env) -> None:
    cfg, state, pr, dedup = loop_env
    state.inc_rc_budget_attempts.return_value = 3
    loop = _loop(loop_env)
    runs = [
        {"databaseId": 99, "duration_s": 9000,
         "createdAt": "2026-04-20T00:00:00Z",
         "conclusion": "success", "url": "u"},
        *_history(),
    ]
    loop._fetch_recent_runs = AsyncMock(return_value=runs)
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    loop._fetch_job_breakdown = AsyncMock(return_value=[])
    loop._fetch_junit_tests = AsyncMock(return_value=[])
    stats = await loop._do_work()
    assert stats["escalated"] >= 1
    assert any(
        "hitl-escalation" in call.args[2] and "rc-duration-stuck" in call.args[2]
        for call in pr.create_issue.await_args_list
    )


async def test_reconcile_closed_escalations_clears_dedup(
    loop_env, monkeypatch
) -> None:
    cfg, state, pr, dedup = loop_env
    dedup.get.return_value = {"rc_budget:median", "rc_budget:spike"}
    loop = _loop(loop_env)

    class _P:
        returncode = 0
        async def communicate(self):
            return (
                b'[{"title": "HITL: RC gate duration regression (median) '
                b'unresolved after 3 attempts"}]',
                b"",
            )

    async def fake_subproc(*args, **kwargs):
        return _P()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subproc)
    await loop._reconcile_closed_escalations()
    dedup.set_all.assert_called_once()
    remaining = dedup.set_all.call_args.args[0]
    assert "rc_budget:median" not in remaining
    assert "rc_budget:spike" in remaining
    state.clear_rc_budget_attempts.assert_called_once_with("median")
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Replace `_do_work` + append helpers** in `src/rc_budget_loop.py`:

```python
    async def _do_work(self) -> WorkCycleResult:
        t0 = time.perf_counter()
        await self._reconcile_closed_escalations()
        runs = await self._fetch_recent_runs()
        if len(runs) < _MIN_HISTORY:
            return {"status": "warmup", "runs_seen": len(runs)}

        self._state.set_rc_budget_duration_history([
            {"run_id": int(r.get("databaseId", 0)),
             "created_at": str(r.get("createdAt", "")),
             "duration_s": int(r["duration_s"]),
             "conclusion": str(r.get("conclusion", ""))}
            for r in runs
        ])

        current, baselines = self._compute_baselines(runs)
        signals = self._check_signals(current, baselines)

        filed = 0
        escalated = 0
        dedup = set(self._dedup.get())
        previous_5 = [r for r in runs if r is not current][:5]
        jobs: list[dict[str, Any]] = []
        junit_tests: list[tuple[str, float]] = []
        if signals:
            jobs = await self._fetch_job_breakdown(current)
            junit_tests = await self._fetch_junit_tests(current)

        for kind, baseline_s in signals:
            key = f"rc_budget:{kind}"
            if key in dedup:
                continue
            attempts = self._state.inc_rc_budget_attempts(kind)
            if attempts >= _MAX_ATTEMPTS:
                await self._file_escalation(kind, attempts)
                escalated += 1
            else:
                await self._file_regression_issue(
                    kind=kind, current=current, baseline_s=baseline_s,
                    baselines=baselines, previous_5=previous_5,
                    jobs=jobs, junit_tests=junit_tests,
                )
                filed += 1
            dedup.add(key)
            self._dedup.set_all(dedup)

        self._emit_trace(t0, runs_seen=len(runs), signals=len(signals))
        return {
            "status": "ok", "runs_seen": len(runs),
            "filed": filed, "escalated": escalated,
            "current_duration_s": int(current["duration_s"]),
            "rolling_median_s": baselines["rolling_median"],
            "recent_max_s": baselines["recent_max"],
        }

    def _check_signals(
        self, current: dict[str, Any], baselines: dict[str, int]
    ) -> list[tuple[str, int]]:
        """Return ``[(kind, baseline_s), ...]`` where kind ∈ {median, spike}.

        Spec §4.8 + sibling plan: ``>=`` comparison.
        """
        cfg = self._config
        cur = int(current["duration_s"])
        hits: list[tuple[str, int]] = []
        m, r = baselines["rolling_median"], baselines["recent_max"]
        if m > 0 and cur >= cfg.rc_budget_threshold_ratio * m:
            hits.append(("median", m))
        if r > 0 and cur >= cfg.rc_budget_spike_ratio * r:
            hits.append(("spike", r))
        return hits

    async def _fetch_job_breakdown(
        self, run: dict[str, Any]
    ) -> list[dict[str, Any]]:
        run_id = str(run.get("databaseId", ""))
        if not run_id:
            return []
        cmd = ["gh", "run", "view", run_id,
               "--repo", self._config.repo, "--json", "jobs"]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            return []
        try:
            payload = json.loads(stdout.decode() or "{}")
        except json.JSONDecodeError:
            return []
        out: list[dict[str, Any]] = []
        for job in payload.get("jobs") or []:
            s, c = _parse_iso(job.get("startedAt")), _parse_iso(job.get("completedAt"))
            if not s or not c:
                continue
            out.append({"name": job.get("name", "?"),
                        "duration_s": max(0, int((c - s).total_seconds()))})
        out.sort(key=lambda j: j["duration_s"], reverse=True)
        return out[:10]

    async def _fetch_junit_tests(
        self, run: dict[str, Any]
    ) -> list[tuple[str, float]]:
        run_id = str(run.get("databaseId", ""))
        if not run_id:
            return []
        with tempfile.TemporaryDirectory() as td:
            cmd = ["gh", "run", "download", run_id,
                   "--repo", self._config.repo,
                   "--name", "junit-scenario", "--dir", td]
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            if proc.returncode != 0:
                return []
            results: list[tuple[str, float]] = []
            for xml_path in Path(td).rglob("*.xml"):
                try:
                    root = ET.fromstring(xml_path.read_bytes())
                except ET.ParseError:
                    continue
                for case in root.iter("testcase"):
                    cls = case.get("classname") or ""
                    name = case.get("name") or ""
                    test_id = f"{cls}.{name}".lstrip(".")
                    try:
                        dur = float(case.get("time") or 0.0)
                    except ValueError:
                        dur = 0.0
                    results.append((test_id, dur))
        results.sort(key=lambda t: t[1], reverse=True)
        return results[:10]

    async def _file_regression_issue(
        self, *, kind: str, current: dict[str, Any], baseline_s: int,
        baselines: dict[str, int], previous_5: list[dict[str, Any]],
        jobs: list[dict[str, Any]], junit_tests: list[tuple[str, float]],
    ) -> int:
        cfg = self._config
        cur = int(current["duration_s"])
        title = (
            f"RC gate duration regression: {cur}s vs {baseline_s}s "
            f"({'spike' if kind == 'spike' else 'median'})"
        )
        job_lines = "\n".join(
            f"- `{j['name']}` — {j['duration_s']}s" for j in jobs
        ) or "_(job breakdown unavailable)_"
        test_lines = "\n".join(
            f"- `{t}` — {d:.2f}s" for t, d in junit_tests
        ) or "_(junit-scenario artifact absent — top-10 tests elided)_"
        prev_lines = "\n".join(
            f"- run {r.get('databaseId', '?')} "
            f"({r.get('createdAt', '?')}) — {int(r['duration_s'])}s"
            for r in previous_5
        )
        body = (
            f"## RC wall-clock regression (signal: `{kind}`)\n\n"
            f"Run [{current.get('databaseId', '?')}]({current.get('url', '')}) "
            f"took **{cur}s**. Trips `{kind}`:\n\n"
            f"- Current: **{cur}s**\n"
            f"- Rolling 30d median: **{baselines['rolling_median']}s** "
            f"(threshold_ratio `{cfg.rc_budget_threshold_ratio}` → fires at "
            f"`{int(cfg.rc_budget_threshold_ratio * baselines['rolling_median'])}s`)\n"
            f"- Max of recent 5 (excl. current): **{baselines['recent_max']}s** "
            f"(spike_ratio `{cfg.rc_budget_spike_ratio}` → fires at "
            f"`{int(cfg.rc_budget_spike_ratio * baselines['recent_max'])}s`)\n\n"
            f"### Previous 5 runs\n{prev_lines}\n\n"
            f"### Per-job breakdown (top 10)\n{job_lines}\n\n"
            f"### Top-10 slowest tests\n{test_lines}\n\n"
            f"_Auto-filed by HydraFlow `rc_budget` (spec §4.8). "
            f"Escalates after 3 unresolved attempts._"
        )
        return await self._pr.create_issue(
            title, body, ["hydraflow-find", "rc-duration-regression"]
        )

    async def _file_escalation(self, kind: str, attempts: int) -> int:
        title = (
            f"HITL: RC gate duration regression ({kind}) unresolved after "
            f"{attempts} attempts"
        )
        body = (
            f"`rc_budget` filed `rc-duration-regression` for `{kind}` "
            f"{attempts} times without closure. Close this to clear the "
            f"`rc_budget:{kind}` dedup key (spec §3.2)."
        )
        return await self._pr.create_issue(
            title, body, ["hitl-escalation", "rc-duration-stuck"]
        )

    async def _reconcile_closed_escalations(self) -> None:
        cmd = [
            "gh", "issue", "list", "--repo", self._config.repo,
            "--state", "closed",
            "--label", "hitl-escalation", "--label", "rc-duration-stuck",
            "--author", "@me", "--limit", "100", "--json", "title",
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            return
        try:
            closed = json.loads(stdout.decode() or "[]")
        except json.JSONDecodeError:
            return
        current = self._dedup.get()
        keep = set(current)
        for issue in closed:
            title = issue.get("title", "")
            for kind in ("median", "spike"):
                key = f"rc_budget:{kind}"
                if key in keep and f"({kind})" in title:
                    keep.discard(key)
                    self._state.clear_rc_budget_attempts(kind)
        if keep != current:
            self._dedup.set_all(keep)

    def _emit_trace(self, t0: float, *, runs_seen: int, signals: int) -> None:
        try:
            from trace_collector import emit_loop_subprocess_trace  # noqa: PLC0415
        except ImportError:
            return
        emit_loop_subprocess_trace(
            worker_name=self._worker_name,
            command=["gh", "run", "list", _WORKFLOW],
            exit_code=0, duration_s=time.perf_counter() - t0,
            stdout_tail=f"runs_seen={runs_seen} signals={signals}",
            stderr_tail="",
        )
```

- [ ] **Step 4: Re-run — expect all PASS.**
- [ ] **Step 5: Commit:** `git add src/rc_budget_loop.py tests/test_rc_budget_loop.py && git commit -m "feat(loop): RCBudget signals + filing + escalation + reconcile (§4.8)"`

---

## Task 6 — Kill-switch + both-signal integration tests

- [ ] **Step 1: Append failing tests:**

```python
async def test_kill_switch_short_circuits_run(loop_env) -> None:
    cfg, state, pr, dedup = loop_env
    stop = asyncio.Event()
    deps = LoopDeps(
        event_bus=EventBus(), stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda name: name != "rc_budget",
    )
    loop = RCBudgetLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=deps
    )
    # Belt + braces: a guarded _do_work must not be entered by the dispatcher.
    loop._fetch_recent_runs = AsyncMock(side_effect=AssertionError("must not run"))
    # Drive one cycle via the public run loop; tick the stop event after.
    async def driver():
        await asyncio.sleep(0.01)
        stop.set()
    await asyncio.gather(loop.run(), driver())
    pr.create_issue.assert_not_awaited()


async def test_both_signals_fire_concurrently(loop_env) -> None:
    loop = _loop(loop_env)
    # median=300, recent_max=320, current=1000 → both trip.
    runs = [
        {"databaseId": 99, "duration_s": 1000,
         "createdAt": "2026-04-20T00:00:00Z",
         "conclusion": "success", "url": "u"},
        *[
            {"databaseId": i, "duration_s": (300 if i != 5 else 320),
             "createdAt": f"2026-04-{10 + i:02d}T00:00:00Z",
             "conclusion": "success", "url": f"u{i}"}
            for i in range(1, 7)
        ],
    ]
    loop._fetch_recent_runs = AsyncMock(return_value=runs)
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    loop._fetch_job_breakdown = AsyncMock(return_value=[])
    loop._fetch_junit_tests = AsyncMock(return_value=[])
    stats = await loop._do_work()
    assert stats["filed"] == 2
    _, _, _, dedup = loop_env
    assert dedup.set_all.call_count == 2
```

**Note:** spot-check `src/base_background_loop.py:95-120` during execution — if the dispatch loop exposes a single-step entry point (e.g. `tick()`), prefer it; the `run()`+`stop_event` pattern above is the public-API fallback.

- [ ] **Step 2: Run — expect PASS** (no source edits; kill-switch is `BaseBackgroundLoop` behavior, both-signal is Task 5 logic).
- [ ] **Step 3: Commit:** `git add tests/test_rc_budget_loop.py && git commit -m "test(loop): RCBudget kill-switch + both-signal integration (§3.2 + §4.8)"`

---

## Task 7 — Five-checkpoint wiring

One task, five sub-steps. The worker string `rc_budget` must be verbatim across all five sites — `test_loop_wiring_completeness.py` matches exactly.

- [ ] **Step 1: `src/service_registry.py`**

  - `:63` — add `from rc_budget_loop import RCBudgetLoop  # noqa: TCH001` near `from retrospective_loop ...`.
  - `:168` area — append dataclass field `rc_budget_loop: RCBudgetLoop`.
  - `:813` — after the `retrospective_loop = RetrospectiveLoop(...)` block, insert:

    ```python
    rc_budget_dedup = DedupStore(
        "rc_budget", config.data_root / "dedup" / "rc_budget.json",
    )
    rc_budget_loop = RCBudgetLoop(  # noqa: F841
        config=config, state=state, pr_manager=prs,
        dedup=rc_budget_dedup, deps=loop_deps,
    )
    ```

  - `:871` — append `rc_budget_loop=rc_budget_loop,` inside the `return ServiceRegistry(...)` call.

- [ ] **Step 2: `src/orchestrator.py`**

  - `:158` — append `"rc_budget": svc.rc_budget_loop,` to `bg_loop_registry`.
  - `:909` — append `("rc_budget", self._svc.rc_budget_loop.run),` to `loop_factories`.

- [ ] **Step 3: `src/ui/src/constants.js`**

  - `:252` — append `'rc_budget'` to the `EDITABLE_INTERVAL_WORKERS` Set.
  - `:273` — append `rc_budget: 14400,` to `SYSTEM_WORKER_INTERVALS`.
  - `:312` — append to `BACKGROUND_WORKERS`:

    ```js
    { key: 'rc_budget', label: 'RC Budget', description: 'Detects RC CI wall-clock bloat via rolling-median + spike-vs-recent-max signals; files hydraflow-find issues.', color: theme.orange, group: 'repo_health', tags: ['quality'] },
    ```

- [ ] **Step 4: `src/dashboard_routes/_common.py`**

  - `:55` — append `"rc_budget": (3600, 604800),` to `_INTERVAL_BOUNDS`.

- [ ] **Step 5: Verify + commit:**

  ```bash
  PYTHONPATH=src uv run pytest tests/test_loop_wiring_completeness.py -v
  git add src/service_registry.py src/orchestrator.py src/ui/src/constants.js src/dashboard_routes/_common.py
  git commit -m "feat(wiring): RCBudgetLoop five-checkpoint registration (§4.8)"
  ```

  Expected: all five wiring classes green.

---

## Task 8 — Loop-wiring-completeness confirmation

Regex discovery in `tests/test_loop_wiring_completeness.py` auto-matches `worker_name = "rc_budget"` — no edit required.

- [ ] **Step 1: Confirm:** `PYTHONPATH=src uv run pytest tests/test_loop_wiring_completeness.py -v` — expect PASS.
- [ ] **Step 2: Spot-check:** `grep -n "rc_budget" src/orchestrator.py src/service_registry.py src/dashboard_routes/_common.py src/ui/src/constants.js` — expect multiple hits across all four.

No commit — nothing changed.

---

## Task 9 — MockWorld scenario

**Modify** `tests/scenarios/catalog/loop_registrations.py` — above `_BUILDERS` (~line 233), insert:

```python
def _build_rc_budget(ports: dict[str, Any], config: Any, deps: Any) -> Any:
    from rc_budget_loop import RCBudgetLoop  # noqa: PLC0415

    state = ports.get("rc_budget_state") or MagicMock()
    dedup = ports.get("rc_budget_dedup") or MagicMock()
    ports.setdefault("rc_budget_state", state)
    ports.setdefault("rc_budget_dedup", dedup)
    return RCBudgetLoop(
        config=config, state=state, pr_manager=ports["github"],
        dedup=dedup, deps=deps,
    )
```

Then at `:257` append `"rc_budget": _build_rc_budget,` to `_BUILDERS`. **Modify** `tests/scenarios/catalog/test_loop_instantiation.py:22` and `tests/scenarios/catalog/test_loop_registrations.py:22` — append `"rc_budget",` to each coverage list.

**Create** `tests/scenarios/test_rc_budget_scenario.py`:

```python
"""Scenario: RCBudgetLoop fires on a synthetic 30d history with a spike."""

from __future__ import annotations

import asyncio as _asyncio
import datetime as _dt
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.loop_port_seeding import seed_ports as _seed_ports

pytestmark = pytest.mark.scenario_loops


class _FakeProc:
    def __init__(self, stdout: bytes, exit_code: int = 0) -> None:
        self._stdout = stdout
        self.returncode = exit_code

    async def communicate(self):
        return self._stdout, b""


def _make_runs_payload() -> bytes:
    now = _dt.datetime(2026, 4, 22, 12, 0, 0, tzinfo=_dt.UTC)
    runs = []
    for i in range(29, 0, -1):
        started = now - _dt.timedelta(days=i)
        updated = started + _dt.timedelta(seconds=300)
        runs.append({
            "databaseId": 1000 + i, "url": f"https://e/{1000 + i}",
            "conclusion": "success",
            "createdAt": started.isoformat().replace("+00:00", "Z"),
            "startedAt": started.isoformat().replace("+00:00", "Z"),
            "updatedAt": updated.isoformat().replace("+00:00", "Z"),
        })
    # Spike.
    updated = now + _dt.timedelta(seconds=900)
    runs.append({
        "databaseId": 2000, "url": "https://e/2000",
        "conclusion": "success",
        "createdAt": now.isoformat().replace("+00:00", "Z"),
        "startedAt": now.isoformat().replace("+00:00", "Z"),
        "updatedAt": updated.isoformat().replace("+00:00", "Z"),
    })
    runs.sort(key=lambda r: r["createdAt"], reverse=True)
    return json.dumps(runs).encode()


class TestRCBudgetScenario:
    async def test_rc_budget_fires_on_spike(self, tmp_path, monkeypatch) -> None:
        world = MockWorld(tmp_path)

        fake_state = MagicMock()
        fake_state.get_rc_budget_duration_history.return_value = []
        fake_state.get_rc_budget_attempts.return_value = 0
        fake_state.inc_rc_budget_attempts.return_value = 1

        fake_dedup = MagicMock()
        fake_dedup.get.return_value = set()

        fake_github = AsyncMock()
        fake_github.create_issue = AsyncMock(return_value=42)

        _seed_ports(
            world, github=fake_github,
            rc_budget_state=fake_state, rc_budget_dedup=fake_dedup,
        )

        runs_payload = _make_runs_payload()

        async def fake_subproc(*args, **kwargs):
            argv = args
            if "issue" in argv and "list" in argv:
                return _FakeProc(b"[]")
            if "run" in argv and "list" in argv:
                return _FakeProc(runs_payload)
            if "run" in argv and "view" in argv:
                return _FakeProc(b'{"jobs": []}')
            if "run" in argv and "download" in argv:
                return _FakeProc(b"", exit_code=1)  # artifact absent
            return _FakeProc(b"[]")

        monkeypatch.setattr(_asyncio, "create_subprocess_exec", fake_subproc)

        stats = await world.run_with_loops(["rc_budget"], cycles=1)

        assert stats["rc_budget"]["filed"] >= 1, stats
        assert fake_github.create_issue.await_count >= 1
        labels = fake_github.create_issue.await_args.args[2]
        assert "hydraflow-find" in labels
        assert "rc-duration-regression" in labels
```

- [ ] **Step 1: Run:**

  ```bash
  PYTHONPATH=src uv run pytest tests/scenarios/test_rc_budget_scenario.py tests/scenarios/catalog/ -v
  ```

  Expected: PASS across scenario + catalog coverage.

- [ ] **Step 2: Commit:**

  ```bash
  git add tests/scenarios/catalog/loop_registrations.py tests/scenarios/catalog/test_loop_instantiation.py tests/scenarios/catalog/test_loop_registrations.py tests/scenarios/test_rc_budget_scenario.py
  git commit -m "test(scenarios): RCBudget scenario + catalog registration (§4.8)"
  ```

---

## Task 10 — Final verification + PR

- [ ] **Step 1:** `make quality` — hard gate per `docs/agents/quality-gates.md`. Fix anything red.

- [ ] **Step 2:** `git push -u origin trust-arch-hardening`

- [ ] **Step 3:**

  ```bash
  gh pr create --title "feat(loop): RCBudgetLoop — RC CI wall-clock regression detector (§4.8)" --body "$(cat <<'EOF'
## Summary

- New `RCBudgetLoop` (`src/rc_budget_loop.py`) — 4h `BaseBackgroundLoop` reading 30d of `rc-promotion-scenario.yml` runs via `gh run list`; files `hydraflow-find` + `rc-duration-regression` on either signal:
  - Gradual: `current_s >= rc_budget_threshold_ratio * rolling_median` (default `1.5`).
  - Spike: `current_s >= rc_budget_spike_ratio * max(recent-5 excl. current)` (default `2.0`).
- 3-attempt escalation → `hitl-escalation` + `rc-duration-stuck`, with dedup-clear on close (§3.2).
- Kill-switch via `LoopDeps.enabled_cb("rc_budget")` — no `rc_budget_enabled` config field (§12.2).
- State mixin `RCBudgetStateMixin` + two `StateData` fields.
- Config fields + env overrides (`HYDRAFLOW_RC_BUDGET_INTERVAL` / `..._THRESHOLD_RATIO` / `..._SPIKE_RATIO`).
- Five-checkpoint wiring; loop-wiring-completeness test auto-covers.
- One MockWorld scenario + scenario-catalog builder.

## Spec

`docs/superpowers/specs/2026-04-22-trust-architecture-hardening-design.md` §4.8 / §3.2 / §12.2.

## Test plan

- [ ] `PYTHONPATH=src uv run pytest tests/test_state_rc_budget.py -v`
- [ ] `PYTHONPATH=src uv run pytest tests/test_config_rc_budget.py -v`
- [ ] `PYTHONPATH=src uv run pytest tests/test_rc_budget_loop.py -v`
- [ ] `PYTHONPATH=src uv run pytest tests/test_loop_wiring_completeness.py -v`
- [ ] `PYTHONPATH=src uv run pytest tests/scenarios/test_rc_budget_scenario.py tests/scenarios/catalog/ -v`
- [ ] `make quality`

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
  ```

Return the PR URL to the user.

---

## Appendix — quick reference

| Decision | Value | Source |
|---|---|---|
| Worker name | `rc_budget` | Spec §12.2 |
| Interval | `14400s` (4h), bounds `3600–604800` | Spec §4.8 |
| Gradual ratio | `1.5`, bounds `1.0–5.0` | Spec §4.8 |
| Spike ratio | `2.0`, bounds `1.0–10.0` | Spec §4.8 |
| Comparison | `>=` | Sibling plan |
| Dedup keys | `rc_budget:median`, `rc_budget:spike` | Sibling plan format |
| Escalation labels | `hitl-escalation`, `rc-duration-stuck` | Spec §4.8 |
| Regression labels | `hydraflow-find`, `rc-duration-regression` | Spec §4.8 |
| History cap | 60 | This plan §11 |
| Min history | 5 (else warmup) | This plan §10 |
| Recent-N | 5 | Spec §4.8 |
| Workflow | `rc-promotion-scenario.yml` | This plan §6 |
| Telemetry | `emit_loop_subprocess_trace` lazy-import | Sibling plan |
| DedupStore clear | `set_all(remaining)` | Sibling plan |
