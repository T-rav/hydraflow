# Trust Fleet Sanity Loop — §12.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Land `TrustFleetSanityLoop` (spec §12.1) — the tenth loop in the trust fleet (the meta-observability loop). A 10-minute `BaseBackgroundLoop` subclass that watches the nine §4.1–§4.9 trust loops and files a `hitl-escalation` + `trust-loop-anomaly` issue *immediately* (one-attempt escalation — the anomaly IS the escalation) whenever any of five anomalies breach configured thresholds:

1. **issues-per-hour** — any loop files more than `loop_anomaly_issues_per_hour` issues in an hour.
2. **repair ratio** — any loop's `repair_failures_total / repair_successes_total` over 24h exceeds `loop_anomaly_repair_ratio`.
3. **tick-error ratio** — any loop's `ticks_errored / ticks_total` over 24h exceeds `loop_anomaly_tick_error_ratio`.
4. **staleness** — any enabled loop hasn't ticked in `> loop_anomaly_staleness_multiplier × interval`.
5. **cost spike** — any loop's current-day cost exceeds `loop_anomaly_cost_spike_ratio × 30-day-median` (reads from §4.11's per-loop cost endpoint — lazy-imported, gracefully disabled when absent).

Dead-man-switch: `HealthMonitorLoop` gains a per-tick staleness check for `trust_fleet_sanity`; when the sanity loop itself goes silent, HealthMonitor files a `hydraflow-find` + `sanity-loop-stalled` issue. The recursion terminates at human-in-the-loop — bounded meta-observability (spec §12.1 "Bounds of meta-observability").

Kill-switch via `LoopDeps.enabled_cb("trust_fleet_sanity")` per spec §3.2 / §12.2 — **no `trust_fleet_sanity_enabled` config field**.

**Architecture:** New `src/trust_fleet_sanity_loop.py`; new helper `src/trust_fleet_anomaly_detectors.py` (five pure detector functions factored out so unit tests exercise each without spinning up the loop); new state mixin `src/state/_trust_fleet_sanity.py` (per-anomaly-key dedup attempt counters + last-audit-run timestamps); six config fields (`trust_fleet_sanity_interval` + the five `loop_anomaly_*` thresholds) + env overrides; five-checkpoint wiring; one MockWorld scenario + catalog builder; HealthMonitor extension for dead-man-switch; `/api/trust/fleet` endpoint **schema docstring** (impl owned by Plan 6b).

**Spec refs:** `docs/superpowers/specs/2026-04-22-trust-architecture-hardening-design.md` §12.1, §12.2, §12.3, §12.4, §3.2.

**Sibling plan carries (locked from rc-budget-loop + wiki-rot-detector-loop):**

1. Lazy-import `trace_collector.emit_loop_subprocess_trace` via `try/except ImportError` (caretaker-fleet Plan 6 owns the module).
2. DedupStore clearance via `set_all(remaining)` — no `remove`/`discard` method (verified `src/dedup_store.py:55-65`).
3. Escalation key format `f"{worker_name}:{subject}"` → here `f"trust_fleet_sanity:{anomaly_kind}:{target_worker}"` (e.g. `trust_fleet_sanity:issues_per_hour:ci_monitor`).
4. Threshold comparisons use `>=`.
5. No `trust_fleet_sanity_enabled` config field — kill-switch through `LoopDeps.enabled_cb("trust_fleet_sanity")` only.

**Decisions locked (spec ambiguous or sanity-loop-specific):**

6. **One-attempt escalation.** Unlike sibling loops (3-attempt budget), the sanity loop files `hitl-escalation` + `trust-loop-anomaly` **on the first breach** — the anomaly *is* the escalation. Per-key attempt counter still exists (stored via state mixin) so the dedup-close reconcile can reset it, but the branch `attempts >= 1` → escalate. Rationale: spec §12.1 "files a `hitl-escalation` issue" (no retry language — anomalies are already a "second-order failure" worth waking an operator for).
7. **Metric sources** — the detector helpers read from three surfaces, all existing:
   - `events.EventBus.load_events_since(since)` — returns all `BACKGROUND_WORKER_STATUS` events persisted to `events.jsonl` within the window. Yields per-worker `status ∈ {"ok", "error"}` samples → `ticks_total`, `ticks_errored`, and (via details) `filed` / `repaired` / `failed` subfields.
   - `state.get_worker_heartbeats()` — returns `dict[worker_name, PersistedWorkerHeartbeat]` with `last_run` ISO string. Source for staleness.
   - `bg_worker_manager.worker_enabled` — the live enabled-state dict. Only enabled loops are eligible for staleness checks (a disabled loop not ticking is correct).
   - The cost-reader is **lazy**: tries to import `trust_fleet_cost_reader` (owned by §4.11 / Plan 6b). If absent, cost-spike check returns `(False, {"status": "cost_reader_unavailable"})` and emits a single-line INFO log. Not an error.
8. **Watched workers set** — exactly the nine names from spec §12.2: `corpus_learning`, `contract_refresh`, `staging_bisect`, `principles_audit`, `flake_tracker`, `skill_prompt_eval`, `fake_coverage_auditor`, `rc_budget`, `wiki_rot_detector`. Hard-coded list in `trust_fleet_anomaly_detectors.py` as `TRUST_LOOP_WORKERS: tuple[str, ...]`. Workers that don't exist yet (some land in sibling plans) are tolerated — missing heartbeats = "no data yet" = no anomaly fires. A new-loop-introduction PR adds its worker name here in its five-checkpoint-wiring task.
9. **Windows** — hourly (issues-per-hour) = last 3600s; daily (repair ratio, tick-error ratio, cost) = last 86400s. All computed relative to `datetime.now(UTC)` at tick entry. Staleness uses per-worker interval retrieved from `bg_worker_manager.get_interval(worker)` with a fallback of `86400` when the interval is unset (new / not-yet-registered loop → conservative: don't flag).
10. **Zero-denominator handling.** Every ratio detector guards against `0` denominators by returning `(False, {"status": "insufficient_data", "total": 0})`. No division-by-zero, no false alarm on a fresh install.
11. **Counter-field shape in event details.** Each sibling loop's `_do_work` already returns a `WorkCycleResult` dict; the sanity loop reads specific keys conventionally: `filed` (int, issues filed this tick), `repaired` (int, repair success count — optional), `failed` (int, repair failure count — optional). Missing keys count as zero. Sibling loops that want to be observed for the repair-ratio detector must start emitting `repaired`/`failed` in their cycle-result dicts; the sanity loop's detector tolerates absence gracefully. A doc-comment lists the convention for sibling authors.
12. **Issue title format** = `f"HITL: trust-loop anomaly — {worker} {kind}"` — dedup key `f"trust_fleet_sanity:{kind}:{worker}"`.
13. **Close-reconcile** polls `gh issue list --state closed --label hitl-escalation --label trust-loop-anomaly --author @me --limit 200 --json title`. For each closed title, regex-extract the trailing `{worker} {kind}` pair, build `trust_fleet_sanity:{kind}:{worker}`, drop from dedup, reset attempts. Called at the top of each tick (no separate cron — spec §3.2).
14. **Staleness gate** — only enabled loops can trigger the staleness anomaly. A disabled loop sitting silent is intentional (operator pulled the kill-switch). The detector reads `bg_worker_manager.worker_enabled.get(worker, True)` (default `True` matches BGWorkerManager's `is_enabled` semantics). The kill-switch sanity **itself** being disabled is covered by HealthMonitor's dead-man-switch (§12.1 "Bounds").
15. **HealthMonitor dead-man-switch** — add a new method `HealthMonitorLoop._check_sanity_loop_staleness()` called near the top of `_do_work()`. Reads `state.get_worker_heartbeats().get("trust_fleet_sanity")`; computes `elapsed = now - last_run`. If `elapsed >= 3 × config.trust_fleet_sanity_interval` **and** the sanity loop is marked enabled in `bg_workers.worker_enabled`, file a `hydraflow-find` + `sanity-loop-stalled` issue (deduped on title). 3× multiplier is distinct from the sanity loop's own `loop_anomaly_staleness_multiplier` — HealthMonitor's job is to catch *hard* silence, not flakiness. A single constant in `health_monitor_loop.py` (`_SANITY_STALL_MULTIPLIER = 3`).
16. **Endpoint schema** is documented in this plan (Task 9) as a Python docstring `src/trust_fleet_sanity_loop.py:FLEET_ENDPOINT_SCHEMA` (a module-level string constant). Plan 6b reads this constant when implementing `/api/trust/fleet`.
17. **No read-side endpoint in this plan.** The loop only *writes* (issues + state). `/api/trust/fleet` is a read endpoint that reads from `StateTracker` / `EventLog` / `prompt_telemetry` — Plan 6b owns the route.
18. **Tick cadence** `600s` (10 minutes). Bounds `60–3600` in both `_INTERVAL_BOUNDS` and the config `Field(...)`.

---

## File Structure

| File | Role | C/M |
|---|---|---|
| `src/models.py:1757` | Append three `StateData` fields: `trust_fleet_sanity_attempts: dict[str, int]` + `trust_fleet_sanity_last_run: str \| None` + `trust_fleet_sanity_last_seen_counts: dict[str, dict[str, int]]` | M |
| `src/state/_trust_fleet_sanity.py` | New `TrustFleetSanityStateMixin` — attempt getter/inc/clear, last-run setter/getter, per-worker cumulative-counter snapshot (for issues-per-hour rate baseline across ticks) | C |
| `src/state/__init__.py:28-46, 55-76` | Import mixin + append to `StateTracker` MRO (alphabetical position — after `TraceRunsMixin`) | M |
| `src/config.py:174` | Append six env-override rows: `trust_fleet_sanity_interval` + `loop_anomaly_issues_per_hour` + ratios/multipliers | M |
| `src/config.py:210` (float list) | Append four float env-override rows for the ratio/multiplier thresholds | M |
| `src/config.py:1619` | Six `HydraFlowConfig` fields after `retrospective_interval` | M |
| `src/trust_fleet_anomaly_detectors.py` | New helper — five detector functions + the `TRUST_LOOP_WORKERS` tuple + the cost-reader lazy loader + zero-guard primitives | C |
| `src/trust_fleet_sanity_loop.py` | New loop — tick: reconcile → collect metrics → run five detectors → file escalations. Plus module-level `FLEET_ENDPOINT_SCHEMA` constant | C |
| `src/health_monitor_loop.py:336` | Add `_check_sanity_loop_staleness()` call in `_do_work()`; define method elsewhere in the class; new constant `_SANITY_STALL_MULTIPLIER = 3` near other module constants | M |
| `src/service_registry.py:63` | Add `from trust_fleet_sanity_loop import TrustFleetSanityLoop  # noqa: TCH001` | M |
| `src/service_registry.py:168` | Append dataclass field `trust_fleet_sanity_loop: TrustFleetSanityLoop` | M |
| `src/service_registry.py:813` | After `retrospective_loop = RetrospectiveLoop(...)` block, insert dedup + loop construction | M |
| `src/service_registry.py:871` | Append `trust_fleet_sanity_loop=trust_fleet_sanity_loop,` to `ServiceRegistry(...)` | M |
| `src/orchestrator.py:158` | Append `"trust_fleet_sanity": svc.trust_fleet_sanity_loop,` to `bg_loop_registry` | M |
| `src/orchestrator.py:909` | Append `("trust_fleet_sanity", self._svc.trust_fleet_sanity_loop.run),` to `loop_factories` | M |
| `src/ui/src/constants.js:252` | Append `'trust_fleet_sanity'` to `EDITABLE_INTERVAL_WORKERS` | M |
| `src/ui/src/constants.js:273` | Append `trust_fleet_sanity: 600,` to `SYSTEM_WORKER_INTERVALS` | M |
| `src/ui/src/constants.js:312` | Append `BACKGROUND_WORKERS` entry | M |
| `src/dashboard_routes/_common.py:55` | Append `"trust_fleet_sanity": (60, 3600),` to `_INTERVAL_BOUNDS` | M |
| `tests/test_state_trust_fleet_sanity.py` | Mixin unit tests | C |
| `tests/test_trust_fleet_anomaly_detectors.py` | Five detector unit tests (one per detector) + edge cases | C |
| `tests/test_trust_fleet_sanity_loop.py` | Loop unit tests (skeleton, reconcile, kill-switch, filing, escalation, cost-reader-absent) | C |
| `tests/test_health_monitor_sanity_stall.py` | HealthMonitor dead-man-switch unit test | C |
| `tests/scenarios/catalog/loop_registrations.py:234` | `_build_trust_fleet_sanity` + `_BUILDERS` entry | M |
| `tests/scenarios/catalog/test_loop_instantiation.py:~30` | `"trust_fleet_sanity",` | M |
| `tests/scenarios/catalog/test_loop_registrations.py:~30` | `"trust_fleet_sanity",` | M |
| `tests/scenarios/test_trust_fleet_sanity_scenario.py` | MockWorld scenario — seed stale heartbeats + assert filing | C |
| `tests/test_loop_wiring_completeness.py` | Regex auto-discovery — no edit required | Covered |

---

## Task 1 — State schema (per-anomaly attempts + last-run + counter snapshots)

**Modify** `src/models.py:1757` — after `code_grooming_filed: list[str] = Field(default_factory=list)`, insert:

```python
    # Trust fleet — TrustFleetSanityLoop (spec §12.1)
    trust_fleet_sanity_attempts: dict[str, int] = Field(default_factory=dict)
    trust_fleet_sanity_last_run: str | None = None
    trust_fleet_sanity_last_seen_counts: dict[str, dict[str, int]] = Field(
        default_factory=dict,
    )
```

`trust_fleet_sanity_last_seen_counts` shape: `{worker_name: {"issues_filed_total": int, "observed_at": iso_string}}` — a cheap per-worker cumulative snapshot so the issues-per-hour detector can compute `delta / elapsed_hours` across ticks when the event log is unavailable. Fallback surface; primary is the event log.

**Modify** `src/state/__init__.py:28-46` — add `from ._trust_fleet_sanity import TrustFleetSanityStateMixin` in alphabetical position (after `TraceRunsMixin` import — `TrustFleet` sorts after `TraceRuns` alphabetically).

**Modify** `src/state/__init__.py:55-76` — append `TrustFleetSanityStateMixin,` to the `StateTracker` MRO after `TraceRunsMixin,`.

- [ ] **Step 1: Write failing mixin test** — `tests/test_state_trust_fleet_sanity.py`:

```python
"""Tests for TrustFleetSanityStateMixin (spec §12.1)."""

from __future__ import annotations

from pathlib import Path

from state import StateTracker


def _tracker(tmp_path: Path) -> StateTracker:
    return StateTracker(state_file=tmp_path / "state.json")


def test_get_returns_zero_when_unset(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    assert st.get_trust_fleet_sanity_attempts("issues_per_hour:ci_monitor") == 0


def test_inc_is_monotonic(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    key = "tick_error_ratio:rc_budget"
    assert st.inc_trust_fleet_sanity_attempts(key) == 1
    assert st.inc_trust_fleet_sanity_attempts(key) == 2
    assert st.get_trust_fleet_sanity_attempts("other:key") == 0


def test_clear_resets_single_key(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    st.inc_trust_fleet_sanity_attempts("a:one")
    st.inc_trust_fleet_sanity_attempts("b:two")
    st.clear_trust_fleet_sanity_attempts("a:one")
    assert st.get_trust_fleet_sanity_attempts("a:one") == 0
    assert st.get_trust_fleet_sanity_attempts("b:two") == 1


def test_last_run_roundtrips(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    assert st.get_trust_fleet_sanity_last_run() is None
    st.set_trust_fleet_sanity_last_run("2026-04-22T12:00:00+00:00")
    assert st.get_trust_fleet_sanity_last_run() == "2026-04-22T12:00:00+00:00"


def test_last_seen_counts_roundtrips(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    st.set_trust_fleet_sanity_last_seen_count(
        "ci_monitor", issues_filed_total=5, observed_at="2026-04-22T12:00:00+00:00",
    )
    snap = st.get_trust_fleet_sanity_last_seen_counts()
    assert snap["ci_monitor"]["issues_filed_total"] == 5
    assert snap["ci_monitor"]["observed_at"] == "2026-04-22T12:00:00+00:00"


def test_persists_across_instances(tmp_path: Path) -> None:
    st1 = _tracker(tmp_path)
    st1.inc_trust_fleet_sanity_attempts("persist:key")
    st2 = _tracker(tmp_path)
    assert st2.get_trust_fleet_sanity_attempts("persist:key") == 1
```

- [ ] **Step 2: Run — expect FAIL** (`AttributeError`):

  ```bash
  PYTHONPATH=src uv run pytest tests/test_state_trust_fleet_sanity.py -v
  ```

- [ ] **Step 3: Create** `src/state/_trust_fleet_sanity.py`:

```python
"""State accessors for TrustFleetSanityLoop (spec §12.1).

Three fields:

- ``trust_fleet_sanity_attempts``: ``dict[str, int]`` — per-anomaly-key
  repair-attempt counter. Key format ``f"{kind}:{worker}"``. The
  sanity loop uses a 1-attempt escalation (anomaly IS the escalation),
  but the counter surface is preserved so the close-reconcile can
  reset it and so future policy can raise the bar without a schema
  migration.
- ``trust_fleet_sanity_last_run``: ISO timestamp of the most-recent
  successful tick. Used by the HealthMonitor dead-man-switch.
- ``trust_fleet_sanity_last_seen_counts``: per-worker cumulative
  counter snapshot (``issues_filed_total``) + observation timestamp.
  Fallback source for the issues-per-hour detector when the event log
  is unavailable (e.g. a fresh install with no persisted events yet).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import StateData


class TrustFleetSanityStateMixin:
    """State for `TrustFleetSanityLoop` (spec §12.1)."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    # --- per-anomaly attempt counters ---

    def get_trust_fleet_sanity_attempts(self, key: str) -> int:
        return int(self._data.trust_fleet_sanity_attempts.get(key, 0))

    def inc_trust_fleet_sanity_attempts(self, key: str) -> int:
        current = int(self._data.trust_fleet_sanity_attempts.get(key, 0)) + 1
        attempts = dict(self._data.trust_fleet_sanity_attempts)
        attempts[key] = current
        self._data.trust_fleet_sanity_attempts = attempts
        self.save()
        return current

    def clear_trust_fleet_sanity_attempts(self, key: str) -> None:
        attempts = dict(self._data.trust_fleet_sanity_attempts)
        attempts.pop(key, None)
        self._data.trust_fleet_sanity_attempts = attempts
        self.save()

    # --- last successful tick (for HealthMonitor dead-man-switch) ---

    def get_trust_fleet_sanity_last_run(self) -> str | None:
        return self._data.trust_fleet_sanity_last_run

    def set_trust_fleet_sanity_last_run(self, iso: str) -> None:
        self._data.trust_fleet_sanity_last_run = iso
        self.save()

    # --- per-worker counter snapshots (fallback for issues-per-hour) ---

    def get_trust_fleet_sanity_last_seen_counts(self) -> dict[str, dict[str, int]]:
        return {
            name: dict(entry)
            for name, entry in self._data.trust_fleet_sanity_last_seen_counts.items()
        }

    def set_trust_fleet_sanity_last_seen_count(
        self, worker: str, *, issues_filed_total: int, observed_at: str,
    ) -> None:
        snap = dict(self._data.trust_fleet_sanity_last_seen_counts)
        snap[worker] = {
            "issues_filed_total": int(issues_filed_total),
            "observed_at": observed_at,
        }
        self._data.trust_fleet_sanity_last_seen_counts = snap
        self.save()
```

- [ ] **Step 4: Apply `models.py` + `state/__init__.py` edits (above).**
- [ ] **Step 5: Re-run — expect 6 PASS.**
- [ ] **Step 6: Commit:**

  ```bash
  git add src/models.py src/state/_trust_fleet_sanity.py src/state/__init__.py tests/test_state_trust_fleet_sanity.py
  git commit -m "feat(state): TrustFleetSanityStateMixin + three StateData fields (§12.1)"
  ```

---

## Task 2 — Config fields + env overrides

**Modify** `src/config.py:174` — after the `retrospective_interval` int-override row, append:

```python
    ("trust_fleet_sanity_interval", "HYDRAFLOW_TRUST_FLEET_SANITY_INTERVAL", 600),
    ("loop_anomaly_issues_per_hour", "HYDRAFLOW_LOOP_ANOMALY_ISSUES_PER_HOUR", 10),
```

**Modify** `src/config.py:210` (the `_ENV_FLOAT_OVERRIDES` list) — append four float rows:

```python
    ("loop_anomaly_repair_ratio", "HYDRAFLOW_LOOP_ANOMALY_REPAIR_RATIO", 2.0),
    ("loop_anomaly_tick_error_ratio", "HYDRAFLOW_LOOP_ANOMALY_TICK_ERROR_RATIO", 0.2),
    ("loop_anomaly_staleness_multiplier", "HYDRAFLOW_LOOP_ANOMALY_STALENESS_MULTIPLIER", 2.0),
    ("loop_anomaly_cost_spike_ratio", "HYDRAFLOW_LOOP_ANOMALY_COST_SPIKE_RATIO", 5.0),
```

**Modify** `src/config.py:1619` — after the closing `)` of `retrospective_interval`'s field definition, insert:

```python

    # Trust fleet — TrustFleetSanityLoop (spec §12.1)
    trust_fleet_sanity_interval: int = Field(
        default=600,
        ge=60,
        le=3600,
        description="Seconds between TrustFleetSanityLoop ticks (default 10m)",
    )
    loop_anomaly_issues_per_hour: int = Field(
        default=10,
        ge=1,
        le=1000,
        description=(
            "TrustFleetSanityLoop: files an escalation when any watched loop "
            "exceeds this many issues/hour (spec §12.1)."
        ),
    )
    loop_anomaly_repair_ratio: float = Field(
        default=2.0,
        ge=0.1,
        le=100.0,
        description=(
            "TrustFleetSanityLoop: `repair_failures_total / repair_successes_total` "
            "over 24h breach threshold (spec §12.1)."
        ),
    )
    loop_anomaly_tick_error_ratio: float = Field(
        default=0.2,
        ge=0.01,
        le=1.0,
        description=(
            "TrustFleetSanityLoop: `ticks_errored / ticks_total` over 24h "
            "breach threshold (spec §12.1)."
        ),
    )
    loop_anomaly_staleness_multiplier: float = Field(
        default=2.0,
        ge=1.0,
        le=100.0,
        description=(
            "TrustFleetSanityLoop: staleness breach when an enabled loop has not "
            "ticked in > this × its interval (spec §12.1)."
        ),
    )
    loop_anomaly_cost_spike_ratio: float = Field(
        default=5.0,
        ge=1.0,
        le=100.0,
        description=(
            "TrustFleetSanityLoop: current-day cost breach when > this × "
            "30-day median (spec §12.1; reads §4.11 cost endpoint, tolerates absence)."
        ),
    )
```

- [ ] **Step 1: Write failing test** — `tests/test_config_trust_fleet_sanity.py`:

```python
"""Tests for TrustFleetSanityLoop config fields + env overrides (spec §12.1)."""

from __future__ import annotations

import pytest

from config import HydraFlowConfig


def test_default_values() -> None:
    cfg = HydraFlowConfig()
    assert cfg.trust_fleet_sanity_interval == 600
    assert cfg.loop_anomaly_issues_per_hour == 10
    assert cfg.loop_anomaly_repair_ratio == 2.0
    assert cfg.loop_anomaly_tick_error_ratio == 0.2
    assert cfg.loop_anomaly_staleness_multiplier == 2.0
    assert cfg.loop_anomaly_cost_spike_ratio == 5.0


def test_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("HYDRAFLOW_TRUST_FLEET_SANITY_INTERVAL", "900")
    monkeypatch.setenv("HYDRAFLOW_LOOP_ANOMALY_ISSUES_PER_HOUR", "25")
    monkeypatch.setenv("HYDRAFLOW_LOOP_ANOMALY_REPAIR_RATIO", "3.5")
    monkeypatch.setenv("HYDRAFLOW_LOOP_ANOMALY_TICK_ERROR_RATIO", "0.5")
    monkeypatch.setenv("HYDRAFLOW_LOOP_ANOMALY_STALENESS_MULTIPLIER", "4.0")
    monkeypatch.setenv("HYDRAFLOW_LOOP_ANOMALY_COST_SPIKE_RATIO", "10.0")
    cfg = HydraFlowConfig()
    assert cfg.trust_fleet_sanity_interval == 900
    assert cfg.loop_anomaly_issues_per_hour == 25
    assert cfg.loop_anomaly_repair_ratio == 3.5
    assert cfg.loop_anomaly_tick_error_ratio == 0.5
    assert cfg.loop_anomaly_staleness_multiplier == 4.0
    assert cfg.loop_anomaly_cost_spike_ratio == 10.0


def test_interval_bounds() -> None:
    with pytest.raises(ValueError, match="greater than or equal to 60"):
        HydraFlowConfig(trust_fleet_sanity_interval=30)
    with pytest.raises(ValueError, match="less than or equal to 3600"):
        HydraFlowConfig(trust_fleet_sanity_interval=86400)


def test_tick_error_ratio_bounded_below_one() -> None:
    with pytest.raises(ValueError, match="less than or equal to 1"):
        HydraFlowConfig(loop_anomaly_tick_error_ratio=1.5)
```

- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Apply config.py edits (above).**
- [ ] **Step 4: Re-run — expect 4 PASS.**
- [ ] **Step 5: Commit:**

  ```bash
  git add src/config.py tests/test_config_trust_fleet_sanity.py
  git commit -m "feat(config): trust_fleet_sanity_interval + five loop_anomaly_* thresholds (§12.1)"
  ```

---

## Task 3 — Loop skeleton + tick stub

- [ ] **Step 1: Write failing test** — `tests/test_trust_fleet_sanity_loop.py`:

```python
"""Tests for TrustFleetSanityLoop (spec §12.1)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus
from trust_fleet_sanity_loop import TrustFleetSanityLoop


def _deps(stop: asyncio.Event, enabled: bool = True) -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: enabled,
    )


@pytest.fixture
def loop_env(tmp_path: Path):
    cfg = HydraFlowConfig(data_root=tmp_path, repo="hydra/hydraflow")
    state = MagicMock()
    state.get_trust_fleet_sanity_attempts.return_value = 0
    state.inc_trust_fleet_sanity_attempts.return_value = 1
    state.get_trust_fleet_sanity_last_run.return_value = None
    state.get_trust_fleet_sanity_last_seen_counts.return_value = {}
    state.get_worker_heartbeats.return_value = {}
    bg_workers = MagicMock()
    bg_workers.worker_enabled = {}
    bg_workers.get_interval.return_value = 600
    pr_manager = AsyncMock()
    pr_manager.create_issue = AsyncMock(return_value=42)
    dedup = MagicMock()
    dedup.get.return_value = set()
    bus = EventBus()
    return cfg, state, bg_workers, pr_manager, dedup, bus


def _loop(env, enabled: bool = True) -> TrustFleetSanityLoop:
    cfg, state, bg_workers, pr, dedup, bus = env
    deps = _deps(asyncio.Event(), enabled=enabled)
    # Override event_bus on deps — the same bus is passed explicitly for
    # metric reads via load_events_since.
    return TrustFleetSanityLoop(
        config=cfg,
        state=state,
        bg_workers=bg_workers,
        pr_manager=pr,
        dedup=dedup,
        event_bus=bus,
        deps=deps,
    )


def test_skeleton_worker_name_and_interval(loop_env) -> None:
    loop = _loop(loop_env)
    assert loop._worker_name == "trust_fleet_sanity"
    assert loop._get_default_interval() == 600


async def test_do_work_noop_when_no_metrics(loop_env) -> None:
    loop = _loop(loop_env)
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    stats = await loop._do_work()
    assert stats["status"] == "ok"
    assert stats["anomalies"] == 0
    _, _, _, pr, _, _ = loop_env
    pr.create_issue.assert_not_awaited()


async def test_kill_switch_short_circuits(loop_env) -> None:
    loop = _loop(loop_env, enabled=False)
    # The base class handles the kill-switch branch in `run()`; at the
    # `_do_work` level we expect the loop to still be callable but
    # short-circuit on the enabled check it makes defensively.
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    stats = await loop._do_work()
    assert stats["status"] == "disabled"
```

- [ ] **Step 2: Run — expect FAIL (`ImportError`).**

- [ ] **Step 3: Create** `src/trust_fleet_sanity_loop.py`:

```python
"""TrustFleetSanityLoop — meta-observability for the trust loop fleet (spec §12.1).

Watches the nine §4.1–§4.9 trust loops. On any of five anomaly
conditions (thresholds config-driven, operator-tunable), files a
``hitl-escalation`` issue with label ``trust-loop-anomaly``. One-attempt
escalation — the anomaly IS the escalation, not a repair attempt.

Dead-man-switch: ``HealthMonitorLoop`` watches *this* loop's
heartbeat; when the sanity loop itself stops ticking, HealthMonitor
files ``sanity-loop-stalled``. Recursion bounded at one meta-layer
(spec §12.1 "Bounds of meta-observability").

Kill-switch: ``LoopDeps.enabled_cb("trust_fleet_sanity")`` — **no
``trust_fleet_sanity_enabled`` config field** (spec §12.2).

Read-side surface is `/api/trust/fleet?range=7d|30d` — schema
documented in :data:`FLEET_ENDPOINT_SCHEMA` below. Route impl is owned
by Plan 6b (§4.11 factory-cost work).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from models import WorkCycleResult
from trust_fleet_anomaly_detectors import (
    TRUST_LOOP_WORKERS,
    detect_cost_spike,
    detect_issues_per_hour,
    detect_repair_ratio,
    detect_staleness,
    detect_tick_error_ratio,
)

if TYPE_CHECKING:
    from bg_worker_manager import BGWorkerManager
    from config import HydraFlowConfig
    from dedup_store import DedupStore
    from events import EventBus
    from pr_manager import PRManager
    from state import StateTracker

logger = logging.getLogger("hydraflow.trust_fleet_sanity_loop")


FLEET_ENDPOINT_SCHEMA: str = """
/api/trust/fleet response schema (spec §12.1; owned by Plan 6b).

Request: GET /api/trust/fleet?range=7d|30d

Response JSON:

{
  "range": "7d" | "30d",
  "generated_at": "<iso8601 UTC>",
  "loops": [
    {
      "worker_name": "<string>",         # e.g. "ci_monitor", "rc_budget"
      "enabled": <bool>,                  # from BGWorkerManager.is_enabled
      "interval_s": <int>,                # effective interval (dynamic or default)
      "last_tick_at": "<iso8601>" | null, # from worker_heartbeats
      "ticks_total": <int>,               # window-scoped count from event log
      "ticks_errored": <int>,             # status=="error" in the window
      "issues_filed_total": <int>,        # sum of details.filed over the window
      "issues_closed_total": <int>,       # sum from `EventType.ISSUE_CLOSED` events (best-effort; 0 if absent)
      "issues_open_escalated": <int>,     # currently-open issues the loop filed with hitl-escalation label
      "repair_attempts_total": <int>,     # sum of details.repaired + details.failed
      "repair_successes_total": <int>,    # sum of details.repaired
      "repair_failures_total": <int>,     # sum of details.failed
      "loop_specific": {                  # optional per-loop metrics; see §12.1 examples
        "reverts_merged": <int>,          # staging_bisect
        "cases_added": <int>,             # corpus_learning
        "cassettes_refreshed": <int>,     # contract_refresh
        "principles_regressions": <int>,  # principles_audit
        ...
      }
    },
    ...
  ],
  "anomalies_recent": [
    {
      "kind": "issues_per_hour" | "repair_ratio" | "tick_error_ratio"
            | "staleness" | "cost_spike",
      "worker": "<string>",
      "filed_at": "<iso8601>",
      "issue_number": <int>,
      "details": {<detector-specific>}
    }
  ]
}

Implementation notes for Plan 6b:
- Read `ticks_total`/`ticks_errored`/`issues_filed_total` by calling
  `event_bus.load_events_since(now - range)` and tallying
  `EventType.BACKGROUND_WORKER_STATUS` entries where `data.worker`
  matches each loop.
- Read `last_tick_at`/`enabled`/`interval_s` from
  `state.get_worker_heartbeats()` + `bg_workers.worker_enabled` +
  `bg_workers.get_interval`.
- `anomalies_recent` is populated from the last-24h `hitl-escalation`+
  `trust-loop-anomaly` issues authored by the bot (via `gh issue list`).
- Loop-specific metrics are loop-maintained counter fields TBD by each
  sibling loop; default `0` when unreported.
"""

_MAX_ATTEMPTS = 1  # spec §12.1 — the anomaly IS the escalation.
_HOUR_SECONDS = 3600
_DAY_SECONDS = 86_400
_ANOMALY_KINDS: tuple[str, ...] = (
    "issues_per_hour",
    "repair_ratio",
    "tick_error_ratio",
    "staleness",
    "cost_spike",
)

_TITLE_RE = re.compile(
    r"HITL: trust-loop anomaly — (?P<worker>[\w_]+) (?P<kind>[\w_]+)$",
)


class TrustFleetSanityLoop(BaseBackgroundLoop):
    """Meta-observability loop — watches the nine trust loops (spec §12.1)."""

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        state: StateTracker,
        bg_workers: BGWorkerManager,
        pr_manager: PRManager,
        dedup: DedupStore,
        event_bus: EventBus,
        deps: LoopDeps,
    ) -> None:
        super().__init__(
            worker_name="trust_fleet_sanity",
            config=config,
            deps=deps,
            run_on_startup=False,
        )
        self._state = state
        self._bg_workers = bg_workers
        self._pr = pr_manager
        self._dedup = dedup
        self._source_bus = event_bus  # separate handle for load_events_since

    def _get_default_interval(self) -> int:
        return self._config.trust_fleet_sanity_interval

    async def _do_work(self) -> WorkCycleResult:
        """Skeleton — Task 5 replaces with the full tick."""
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        await self._reconcile_closed_escalations()
        # Skeleton returns without running detectors (Task 5 fills this in).
        return {"status": "ok", "anomalies": 0}

    async def _reconcile_closed_escalations(self) -> None:
        """Task 5."""
        return None
```

- [ ] **Step 4: Re-run — expect 3 PASS.**
- [ ] **Step 5: Commit:**

  ```bash
  git add src/trust_fleet_sanity_loop.py tests/test_trust_fleet_sanity_loop.py
  git commit -m "feat(loop): TrustFleetSanityLoop skeleton + endpoint schema constant (§12.1)"
  ```

---

## Task 4 — Metrics-reader helpers (event log, heartbeats, lazy cost-reader)

This task introduces the read side of the loop — the functions that turn raw persistence / worker-manager state into per-worker metric dicts the detectors can consume. All pure functions (no side effects beyond logging), living on the loop class so Task 5 can call them directly.

- [ ] **Step 1: Append failing tests** to `tests/test_trust_fleet_sanity_loop.py`:

```python
from datetime import timedelta

from events import EventType, HydraFlowEvent
from models import BackgroundWorkerStatusPayload


def _make_status_event(worker: str, status: str, *, ago_s: int, filed: int = 0,
                       repaired: int = 0, failed: int = 0) -> HydraFlowEvent:
    ts = datetime.now(UTC) - timedelta(seconds=ago_s)
    return HydraFlowEvent(
        type=EventType.BACKGROUND_WORKER_STATUS,
        timestamp=ts.isoformat(),
        data=BackgroundWorkerStatusPayload(
            worker=worker,
            status=status,
            last_run=ts.isoformat(),
            details={"filed": filed, "repaired": repaired, "failed": failed},
        ),
    )


async def test_collect_window_metrics_tallies_events(loop_env) -> None:
    loop = _loop(loop_env)
    events = [
        _make_status_event("ci_monitor", "ok", ago_s=600, filed=2),
        _make_status_event("ci_monitor", "ok", ago_s=1800, filed=3),
        _make_status_event("ci_monitor", "error", ago_s=2400),
        _make_status_event("rc_budget", "ok", ago_s=300, repaired=1),
        # Outside daily window — must be excluded.
        _make_status_event("ci_monitor", "ok", ago_s=_DAY_SECONDS + 120, filed=99),
    ]
    _, _, _, _, _, bus = loop_env
    # Stub load_events_since to return our fabricated list.
    async def fake_load(since):  # noqa: ARG001
        return [e for e in events
                if datetime.fromisoformat(e.timestamp) >= since]
    bus.load_events_since = fake_load  # type: ignore[method-assign]
    metrics = await loop._collect_window_metrics()
    ci = metrics["ci_monitor"]
    assert ci["ticks_total"] == 3
    assert ci["ticks_errored"] == 1
    assert ci["issues_filed_day"] == 5
    assert ci["issues_filed_hour"] == 2  # only the 600s-ago event


def test_lazy_cost_reader_tolerates_missing_module(loop_env, monkeypatch) -> None:
    import sys
    loop = _loop(loop_env)
    monkeypatch.setitem(sys.modules, "trust_fleet_cost_reader", None)
    reader = loop._load_cost_reader()
    assert reader is None
```

(Note: the constant `_DAY_SECONDS` is imported at module top from `trust_fleet_sanity_loop` for the test to resolve.)

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Append helpers** to `TrustFleetSanityLoop`:

```python
    async def _collect_window_metrics(self) -> dict[str, dict[str, Any]]:
        """Walk the event log's last 24h and tally per-worker counters.

        Returns a dict keyed by worker_name → metric dict with:
        ``ticks_total``, ``ticks_errored``, ``issues_filed_day``,
        ``issues_filed_hour``, ``repaired_day``, ``failed_day``,
        ``last_seen_iso``.
        """
        now = datetime.now(UTC)
        day_cutoff = now - timedelta(seconds=_DAY_SECONDS)
        hour_cutoff = now - timedelta(seconds=_HOUR_SECONDS)

        events = await self._load_events_since(day_cutoff)

        out: dict[str, dict[str, Any]] = {
            w: {
                "ticks_total": 0,
                "ticks_errored": 0,
                "issues_filed_day": 0,
                "issues_filed_hour": 0,
                "repaired_day": 0,
                "failed_day": 0,
                "last_seen_iso": None,
            }
            for w in TRUST_LOOP_WORKERS
        }
        from events import EventType  # noqa: PLC0415

        for ev in events:
            if ev.type != EventType.BACKGROUND_WORKER_STATUS:
                continue
            data = getattr(ev, "data", {}) or {}
            worker = data.get("worker") if isinstance(data, dict) else None
            if worker not in out:
                continue
            ts_raw = getattr(ev, "timestamp", None)
            ts = _parse_iso(ts_raw) if isinstance(ts_raw, str) else None
            if ts is None or ts < day_cutoff:
                continue
            bucket = out[worker]
            bucket["ticks_total"] += 1
            if data.get("status") == "error":
                bucket["ticks_errored"] += 1
            details = data.get("details") or {}
            filed = int(details.get("filed", 0) or 0)
            bucket["issues_filed_day"] += filed
            if ts >= hour_cutoff:
                bucket["issues_filed_hour"] += filed
            bucket["repaired_day"] += int(details.get("repaired", 0) or 0)
            bucket["failed_day"] += int(details.get("failed", 0) or 0)
            seen = bucket["last_seen_iso"]
            if seen is None or ts_raw > seen:
                bucket["last_seen_iso"] = ts_raw
        return out

    async def _load_events_since(self, since: datetime) -> list[Any]:
        """Wrap ``EventBus.load_events_since`` with robust defaults.

        Returns ``[]`` when the bus has no ``event_log`` attached (tests
        often pass a vanilla ``EventBus()``).
        """
        try:
            loaded = await self._source_bus.load_events_since(since)
        except Exception:  # noqa: BLE001
            logger.debug("load_events_since failed", exc_info=True)
            return []
        return loaded or []

    def _load_cost_reader(self) -> Any | None:
        """Lazy-import the §4.11 cost reader.

        Returns the module object (which must expose
        ``get_loop_cost_today(worker) -> float`` and
        ``get_loop_cost_30d_median(worker) -> float``) or ``None`` if
        absent. Absence is not an error — Plan 6b lands the module.
        """
        try:
            import trust_fleet_cost_reader as module  # noqa: PLC0415
        except ImportError:
            logger.info(
                "trust_fleet_cost_reader unavailable — cost-spike detector disabled"
            )
            return None
        if module is None:
            return None
        return module
```

Prepend near the other module-level helpers (above `class TrustFleetSanityLoop`):

```python
def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
```

- [ ] **Step 4: Re-run — expect all PASS.**
- [ ] **Step 5: Commit:**

  ```bash
  git add src/trust_fleet_sanity_loop.py tests/test_trust_fleet_sanity_loop.py
  git commit -m "feat(loop): TrustFleetSanity metrics readers + lazy cost-reader (§12.1)"
  ```

---

## Task 5 — Five anomaly detectors (pure functions in a helper module)

Five detectors, each `(breached: bool, details: dict)`, each a pure function (no side effects, no subprocess) so tests are trivial and the loop class stays small. Factored into a new helper module for discoverability.

- [ ] **Step 1: Write failing tests** — `tests/test_trust_fleet_anomaly_detectors.py`:

```python
"""Unit tests — one per anomaly detector (spec §12.1)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from trust_fleet_anomaly_detectors import (
    TRUST_LOOP_WORKERS,
    detect_cost_spike,
    detect_issues_per_hour,
    detect_repair_ratio,
    detect_staleness,
    detect_tick_error_ratio,
)


def test_trust_loop_workers_contains_nine_spec_workers() -> None:
    """Sanity: the hard-coded watched-worker tuple matches spec §12.2."""
    expected = {
        "corpus_learning", "contract_refresh", "staging_bisect",
        "principles_audit", "flake_tracker", "skill_prompt_eval",
        "fake_coverage_auditor", "rc_budget", "wiki_rot_detector",
    }
    assert set(TRUST_LOOP_WORKERS) == expected


# --- 1. issues-per-hour ---

def test_issues_per_hour_breaches_on_overshoot() -> None:
    metrics = {"issues_filed_hour": 15}
    breached, details = detect_issues_per_hour(
        "ci_monitor", metrics, threshold=10,
    )
    assert breached is True
    assert details["issues_per_hour"] == 15
    assert details["threshold"] == 10


def test_issues_per_hour_exact_match_breaches() -> None:
    """`>=` comparison (sibling plan lock)."""
    metrics = {"issues_filed_hour": 10}
    breached, _ = detect_issues_per_hour("x", metrics, threshold=10)
    assert breached is True


def test_issues_per_hour_below_does_not_breach() -> None:
    metrics = {"issues_filed_hour": 3}
    breached, _ = detect_issues_per_hour("x", metrics, threshold=10)
    assert breached is False


# --- 2. repair ratio ---

def test_repair_ratio_breaches_when_failures_dominate() -> None:
    metrics = {"repaired_day": 2, "failed_day": 6}
    breached, details = detect_repair_ratio("x", metrics, threshold=2.0)
    assert breached is True
    assert details["ratio"] == pytest.approx(3.0)


def test_repair_ratio_insufficient_data_returns_false() -> None:
    metrics = {"repaired_day": 0, "failed_day": 0}
    breached, details = detect_repair_ratio("x", metrics, threshold=2.0)
    assert breached is False
    assert details["status"] == "insufficient_data"


def test_repair_ratio_zero_success_with_failures_treated_as_breach() -> None:
    """0 successes + ≥1 failure can't compute a finite ratio safely — the
    sanity loop errs on the side of alerting (operator decides)."""
    metrics = {"repaired_day": 0, "failed_day": 5}
    breached, details = detect_repair_ratio("x", metrics, threshold=2.0)
    assert breached is True
    assert details["status"] == "no_successes"


# --- 3. tick-error ratio ---

def test_tick_error_ratio_breaches_on_high_error_rate() -> None:
    metrics = {"ticks_total": 10, "ticks_errored": 3}
    breached, details = detect_tick_error_ratio("x", metrics, threshold=0.2)
    assert breached is True
    assert details["ratio"] == pytest.approx(0.3)


def test_tick_error_ratio_insufficient_data_returns_false() -> None:
    metrics = {"ticks_total": 0, "ticks_errored": 0}
    breached, details = detect_tick_error_ratio("x", metrics, threshold=0.2)
    assert breached is False
    assert details["status"] == "insufficient_data"


def test_tick_error_ratio_at_threshold_breaches() -> None:
    metrics = {"ticks_total": 10, "ticks_errored": 2}
    breached, _ = detect_tick_error_ratio("x", metrics, threshold=0.2)
    assert breached is True


# --- 4. staleness ---

def test_staleness_breaches_when_interval_exceeded_and_enabled() -> None:
    now = datetime.now(UTC)
    last_run = (now - timedelta(seconds=3000)).isoformat()
    breached, details = detect_staleness(
        "rc_budget",
        last_run_iso=last_run,
        interval_s=600,
        multiplier=2.0,
        is_enabled=True,
        now=now,
    )
    assert breached is True
    assert details["elapsed_s"] >= 3000
    assert details["threshold_s"] == 1200


def test_staleness_respects_disabled_flag() -> None:
    now = datetime.now(UTC)
    last_run = (now - timedelta(seconds=999999)).isoformat()
    breached, details = detect_staleness(
        "rc_budget",
        last_run_iso=last_run,
        interval_s=600,
        multiplier=2.0,
        is_enabled=False,
        now=now,
    )
    assert breached is False
    assert details["status"] == "disabled"


def test_staleness_no_heartbeat_is_not_a_breach() -> None:
    now = datetime.now(UTC)
    breached, details = detect_staleness(
        "rc_budget",
        last_run_iso=None,
        interval_s=600,
        multiplier=2.0,
        is_enabled=True,
        now=now,
    )
    assert breached is False
    assert details["status"] == "no_heartbeat"


# --- 5. cost spike ---

def test_cost_spike_breaches_on_overshoot() -> None:
    mod = MagicMock()
    mod.get_loop_cost_today.return_value = 60.0
    mod.get_loop_cost_30d_median.return_value = 10.0
    breached, details = detect_cost_spike(
        "rc_budget", reader=mod, threshold=5.0,
    )
    assert breached is True
    assert details["today_usd"] == pytest.approx(60.0)
    assert details["median_usd"] == pytest.approx(10.0)
    assert details["ratio"] == pytest.approx(6.0)


def test_cost_spike_absent_reader_returns_no_breach() -> None:
    breached, details = detect_cost_spike("rc_budget", reader=None, threshold=5.0)
    assert breached is False
    assert details["status"] == "cost_reader_unavailable"


def test_cost_spike_zero_median_returns_false() -> None:
    mod = MagicMock()
    mod.get_loop_cost_today.return_value = 5.0
    mod.get_loop_cost_30d_median.return_value = 0.0
    breached, details = detect_cost_spike(
        "rc_budget", reader=mod, threshold=5.0,
    )
    assert breached is False
    assert details["status"] == "insufficient_data"


def test_cost_spike_reader_exception_returns_false() -> None:
    """A broken cost reader must not crash the sanity loop."""
    mod = MagicMock()
    mod.get_loop_cost_today.side_effect = RuntimeError("boom")
    breached, details = detect_cost_spike(
        "rc_budget", reader=mod, threshold=5.0,
    )
    assert breached is False
    assert details["status"] == "reader_error"
```

- [ ] **Step 2: Run — expect FAIL (`ImportError`).**

- [ ] **Step 3: Create** `src/trust_fleet_anomaly_detectors.py`:

```python
"""Five pure anomaly-detector functions for TrustFleetSanityLoop (spec §12.1).

Each detector is a pure function that accepts a normalized metric dict
and returns ``(breached: bool, details: dict)``. No side effects, no
subprocess, no I/O (the cost-spike detector calls the passed reader
module's functions but the reader itself is injected — absent-reader
is a first-class *input*, not a runtime import failure). This makes
unit tests trivial and keeps the loop class focused on orchestration.

Threshold comparisons are ``>=`` per sibling-plan lock. Zero-
denominator paths return ``(False, {"status": "insufficient_data"})``
rather than raising — a fresh install shouldn't escalate the moment it
boots.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger("hydraflow.trust_fleet_anomaly_detectors")


# Spec §12.2 — exactly nine watched workers.
TRUST_LOOP_WORKERS: tuple[str, ...] = (
    "corpus_learning",
    "contract_refresh",
    "staging_bisect",
    "principles_audit",
    "flake_tracker",
    "skill_prompt_eval",
    "fake_coverage_auditor",
    "rc_budget",
    "wiki_rot_detector",
)


def detect_issues_per_hour(
    worker: str,
    metrics: dict[str, Any],
    *,
    threshold: int,
) -> tuple[bool, dict[str, Any]]:
    """`issues_filed_hour >= threshold` → breach (spec §12.1 bullet 1)."""
    filed = int(metrics.get("issues_filed_hour", 0))
    if filed >= threshold:
        return True, {
            "worker": worker,
            "issues_per_hour": filed,
            "threshold": threshold,
        }
    return False, {
        "worker": worker,
        "issues_per_hour": filed,
        "threshold": threshold,
    }


def detect_repair_ratio(
    worker: str,
    metrics: dict[str, Any],
    *,
    threshold: float,
) -> tuple[bool, dict[str, Any]]:
    """`failed / repaired >= threshold` over 24h → breach (spec §12.1 bullet 2)."""
    repaired = int(metrics.get("repaired_day", 0))
    failed = int(metrics.get("failed_day", 0))
    if repaired == 0 and failed == 0:
        return False, {
            "worker": worker,
            "status": "insufficient_data",
            "repaired": 0,
            "failed": 0,
        }
    if repaired == 0:
        # No successes + ≥1 failure — can't compute a finite ratio.
        # Escalate conservatively; operator decides if signal is real.
        return True, {
            "worker": worker,
            "status": "no_successes",
            "repaired": 0,
            "failed": failed,
            "threshold": threshold,
        }
    ratio = failed / repaired
    breached = ratio >= threshold
    return breached, {
        "worker": worker,
        "ratio": ratio,
        "repaired": repaired,
        "failed": failed,
        "threshold": threshold,
    }


def detect_tick_error_ratio(
    worker: str,
    metrics: dict[str, Any],
    *,
    threshold: float,
) -> tuple[bool, dict[str, Any]]:
    """`ticks_errored / ticks_total >= threshold` over 24h (spec §12.1 bullet 3)."""
    total = int(metrics.get("ticks_total", 0))
    errored = int(metrics.get("ticks_errored", 0))
    if total == 0:
        return False, {
            "worker": worker,
            "status": "insufficient_data",
            "ticks_total": 0,
        }
    ratio = errored / total
    breached = ratio >= threshold
    return breached, {
        "worker": worker,
        "ratio": ratio,
        "ticks_total": total,
        "ticks_errored": errored,
        "threshold": threshold,
    }


def detect_staleness(
    worker: str,
    *,
    last_run_iso: str | None,
    interval_s: int,
    multiplier: float,
    is_enabled: bool,
    now: datetime,
) -> tuple[bool, dict[str, Any]]:
    """Enabled loop hasn't ticked in > multiplier × interval (spec §12.1 bullet 4).

    A *disabled* loop not ticking is correct — no breach. A loop
    without a heartbeat at all is new / not-yet-run — no breach.
    """
    if not is_enabled:
        return False, {"worker": worker, "status": "disabled"}
    if not last_run_iso:
        return False, {"worker": worker, "status": "no_heartbeat"}
    try:
        last_run = datetime.fromisoformat(last_run_iso.replace("Z", "+00:00"))
    except ValueError:
        return False, {"worker": worker, "status": "bad_heartbeat_iso"}
    if last_run.tzinfo is None:
        last_run = last_run.replace(tzinfo=UTC)
    elapsed_s = (now - last_run).total_seconds()
    threshold_s = multiplier * interval_s
    breached = elapsed_s >= threshold_s
    return breached, {
        "worker": worker,
        "elapsed_s": int(elapsed_s),
        "interval_s": interval_s,
        "multiplier": multiplier,
        "threshold_s": int(threshold_s),
        "last_run_iso": last_run_iso,
    }


def detect_cost_spike(
    worker: str,
    *,
    reader: Any | None,
    threshold: float,
) -> tuple[bool, dict[str, Any]]:
    """Current-day cost >= threshold × 30-day median (spec §12.1 bullet 5).

    ``reader`` is a module-like object exposing
    ``get_loop_cost_today(worker) -> float`` and
    ``get_loop_cost_30d_median(worker) -> float``. When ``None``
    (reader absent) or raises, the detector returns no-breach with a
    status tag — spec tolerates the §4.11 module being unbuilt.
    """
    if reader is None:
        return False, {"worker": worker, "status": "cost_reader_unavailable"}
    try:
        today = float(reader.get_loop_cost_today(worker))
        median = float(reader.get_loop_cost_30d_median(worker))
    except Exception as exc:  # noqa: BLE001
        logger.debug("cost reader failed for %s: %s", worker, exc, exc_info=True)
        return False, {"worker": worker, "status": "reader_error"}
    if median <= 0.0:
        return False, {
            "worker": worker,
            "status": "insufficient_data",
            "today_usd": today,
            "median_usd": median,
        }
    ratio = today / median
    breached = ratio >= threshold
    return breached, {
        "worker": worker,
        "today_usd": today,
        "median_usd": median,
        "ratio": ratio,
        "threshold": threshold,
    }
```

- [ ] **Step 4: Re-run — expect all 13 detector tests PASS.**
- [ ] **Step 5: Commit:**

  ```bash
  git add src/trust_fleet_anomaly_detectors.py tests/test_trust_fleet_anomaly_detectors.py
  git commit -m "feat(trust): five anomaly detectors + TRUST_LOOP_WORKERS (§12.1)"
  ```

---

## Task 6 — Filing + 1-attempt escalation + close-reconcile

Wire the skeleton's `_do_work` to the detectors. One-attempt escalation: first breach fires `hitl-escalation` + `trust-loop-anomaly` directly.

- [ ] **Step 1: Append failing tests** to `tests/test_trust_fleet_sanity_loop.py`:

```python
async def test_do_work_files_escalation_on_issues_per_hour_breach(loop_env) -> None:
    cfg, state, bg_workers, pr, dedup, bus = loop_env
    async def fake_load(since):  # noqa: ARG001
        return [
            _make_status_event("ci_monitor", "ok", ago_s=600, filed=20),
        ]
    bus.load_events_since = fake_load  # type: ignore[method-assign]
    loop = _loop(loop_env)
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    loop._load_cost_reader = MagicMock(return_value=None)
    stats = await loop._do_work()
    assert stats["anomalies"] >= 1
    assert pr.create_issue.await_count >= 1
    title = pr.create_issue.await_args.args[0]
    assert "trust-loop anomaly" in title
    assert "ci_monitor" in title
    assert "issues_per_hour" in title
    labels = pr.create_issue.await_args.args[2]
    assert "hitl-escalation" in labels
    assert "trust-loop-anomaly" in labels


async def test_do_work_skips_filing_when_dedup_key_present(loop_env) -> None:
    cfg, state, bg_workers, pr, dedup, bus = loop_env
    dedup.get.return_value = {"trust_fleet_sanity:issues_per_hour:ci_monitor"}
    async def fake_load(since):  # noqa: ARG001
        return [_make_status_event("ci_monitor", "ok", ago_s=600, filed=20)]
    bus.load_events_since = fake_load  # type: ignore[method-assign]
    loop = _loop(loop_env)
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    loop._load_cost_reader = MagicMock(return_value=None)
    stats = await loop._do_work()
    assert stats["anomalies"] == 0
    pr.create_issue.assert_not_awaited()


async def test_do_work_staleness_detector_uses_bg_worker_state(loop_env) -> None:
    cfg, state, bg_workers, pr, dedup, bus = loop_env
    old = (datetime.now(UTC) - timedelta(seconds=99_999)).isoformat()
    state.get_worker_heartbeats.return_value = {
        "rc_budget": {"status": "ok", "last_run": old, "details": {}},
    }
    bg_workers.worker_enabled = {"rc_budget": True}
    bg_workers.get_interval.return_value = 600
    async def fake_load(since):  # noqa: ARG001
        return []
    bus.load_events_since = fake_load  # type: ignore[method-assign]
    loop = _loop(loop_env)
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    loop._load_cost_reader = MagicMock(return_value=None)
    stats = await loop._do_work()
    assert stats["anomalies"] >= 1
    title = pr.create_issue.await_args.args[0]
    assert "rc_budget" in title
    assert "staleness" in title


async def test_do_work_cost_spike_skipped_when_reader_absent(loop_env) -> None:
    """Cost-reader-absent = no breach, no escalation, no crash."""
    cfg, state, bg_workers, pr, dedup, bus = loop_env
    async def fake_load(since):  # noqa: ARG001
        return []  # no tick events anywhere
    bus.load_events_since = fake_load  # type: ignore[method-assign]
    loop = _loop(loop_env)
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    loop._load_cost_reader = MagicMock(return_value=None)
    stats = await loop._do_work()
    assert stats["anomalies"] == 0
    pr.create_issue.assert_not_awaited()


async def test_reconcile_closed_escalations_clears_dedup(loop_env, monkeypatch) -> None:
    cfg, state, bg_workers, pr, dedup, bus = loop_env
    dedup.get.return_value = {
        "trust_fleet_sanity:issues_per_hour:ci_monitor",
        "trust_fleet_sanity:staleness:rc_budget",
    }
    loop = _loop(loop_env)

    class _P:
        returncode = 0
        async def communicate(self):
            # Only the ci_monitor escalation was closed.
            return (
                b'[{"title": "HITL: trust-loop anomaly \xe2\x80\x94 '
                b'ci_monitor issues_per_hour"}]',
                b"",
            )

    async def fake_subproc(*args, **kwargs):
        return _P()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subproc)
    await loop._reconcile_closed_escalations()
    dedup.set_all.assert_called_once()
    remaining = dedup.set_all.call_args.args[0]
    assert "trust_fleet_sanity:issues_per_hour:ci_monitor" not in remaining
    assert "trust_fleet_sanity:staleness:rc_budget" in remaining
    state.clear_trust_fleet_sanity_attempts.assert_called_once_with(
        "issues_per_hour:ci_monitor"
    )
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Replace `_do_work` + add helpers** in `src/trust_fleet_sanity_loop.py`:

```python
    async def _do_work(self) -> WorkCycleResult:
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        t0 = time.perf_counter()
        await self._reconcile_closed_escalations()

        now = datetime.now(UTC)
        window_metrics = await self._collect_window_metrics()
        heartbeats = self._state.get_worker_heartbeats()
        enabled_map = dict(getattr(self._bg_workers, "worker_enabled", {}))
        cost_reader = self._load_cost_reader()

        dedup = set(self._dedup.get())
        filed = 0
        anomalies: list[dict[str, Any]] = []

        cfg = self._config
        for worker in TRUST_LOOP_WORKERS:
            metrics = window_metrics.get(worker, {})
            per_worker_breaches: list[tuple[str, dict[str, Any]]] = []

            breached, details = detect_issues_per_hour(
                worker, metrics, threshold=cfg.loop_anomaly_issues_per_hour,
            )
            if breached:
                per_worker_breaches.append(("issues_per_hour", details))

            breached, details = detect_repair_ratio(
                worker, metrics, threshold=cfg.loop_anomaly_repair_ratio,
            )
            if breached:
                per_worker_breaches.append(("repair_ratio", details))

            breached, details = detect_tick_error_ratio(
                worker, metrics, threshold=cfg.loop_anomaly_tick_error_ratio,
            )
            if breached:
                per_worker_breaches.append(("tick_error_ratio", details))

            hb = heartbeats.get(worker) or {}
            last_run_iso = hb.get("last_run") if isinstance(hb, dict) else None
            interval_s = int(
                self._bg_workers.get_interval(worker) if hasattr(self._bg_workers, "get_interval") else 86400
            )
            is_enabled = bool(enabled_map.get(worker, True))
            breached, details = detect_staleness(
                worker,
                last_run_iso=last_run_iso,
                interval_s=interval_s,
                multiplier=cfg.loop_anomaly_staleness_multiplier,
                is_enabled=is_enabled,
                now=now,
            )
            if breached:
                per_worker_breaches.append(("staleness", details))

            breached, details = detect_cost_spike(
                worker, reader=cost_reader,
                threshold=cfg.loop_anomaly_cost_spike_ratio,
            )
            if breached:
                per_worker_breaches.append(("cost_spike", details))

            for kind, det in per_worker_breaches:
                key = f"trust_fleet_sanity:{kind}:{worker}"
                if key in dedup:
                    continue
                attempts = self._state.inc_trust_fleet_sanity_attempts(
                    f"{kind}:{worker}"
                )
                if attempts >= _MAX_ATTEMPTS:
                    issue_no = await self._file_anomaly(worker, kind, det)
                    anomalies.append({
                        "worker": worker, "kind": kind,
                        "issue_number": issue_no,
                        "details": det,
                    })
                    filed += 1
                dedup.add(key)
                self._dedup.set_all(dedup)

        self._state.set_trust_fleet_sanity_last_run(now.isoformat())
        self._emit_trace(t0, anomalies=len(anomalies))
        return {
            "status": "ok",
            "anomalies": len(anomalies),
            "workers_scanned": len(TRUST_LOOP_WORKERS),
            "filed": filed,
        }

    async def _file_anomaly(
        self, worker: str, kind: str, details: dict[str, Any],
    ) -> int:
        title = f"HITL: trust-loop anomaly — {worker} {kind}"
        detail_lines = "\n".join(
            f"- `{k}`: `{v}`" for k, v in sorted(details.items())
            if k not in {"worker"}
        )
        body = (
            f"## Trust-loop anomaly (`{kind}`) — `{worker}`\n\n"
            f"`TrustFleetSanityLoop` detected `{kind}` threshold breach for "
            f"the `{worker}` loop. Per spec §12.1 the anomaly is the "
            f"escalation — one-attempt, no retry budget.\n\n"
            f"### Detector output\n{detail_lines}\n\n"
            f"### Operator playbook\n"
            f"1. Flip `{worker}`'s kill-switch in the **System** tab if the "
            f"loop is actively misbehaving (spec §12.2).\n"
            f"2. Investigate via the **Diagnostics → Trust Fleet** sub-tab "
            f"(spec §12.3) — click the loop for recent runs + job breakdowns.\n"
            f"3. Close this issue once resolved. Closing clears "
            f"`trust_fleet_sanity:{kind}:{worker}` from the dedup set so the "
            f"detector is free to re-fire on the next drift (spec §3.2).\n\n"
            f"_Auto-filed by HydraFlow `trust_fleet_sanity` (spec §12.1)._"
        )
        return await self._pr.create_issue(
            title, body, ["hitl-escalation", "trust-loop-anomaly"],
        )

    async def _reconcile_closed_escalations(self) -> None:
        cmd = [
            "gh", "issue", "list", "--repo", self._config.repo,
            "--state", "closed",
            "--label", "hitl-escalation", "--label", "trust-loop-anomaly",
            "--author", "@me", "--limit", "200", "--json", "title",
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
        any_change = False
        for issue in closed:
            title = str(issue.get("title", ""))
            m = _TITLE_RE.search(title)
            if not m:
                continue
            worker = m.group("worker")
            kind = m.group("kind")
            key = f"trust_fleet_sanity:{kind}:{worker}"
            if key in keep:
                keep.discard(key)
                self._state.clear_trust_fleet_sanity_attempts(f"{kind}:{worker}")
                any_change = True
        if any_change:
            self._dedup.set_all(keep)

    def _emit_trace(self, t0: float, *, anomalies: int) -> None:
        try:
            from trace_collector import emit_loop_subprocess_trace  # noqa: PLC0415
        except ImportError:
            return
        try:
            emit_loop_subprocess_trace(
                worker_name=self._worker_name,
                command=["trust_fleet_sanity", "tick"],
                exit_code=0,
                duration_s=time.perf_counter() - t0,
                stdout_tail=f"anomalies={anomalies}",
                stderr_tail="",
            )
        except Exception:  # noqa: BLE001
            logger.debug("trace emission failed", exc_info=True)
```

- [ ] **Step 4: Re-run — expect all PASS.**
- [ ] **Step 5: Commit:**

  ```bash
  git add src/trust_fleet_sanity_loop.py tests/test_trust_fleet_sanity_loop.py
  git commit -m "feat(loop): TrustFleetSanity filing + 1-attempt escalation + reconcile (§12.1)"
  ```

---

## Task 7 — HealthMonitor dead-man-switch integration

The sanity loop watches the nine trust loops. HealthMonitor watches the sanity loop. One-layer bounded meta-observability.

Implementation: add a new method to `HealthMonitorLoop` that checks `trust_fleet_sanity`'s heartbeat and files a conventional `hydraflow-find` + `sanity-loop-stalled` issue when the loop has been silent for `>= 3 × trust_fleet_sanity_interval` while enabled.

- [ ] **Step 1: Write failing test** — `tests/test_health_monitor_sanity_stall.py`:

```python
"""Test HealthMonitor dead-man-switch for TrustFleetSanityLoop (spec §12.1)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def hm_env(tmp_path: Path):
    from base_background_loop import LoopDeps
    from config import HydraFlowConfig
    from events import EventBus
    from health_monitor_loop import HealthMonitorLoop

    cfg = HydraFlowConfig(
        data_root=tmp_path, repo="hydra/hydraflow",
        trust_fleet_sanity_interval=600,
    )
    state = MagicMock()
    state.get_worker_heartbeats.return_value = {}
    bg_workers = MagicMock()
    bg_workers.worker_enabled = {"trust_fleet_sanity": True}
    prs = AsyncMock()
    prs.create_issue = AsyncMock(return_value=17)
    import asyncio as _a
    deps = LoopDeps(
        event_bus=EventBus(), stop_event=_a.Event(),
        status_cb=lambda *a, **k: None, enabled_cb=lambda _n: True,
    )
    # HealthMonitorLoop's full ctor takes many args; pass the minimum the
    # check-method needs via attribute injection.
    hm = HealthMonitorLoop.__new__(HealthMonitorLoop)
    hm._config = cfg
    hm._state = state
    hm._bg_workers = bg_workers
    hm._prs = prs
    return hm, state, bg_workers, prs


async def test_stall_over_3x_interval_files_issue(hm_env) -> None:
    hm, state, bg_workers, prs = hm_env
    # Sanity loop heartbeat is 4× interval old.
    stale = (datetime.now(UTC) - timedelta(seconds=2400)).isoformat()
    state.get_worker_heartbeats.return_value = {
        "trust_fleet_sanity": {
            "status": "ok", "last_run": stale, "details": {},
        },
    }
    await hm._check_sanity_loop_staleness()
    prs.create_issue.assert_awaited_once()
    title = prs.create_issue.await_args.args[0]
    assert "sanity-loop-stalled" in title or "stalled" in title.lower()
    labels = prs.create_issue.await_args.args[2]
    assert "hydraflow-find" in labels
    assert "sanity-loop-stalled" in labels


async def test_no_issue_when_disabled(hm_env) -> None:
    hm, state, bg_workers, prs = hm_env
    bg_workers.worker_enabled = {"trust_fleet_sanity": False}
    stale = (datetime.now(UTC) - timedelta(seconds=99999)).isoformat()
    state.get_worker_heartbeats.return_value = {
        "trust_fleet_sanity": {"status": "ok", "last_run": stale, "details": {}},
    }
    await hm._check_sanity_loop_staleness()
    prs.create_issue.assert_not_awaited()


async def test_no_issue_when_heartbeat_recent(hm_env) -> None:
    hm, state, bg_workers, prs = hm_env
    recent = (datetime.now(UTC) - timedelta(seconds=120)).isoformat()
    state.get_worker_heartbeats.return_value = {
        "trust_fleet_sanity": {"status": "ok", "last_run": recent, "details": {}},
    }
    await hm._check_sanity_loop_staleness()
    prs.create_issue.assert_not_awaited()


async def test_no_issue_when_no_heartbeat_yet(hm_env) -> None:
    """A fresh install with no sanity-loop heartbeat must not trip."""
    hm, state, bg_workers, prs = hm_env
    state.get_worker_heartbeats.return_value = {}
    await hm._check_sanity_loop_staleness()
    prs.create_issue.assert_not_awaited()
```

- [ ] **Step 2: Run — expect FAIL (method missing).**

- [ ] **Step 3: Modify** `src/health_monitor_loop.py`:

   3a. Near the other module-level constants (around `_STALE_COUNT_HIGH = 5` — circa `src/health_monitor_loop.py:57`), append:

   ```python
   _SANITY_STALL_MULTIPLIER = 3  # HealthMonitor dead-man-switch for TrustFleetSanity (spec §12.1)
   ```

   3b. Inside `HealthMonitorLoop._do_work()` (circa `src/health_monitor_loop.py:336`), near the top (before the existing metric-collection block), insert:

   ```python
           # Dead-man-switch: detect a stalled TrustFleetSanityLoop (spec §12.1).
           try:
               await self._check_sanity_loop_staleness()
           except Exception:  # noqa: BLE001
               logger.debug("sanity-loop stall check failed", exc_info=True)
   ```

   3c. Append a new method inside `HealthMonitorLoop` (place at the end of the class, before the final `)` of the file):

   ```python
       async def _check_sanity_loop_staleness(self) -> None:
           """Dead-man-switch for `TrustFleetSanityLoop` (spec §12.1).

           When the sanity loop is enabled but its heartbeat is older than
           ``_SANITY_STALL_MULTIPLIER × trust_fleet_sanity_interval``,
           file a conventional `hydraflow-find` + `sanity-loop-stalled`
           issue. The sanity loop watches the nine trust loops; this
           method watches the sanity loop. Recursion bounded at one
           meta-layer (spec §12.1 "Bounds of meta-observability").
           """
           heartbeats = self._state.get_worker_heartbeats()
           hb = heartbeats.get("trust_fleet_sanity")
           if not hb:
               return
           last_run_iso = hb.get("last_run") if isinstance(hb, dict) else None
           if not last_run_iso:
               return
           enabled = bool(
               getattr(self._bg_workers, "worker_enabled", {}).get(
                   "trust_fleet_sanity", True
               )
           )
           if not enabled:
               return
           try:
               last_run = datetime.fromisoformat(
                   last_run_iso.replace("Z", "+00:00"),
               )
           except ValueError:
               return
           if last_run.tzinfo is None:
               last_run = last_run.replace(tzinfo=UTC)
           elapsed_s = (datetime.now(UTC) - last_run).total_seconds()
           threshold_s = (
               _SANITY_STALL_MULTIPLIER
               * self._config.trust_fleet_sanity_interval
           )
           if elapsed_s < threshold_s:
               return

           title = (
               f"sanity-loop-stalled: trust_fleet_sanity silent for "
               f"{int(elapsed_s)}s (threshold {int(threshold_s)}s)"
           )
           body = (
               f"## TrustFleetSanityLoop dead-man-switch tripped\n\n"
               f"The meta-observability loop has not ticked in "
               f"`{int(elapsed_s)}s`, exceeding "
               f"`{_SANITY_STALL_MULTIPLIER} × "
               f"trust_fleet_sanity_interval` = `{int(threshold_s)}s` "
               f"(spec §12.1).\n\n"
               f"- Last heartbeat: `{last_run_iso}`\n"
               f"- Interval: "
               f"`{self._config.trust_fleet_sanity_interval}s`\n"
               f"- Enabled: `True`\n\n"
               f"### Operator playbook\n"
               f"1. Check orchestrator logs for the `trust_fleet_sanity` "
               f"loop task (look for uncaught exceptions on the run task).\n"
               f"2. Restart the orchestrator (`systemctl restart hydraflow` "
               f"or equivalent).\n"
               f"3. If the loop continues to stall, flip its "
               f"kill-switch in the **System** tab and file a HydraFlow "
               f"bug report.\n\n"
               f"_Auto-filed by HydraFlow `health_monitor` "
               f"(spec §12.1 dead-man-switch)._"
           )
           await self._prs.create_issue(
               title, body, ["hydraflow-find", "sanity-loop-stalled"],
           )
   ```

   Verify the `self._prs` / `self._state` / `self._bg_workers` / `self._config` attribute names match the class's `__init__` — adjust if the real field names differ (confirmed in `src/health_monitor_loop.py:298`-circa as `self._config`, `self._state`, `self._prs`, `self._bg_workers`).

   3d. Ensure `datetime` + `UTC` are imported at the top of `health_monitor_loop.py` — they already are (line ~20 of the file).

- [ ] **Step 4: Re-run — expect 4 PASS.**
- [ ] **Step 5: Commit:**

  ```bash
  git add src/health_monitor_loop.py tests/test_health_monitor_sanity_stall.py
  git commit -m "feat(health): sanity-loop dead-man-switch (§12.1 bounds)"
  ```

---

## Task 8 — Kill-switch integration test

The base-class kill-switch (`LoopDeps.enabled_cb`) is already honored in Task 3's skeleton via the defensive `_enabled_cb` check at the top of `_do_work`. Add an explicit integration test that drives the public `run()` path and confirms the loop files nothing when disabled mid-cycle.

- [ ] **Step 1: Append failing test** to `tests/test_trust_fleet_sanity_loop.py`:

```python
async def test_kill_switch_via_run_loop_blocks_all_work(loop_env) -> None:
    """End-to-end: `run()` must not escalate when `enabled_cb` returns False."""
    cfg, state, bg_workers, pr, dedup, bus = loop_env
    stop = asyncio.Event()
    deps = LoopDeps(
        event_bus=bus, stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda name: name != "trust_fleet_sanity",
    )
    loop = TrustFleetSanityLoop(
        config=cfg, state=state, bg_workers=bg_workers,
        pr_manager=pr, dedup=dedup, event_bus=bus, deps=deps,
    )
    # Belt + braces: if the base class lets work run, the collector must
    # fail loudly so the test surfaces the regression.
    loop._collect_window_metrics = AsyncMock(
        side_effect=AssertionError("must not run")
    )

    async def driver():
        await asyncio.sleep(0.02)
        stop.set()

    await asyncio.gather(loop.run(), driver())
    pr.create_issue.assert_not_awaited()


async def test_trace_emission_tolerates_missing_module(loop_env, monkeypatch) -> None:
    """Lazy trace_collector import must not be a hard dependency (sibling lock)."""
    import sys
    monkeypatch.setitem(sys.modules, "trace_collector", None)
    loop = _loop(loop_env)
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    async def fake_load(since):  # noqa: ARG001
        return []
    _, _, _, _, _, bus = loop_env
    bus.load_events_since = fake_load  # type: ignore[method-assign]
    loop._load_cost_reader = MagicMock(return_value=None)
    stats = await loop._do_work()
    assert stats["status"] == "ok"
```

- [ ] **Step 2: Run — expect PASS** (no source edits needed; kill-switch is base-class behavior + Task 3's defensive check; lazy trace is already guarded).
- [ ] **Step 3: Commit:**

  ```bash
  git add tests/test_trust_fleet_sanity_loop.py
  git commit -m "test(loop): TrustFleetSanity kill-switch + lazy trace coverage (§3.2 / §12.2)"
  ```

---

## Task 9 — `/api/trust/fleet` endpoint schema documentation

The read-side endpoint is owned by Plan 6b. This plan's contribution: an authoritative schema constant inside `src/trust_fleet_sanity_loop.py` so Plan 6b has a target. Task 3 already created `FLEET_ENDPOINT_SCHEMA` as a module-level string. This task adds a unit test that asserts the constant is present and well-formed, plus a small assertion that Plan 6b can key off of.

- [ ] **Step 1: Append failing test** to `tests/test_trust_fleet_sanity_loop.py`:

```python
def test_fleet_endpoint_schema_is_documented() -> None:
    """Plan 6b reads this schema to implement /api/trust/fleet."""
    from trust_fleet_sanity_loop import FLEET_ENDPOINT_SCHEMA

    schema = FLEET_ENDPOINT_SCHEMA
    # Required top-level keys must be documented.
    for key in (
        "range", "generated_at", "loops", "anomalies_recent",
        "worker_name", "enabled", "interval_s", "last_tick_at",
        "ticks_total", "ticks_errored", "issues_filed_total",
        "repair_successes_total", "repair_failures_total",
    ):
        assert key in schema, f"missing schema key: {key}"
    # Must reference the owning plan.
    assert "Plan 6b" in schema
    # Must reference the implementation hooks Plan 6b will call.
    assert "load_events_since" in schema
    assert "get_worker_heartbeats" in schema
```

- [ ] **Step 2: Run — expect PASS** (the constant is already defined in Task 3's file body).
- [ ] **Step 3: Commit (with the other Task-9 doc tweaks if any — otherwise skip).**

  ```bash
  git add tests/test_trust_fleet_sanity_loop.py
  git commit -m "test(loop): assert /api/trust/fleet schema contract for Plan 6b (§12.1)"
  ```

---

## Task 10 — Five-checkpoint wiring

One task, five sub-steps. The worker string `trust_fleet_sanity` must be verbatim across all five sites — `test_loop_wiring_completeness.py` matches exactly.

- [ ] **Step 1: `src/service_registry.py`**

  - `:63` area — add the import near the other loop imports:

    ```python
    from trust_fleet_sanity_loop import TrustFleetSanityLoop  # noqa: TCH001
    ```

  - `:168` — append a dataclass field after `retrospective_loop`:

    ```python
        trust_fleet_sanity_loop: TrustFleetSanityLoop
    ```

  - `:813` — after the `retrospective_loop = RetrospectiveLoop(...)` block, insert:

    ```python
    trust_fleet_sanity_dedup = DedupStore(
        "trust_fleet_sanity",
        config.data_root / "dedup" / "trust_fleet_sanity.json",
    )
    trust_fleet_sanity_loop = TrustFleetSanityLoop(  # noqa: F841
        config=config,
        state=state,
        bg_workers=bg_workers,
        pr_manager=prs,
        dedup=trust_fleet_sanity_dedup,
        event_bus=event_bus,
        deps=loop_deps,
    )
    ```

    Confirm that `bg_workers` and `event_bus` are in scope at this site — grep `service_registry.py` for where `BGWorkerManager` and `EventBus` are constructed. If the construction is performed in `orchestrator.py` rather than `service_registry.py`, invert the wiring: construct the sanity loop inside `orchestrator.py:__init__` after `BGWorkerManager` is built, and expose it to `ServiceRegistry` via a deferred setter (`svc.trust_fleet_sanity_loop = ...`). A one-line alternative: pass the `bg_workers` / `event_bus` parameters into `build_service_registry()` as explicit keyword arguments sourced from the orchestrator. Verify before editing.

  - `:871` — append inside the `return ServiceRegistry(...)` call:

    ```python
        trust_fleet_sanity_loop=trust_fleet_sanity_loop,
    ```

- [ ] **Step 2: `src/orchestrator.py`**

  - `:158` — append to `bg_loop_registry`:

    ```python
        "trust_fleet_sanity": svc.trust_fleet_sanity_loop,
    ```

  - `:909` — append to `loop_factories`:

    ```python
        ("trust_fleet_sanity", self._svc.trust_fleet_sanity_loop.run),
    ```

- [ ] **Step 3: `src/ui/src/constants.js`**

  - `:252` — append `'trust_fleet_sanity'` to the `EDITABLE_INTERVAL_WORKERS` Set (inside the existing array-of-strings).
  - `:273` — append to `SYSTEM_WORKER_INTERVALS`:

    ```js
      trust_fleet_sanity: 600,
    ```

  - `:312` — append to `BACKGROUND_WORKERS` (as the last entry before the closing `]`):

    ```js
      { key: 'trust_fleet_sanity', label: 'Trust Fleet Sanity', description: 'Meta-observability. Watches the nine trust loops for anomalies (issues/hr, repair ratio, tick-error rate, staleness, cost spikes); files HITL escalations on breach.', color: theme.red, system: true, group: 'operations', tags: ['monitoring'] },
    ```

- [ ] **Step 4: `src/dashboard_routes/_common.py`**

  - `:55` — append to `_INTERVAL_BOUNDS`:

    ```python
        "trust_fleet_sanity": (60, 3600),
    ```

- [ ] **Step 5: Verify + commit:**

  ```bash
  PYTHONPATH=src uv run pytest tests/test_loop_wiring_completeness.py -v
  git add src/service_registry.py src/orchestrator.py src/ui/src/constants.js src/dashboard_routes/_common.py
  git commit -m "feat(wiring): TrustFleetSanityLoop five-checkpoint registration (§12.1)"
  ```

  Expected: all wiring tests green.

---

## Task 11 — Loop-wiring-completeness confirmation

Regex discovery in `tests/test_loop_wiring_completeness.py` auto-matches `worker_name="trust_fleet_sanity"` — no edit required.

- [ ] **Step 1: Confirm:**

  ```bash
  PYTHONPATH=src uv run pytest tests/test_loop_wiring_completeness.py -v
  ```

  Expected: PASS.

- [ ] **Step 2: Spot-check:**

  ```bash
  grep -n "trust_fleet_sanity" \
      src/orchestrator.py \
      src/service_registry.py \
      src/dashboard_routes/_common.py \
      src/ui/src/constants.js
  ```

  Expected: multiple hits across all four files.

No commit — nothing changed.

---

## Task 12 — MockWorld scenario + catalog

**Modify** `tests/scenarios/catalog/loop_registrations.py` — insert above `_BUILDERS` (around line 233):

```python
def _build_trust_fleet_sanity(
    ports: dict[str, Any], config: Any, deps: Any,
) -> Any:
    from trust_fleet_sanity_loop import TrustFleetSanityLoop  # noqa: PLC0415

    state = ports.get("trust_fleet_sanity_state") or MagicMock()
    dedup = ports.get("trust_fleet_sanity_dedup") or MagicMock()
    bg_workers = ports.get("bg_workers") or MagicMock()
    event_bus = ports.get("event_bus") or MagicMock()
    ports.setdefault("trust_fleet_sanity_state", state)
    ports.setdefault("trust_fleet_sanity_dedup", dedup)
    ports.setdefault("bg_workers", bg_workers)
    ports.setdefault("event_bus", event_bus)
    return TrustFleetSanityLoop(
        config=config,
        state=state,
        bg_workers=bg_workers,
        pr_manager=ports["github"],
        dedup=dedup,
        event_bus=event_bus,
        deps=deps,
    )
```

Append to `_BUILDERS`:

```python
    "trust_fleet_sanity": _build_trust_fleet_sanity,
```

**Modify** `tests/scenarios/catalog/test_loop_instantiation.py` (around line 30) — append `"trust_fleet_sanity",` to the `ALL_LOOPS`-style list.

**Modify** `tests/scenarios/catalog/test_loop_registrations.py` (around line 30) — append `"trust_fleet_sanity",` to the `ALL_LOOPS`-style list.

**Create** `tests/scenarios/test_trust_fleet_sanity_scenario.py`:

```python
"""Scenario: TrustFleetSanityLoop escalates on a stale worker heartbeat.

Seeds a world where `rc_budget` has not ticked in 4 hours (well past
`2.0 × 14400s`); the sanity loop must file a `hitl-escalation` +
`trust-loop-anomaly` issue naming `rc_budget` and `staleness` on the
first tick.
"""

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


class TestTrustFleetSanityScenario:
    async def test_files_escalation_on_stale_rc_budget(
        self, tmp_path, monkeypatch,
    ) -> None:
        world = MockWorld(tmp_path)

        # Heartbeats: rc_budget hasn't ticked in 4h (interval 14400s);
        # threshold is 2.0 × 14400 = 28800s → 4h trips.
        stale_iso = (
            _dt.datetime.now(_dt.UTC) - _dt.timedelta(seconds=60000)
        ).isoformat()
        fake_state = MagicMock()
        fake_state.get_trust_fleet_sanity_attempts.return_value = 0
        fake_state.inc_trust_fleet_sanity_attempts.return_value = 1
        fake_state.get_trust_fleet_sanity_last_seen_counts.return_value = {}
        fake_state.get_worker_heartbeats.return_value = {
            "rc_budget": {
                "status": "ok", "last_run": stale_iso, "details": {},
            },
        }

        fake_dedup = MagicMock()
        fake_dedup.get.return_value = set()

        fake_bg_workers = MagicMock()
        fake_bg_workers.worker_enabled = {"rc_budget": True}
        fake_bg_workers.get_interval.return_value = 14400

        fake_bus = MagicMock()
        async def fake_load(since):  # noqa: ARG001
            return []
        fake_bus.load_events_since = fake_load

        fake_github = AsyncMock()
        fake_github.create_issue = AsyncMock(return_value=99)

        _seed_ports(
            world, github=fake_github,
            trust_fleet_sanity_state=fake_state,
            trust_fleet_sanity_dedup=fake_dedup,
            bg_workers=fake_bg_workers,
            event_bus=fake_bus,
        )

        async def fake_subproc(*args, **kwargs):
            argv = args
            if "issue" in argv and "list" in argv:
                return _FakeProc(b"[]")  # no closed escalations to reconcile
            return _FakeProc(b"[]")

        monkeypatch.setattr(_asyncio, "create_subprocess_exec", fake_subproc)

        stats = await world.run_with_loops(
            ["trust_fleet_sanity"], cycles=1,
        )

        assert stats["trust_fleet_sanity"]["anomalies"] >= 1, stats
        assert fake_github.create_issue.await_count >= 1
        title = fake_github.create_issue.await_args.args[0]
        assert "rc_budget" in title
        assert "staleness" in title
        labels = fake_github.create_issue.await_args.args[2]
        assert "hitl-escalation" in labels
        assert "trust-loop-anomaly" in labels
```

- [ ] **Step 1: Run:**

  ```bash
  PYTHONPATH=src uv run pytest \
      tests/scenarios/test_trust_fleet_sanity_scenario.py \
      tests/scenarios/catalog/ -v
  ```

  Expected: PASS across scenario + catalog coverage.

- [ ] **Step 2: Commit:**

  ```bash
  git add \
      tests/scenarios/catalog/loop_registrations.py \
      tests/scenarios/catalog/test_loop_instantiation.py \
      tests/scenarios/catalog/test_loop_registrations.py \
      tests/scenarios/test_trust_fleet_sanity_scenario.py
  git commit -m "test(scenarios): TrustFleetSanity scenario + catalog registration (§12.1)"
  ```

---

## Task 13 — Final verification + PR

- [ ] **Step 1:** `make quality` — hard gate per `docs/agents/quality-gates.md`. Fix anything red.

- [ ] **Step 2:** `git push -u origin trust-arch-hardening`

- [ ] **Step 3:**

  ```bash
  gh pr create --title "feat(loop): TrustFleetSanityLoop — meta-observability for the trust fleet (§12.1)" --body "$(cat <<'EOF'
## Summary

- New `TrustFleetSanityLoop` (`src/trust_fleet_sanity_loop.py`) — the tenth trust loop. 10-minute `BaseBackgroundLoop` that watches the nine §4.1–§4.9 loops for five anomalies and files `hitl-escalation` + `trust-loop-anomaly` issues on breach:
  - **issues-per-hour** (default `10`)
  - **repair ratio** over 24h (default `2.0`)
  - **tick-error ratio** over 24h (default `0.2`)
  - **staleness** (default `2.0 × interval`)
  - **cost spike** over 30-day median (default `5.0`; reads §4.11 endpoint — tolerates absence)
- **One-attempt escalation** (anomaly IS the escalation, no retry budget — spec §12.1).
- Five pure detector functions in `src/trust_fleet_anomaly_detectors.py` — trivial unit tests.
- Metrics read from `EventBus.load_events_since` (24h tick window) + `StateTracker.get_worker_heartbeats` (staleness) + lazy-imported `trust_fleet_cost_reader` (cost — Plan 6b owns the module).
- Dedup-on-close reconcile clears `trust_fleet_sanity:{kind}:{worker}` keys when the operator closes the escalation (spec §3.2).
- **HealthMonitor dead-man-switch** (`src/health_monitor_loop.py`) files `hydraflow-find` + `sanity-loop-stalled` when the sanity loop itself stops ticking for `3× interval` — recursion bounded at one meta-layer (spec §12.1 "Bounds").
- Kill-switch via `LoopDeps.enabled_cb("trust_fleet_sanity")` — no `trust_fleet_sanity_enabled` config field (spec §12.2).
- `/api/trust/fleet` endpoint **schema** documented as `FLEET_ENDPOINT_SCHEMA` module constant — Plan 6b owns the route impl.
- State mixin `TrustFleetSanityStateMixin` + three `StateData` fields (`trust_fleet_sanity_attempts`, `trust_fleet_sanity_last_run`, `trust_fleet_sanity_last_seen_counts`).
- Config fields + env overrides (`HYDRAFLOW_TRUST_FLEET_SANITY_INTERVAL`, `HYDRAFLOW_LOOP_ANOMALY_*`).
- Five-checkpoint wiring; loop-wiring-completeness test auto-covers.
- One MockWorld scenario + scenario-catalog builder.

## Spec

`docs/superpowers/specs/2026-04-22-trust-architecture-hardening-design.md` §12.1 / §12.2 / §12.3 / §12.4 / §3.2.

## Test plan

- [ ] `PYTHONPATH=src uv run pytest tests/test_state_trust_fleet_sanity.py -v`
- [ ] `PYTHONPATH=src uv run pytest tests/test_config_trust_fleet_sanity.py -v`
- [ ] `PYTHONPATH=src uv run pytest tests/test_trust_fleet_anomaly_detectors.py -v`
- [ ] `PYTHONPATH=src uv run pytest tests/test_trust_fleet_sanity_loop.py -v`
- [ ] `PYTHONPATH=src uv run pytest tests/test_health_monitor_sanity_stall.py -v`
- [ ] `PYTHONPATH=src uv run pytest tests/test_loop_wiring_completeness.py -v`
- [ ] `PYTHONPATH=src uv run pytest tests/scenarios/test_trust_fleet_sanity_scenario.py tests/scenarios/catalog/ -v`
- [ ] `make quality`

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
  ```

Return the PR URL to the user.

---

## Summary

Thirteen tasks landing one new loop (`TrustFleetSanityLoop`), one new helper module (five pure detector functions), one new state mixin (three `StateData` fields), six new config fields + env overrides, one `HealthMonitorLoop` extension (dead-man-switch), five-checkpoint wiring, one MockWorld scenario, one schema-contract doc constant for Plan 6b, and the standard test suite across four unit-test files.

## Spec

`docs/superpowers/specs/2026-04-22-trust-architecture-hardening-design.md` §12.1, §12.2, §12.3, §12.4, §3.2.

## Test plan

- [ ] Unit: state, config, detectors (×5), loop (skeleton, metrics, filing, escalation, reconcile, kill-switch, trace, schema), health-monitor dead-man-switch.
- [ ] Wiring: `test_loop_wiring_completeness.py` auto-covers.
- [ ] Scenario: `test_trust_fleet_sanity_scenario.py` — stale rc_budget heartbeat → staleness anomaly → `hitl-escalation` filed.
- [ ] `make quality`.

---

## Appendix — quick reference

| Decision | Value | Source |
|---|---|---|
| Worker name | `trust_fleet_sanity` | Spec §12.2 |
| Interval | `600s` (10m), bounds `60–3600` | Spec §12.1 |
| Issues-per-hour threshold | `10` | Spec §12.1 |
| Repair-ratio threshold | `2.0` | Spec §12.1 |
| Tick-error ratio threshold | `0.2` | Spec §12.1 |
| Staleness multiplier | `2.0` | Spec §12.1 |
| Cost-spike ratio | `5.0` | Spec §12.1 |
| Escalation attempts | `1` (anomaly IS escalation) | This plan §6 |
| Comparison | `>=` | Sibling plan |
| Dedup key | `trust_fleet_sanity:{kind}:{worker}` | Sibling plan format |
| Labels | `hitl-escalation`, `trust-loop-anomaly` | Spec §12.1 |
| Dead-man-switch multiplier | `3×` in HealthMonitor | This plan §15 |
| Dead-man-switch labels | `hydraflow-find`, `sanity-loop-stalled` | Spec §12.1 |
| Watched workers | 9 (spec §12.2 list) | Spec §12.2 |
| Metric windows | 1h / 24h | Spec §12.1 |
| Cost-reader module | `trust_fleet_cost_reader` (Plan 6b owns) | This plan §7 |
| DedupStore clear | `set_all(remaining)` | Sibling plan |
| Telemetry | `emit_loop_subprocess_trace` lazy-import | Sibling plan |
| Endpoint schema | `FLEET_ENDPOINT_SCHEMA` module constant | This plan §16 |
