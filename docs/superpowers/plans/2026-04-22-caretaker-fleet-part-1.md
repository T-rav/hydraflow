# Caretaker Fleet Part 1 — Flake + Skill-Eval + Fake-Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land three caretaker background loops (`FlakeTrackerLoop` §4.5, `SkillPromptEvalLoop` §4.6, `FakeCoverageAuditorLoop` §4.7) on the same pattern as `PrinciplesAuditLoop` (spec §4.4 — already planned). Each loop detects a specific class of trust rot, files `hydraflow-find` issues for the factory to repair, escalates after 3 attempts, and honors the §12.2 kill-switch contract.

**Architecture:** Three new `BaseBackgroundLoop` subclasses — `src/flake_tracker_loop.py` (4h cadence, reads JUnit XML from the last 20 RC runs via `gh api`), `src/skill_prompt_eval_loop.py` (weekly; dual role — full-corpus backstop + 10% weak-case sampling on `provenance: learning-loop` cases), `src/fake_coverage_auditor_loop.py` (weekly; AST introspection of `tests/scenarios/fakes/` vs cassette corpus under `tests/trust/contracts/cassettes/`). Each loop follows the Principles Audit blueprint: config `*_interval` + env override, `LoopDeps.enabled_cb(worker_name)` kill-switch (NOT a `*_enabled` config field), `PRManager.create_issue` for filing, `DedupStore` keyed per-detection with escalation at attempt 3 → `hitl-escalation` + `<loop>-stuck` label, telemetry via `trace_collector.emit_loop_subprocess_trace` (stubbed locally per the Plan 4 precedent if Plan 6 hasn't landed). State schemas add three `StateData` fields (`flake_counts`, `skill_prompt_last_green`, `fake_coverage_last_known`) plus per-loop attempt dicts. One MockWorld scenario per loop under `tests/scenarios/`. Five-checkpoint wiring (service registry, orchestrator `bg_loop_registry` + `loop_factories`, UI constants, dashboard interval bounds) lands per-loop in one task with five sub-steps.

**Tech Stack:** Python 3.11, `asyncio`, `pydantic` v2 (`StateData` fields), `ast` (stdlib parser for fake introspection), `xml.etree.ElementTree` (JUnit XML), `gh` CLI (artifact download + run list), `pytest`, `pytest-asyncio`, `MagicMock`/`AsyncMock`, GitHub Actions.

**Spec refs:** `docs/superpowers/specs/2026-04-22-trust-architecture-hardening-design.md` §4.5 (FlakeTracker), §4.6 (SkillPromptEval), §4.7 (FakeCoverageAuditor), §3.2 (escalation lifecycle + kill-switch), §12.2 (worker_name registry — `flake_tracker`, `skill_prompt_eval`, `fake_coverage_auditor`), §6 (fail-mode rows), §7 (unit tests).

**Dependencies from sibling plans:**

- §4.1 adversarial skill corpus — `2026-04-22-adversarial-skill-corpus.md`. §4.6 assumes `make trust-adversarial` exists and the corpus YAML cases carry a `provenance` field.
- §4.2 cassette infrastructure — `2026-04-22-fake-contract-tests.md`. §4.7 reads `tests/trust/contracts/cassettes/<adapter>/*.json` laid out by that plan.
- §4.4 PrinciplesAuditLoop — `2026-04-22-principles-audit-loop.md`. Sets the template; Tasks share the `trace_collector.emit_loop_subprocess_trace` stub (do not re-add if already present on this branch).

**Decisions locked in this plan (spec deferred or implied):**

1. **JUnit artifact upload is a prerequisite.** RC workflow (`.github/workflows/rc-promotion-scenario.yml`) currently runs `make scenario` / `make scenario-loops` without `--junitxml`. Task F0 adds `pytest --junitxml` plus `actions/upload-artifact@v4` for the artifact name `junit-scenario` / `junit-scenario-loops`. Without this the loop has nothing to read.
2. **20-run window.** `flake_counts[test_name]` is a monotonically increasing counter over the **last 20** RC runs; the loop recomputes from fresh artifact downloads each tick (no hysteresis) and overwrites state. This keeps the detector idempotent: a long-fixed test decays out of the window in 20 runs.
3. **Flake threshold = 3 with `>=`.** Spec §4.5 prose says "3 fails in 20 runs triggers"; the comparison must be `count >= threshold` so threshold=3 fires at exactly 3 occurrences, not 4.
4. **Skill-prompt eval subprocess.** `make trust-adversarial --format=json` is assumed to emit a JSON array of `{case_id, skill, status: PASS|FAIL, provenance, expected_catcher}` records on stdout. If the command does not yet accept `--format=json`, the runner wrapper (`scripts/trust_adversarial.py`, owned by Plan 1) supplies that flag — a dependency not a precondition for *this* plan's code to be correct, but the scenario test monkey-patches the subprocess so the test is green regardless.
5. **Weak-case sampling.** 10% of cases with `provenance == "learning-loop"`, minimum 1, using a seed-stable `random.Random(state.workflow_run_id)` so reruns hit the same cases within a tick.
6. **Skill-prompt snapshot schema.** `skill_prompt_last_green: dict[str, Literal["PASS", "FAIL"]]` keyed on `case_id`. Compared set-wise each run; `PASS → FAIL` transitions file `skill-prompt-drift` issues.
7. **Fake coverage — two method sets, two subtype labels.** `adapter-surface` (public non-private methods that mirror a real adapter) vs `test-helper` (names matching the allow-list `script_*`, `fail_service`, `heal_service`, `set_state`). One issue per gap, carrying the subtype label plus `fake-coverage-gap`.
8. **Cassette method extraction.** Each cassette JSON has a top-level `input.command` string — the real-adapter method name. The loop treats that as the truth source for surface coverage.
9. **Test-helper coverage = grep.** A `ripgrep` subprocess scanning `tests/scenarios/` for `<helper_name>\s*\(` is sufficient; AST-level precision is not required because helpers are named conventionally and false positives (e.g., a comment) only prevent the loop from firing — not a correctness failure.
10. **Escalation key shape.** Shared across all three: `f"{worker_name}:{subject}"` — respectively `flake_tracker:{test_name}`, `skill_prompt_eval:{case_id}`, and `fake_coverage_auditor:{fake}.{method}:{subtype}`.
11. **3-attempt escalation is uniform.** Spec §4.5–§4.7 all specify 3 — no special-casing for severity. When attempts reach 3, the loop files a second issue labeled `hitl-escalation` and `<loop>-stuck` (`flaky-test-stuck`, `skill-prompt-stuck`, `fake-coverage-stuck`).
12. **Dedup clearance on close.** Spec §3.2 mandates a polling close-handler per-loop. Implemented as a small helper `_reconcile_closed_escalations` called at the top of each tick that calls `gh issue list --state=closed --label=hitl-escalation --author=@me --search=<worker_name>` and removes matching keys from the dedup store using `DedupStore.set_all(remaining)` (no `remove` method exists today).
13. **Telemetry helper stub reuse.** If Plan 4 (Principles) already landed `emit_loop_subprocess_trace` in `src/trace_collector.py`, all three new loops import it directly. If not, Task F3 re-checks and skips if present; otherwise adds the same stub per the Principles plan's Task 18.

---

## File Structure

| File | Role | Created / Modified |
|---|---|---|
| `src/models.py` | `StateData` fields: `flake_counts: dict[str, int]`, `flake_attempts: dict[str, int]`, `skill_prompt_last_green: dict[str, str]`, `skill_prompt_attempts: dict[str, int]`, `fake_coverage_last_known: dict[str, list[str]]`, `fake_coverage_attempts: dict[str, int]` — appended near the existing `code_grooming_filed` entry at `src/models.py:1754-1767` | Modify |
| `src/state/_flake_tracker.py` | New `FlakeTrackerStateMixin` — `get_flake_counts`, `set_flake_counts`, `inc_flake_attempts`, `get_flake_attempts` | Create |
| `src/state/_skill_prompt_eval.py` | New `SkillPromptEvalStateMixin` — `get_skill_prompt_last_green`, `set_skill_prompt_last_green`, attempt getters/incrementers | Create |
| `src/state/_fake_coverage.py` | New `FakeCoverageStateMixin` — `get_fake_coverage_last_known`, `set_fake_coverage_last_known`, attempt getters/incrementers | Create |
| `src/state/__init__.py` | Import three mixins (line 28-46) + add to `StateTracker` MRO (line 55-75) | Modify |
| `src/config.py` | Three interval fields + three env-override rows in `_INT_ENV_OVERRIDES` (line 164-174) + `flake_threshold` field | Modify |
| `src/flake_tracker_loop.py` | New loop — JUnit reader + counter + issue filer + escalation + close-reconcile | Create |
| `src/skill_prompt_eval_loop.py` | New loop — full-corpus backstop + weak-case sampling | Create |
| `src/fake_coverage_auditor_loop.py` | New loop — AST fake introspection + cassette catalog + grep scan | Create |
| `src/orchestrator.py` | Three entries each in `bg_loop_registry` (line 138-159) and `loop_factories` (line 879-910) | Modify |
| `src/service_registry.py` | Three loop fields + three constructor blocks + keyword args in the final `ServiceRegistry(...)` call (line 806-871) | Modify |
| `src/ui/src/constants.js` | Three entries each in `BACKGROUND_WORKERS`, `SYSTEM_WORKER_INTERVALS`, `EDITABLE_INTERVAL_WORKERS` | Modify |
| `src/dashboard_routes/_common.py` | Three entries in `_INTERVAL_BOUNDS` (line 32) | Modify |
| `.github/workflows/rc-promotion-scenario.yml` | Add `--junitxml=<path>` to scenario + scenario-loops steps + `actions/upload-artifact@v4` blocks | Modify |
| `Makefile` | `scenario` / `scenario-loops` targets pass `--junitxml=<path>` when `JUNIT_DIR` env is set | Modify |
| `tests/test_state_flake_tracker.py` | Mixin unit tests | Create |
| `tests/test_state_skill_prompt_eval.py` | Mixin unit tests | Create |
| `tests/test_state_fake_coverage.py` | Mixin unit tests | Create |
| `tests/test_flake_tracker_loop.py` | Loop unit tests (skeleton, tick, filing, escalation, close-reconcile) | Create |
| `tests/test_skill_prompt_eval_loop.py` | Loop unit tests | Create |
| `tests/test_fake_coverage_auditor_loop.py` | Loop unit tests | Create |
| `tests/scenarios/test_flake_tracker_scenario.py` | MockWorld scenario — 20 RC runs with one flaky test | Create |
| `tests/scenarios/test_skill_prompt_eval_scenario.py` | MockWorld scenario — corpus drift + weak-case sampling | Create |
| `tests/scenarios/test_fake_coverage_scenario.py` | MockWorld scenario — uncovered fake method surfaces | Create |
| `tests/test_loop_wiring_completeness.py` | Auto-discovers new loops via regex — verified at Step *.5 of each wiring task | Covered |

---

## Phase 1 — FlakeTrackerLoop (§4.5)

### Task F0: Verify RC workflow emits JUnit XML; add upload step if missing

**Files:**
- Modify: `.github/workflows/rc-promotion-scenario.yml:91-95` (scenario + scenario-loops steps)
- Modify: `Makefile:210-218` (scenario + scenario-loops targets)

Spec §4.5 step 1 requires the loop read pytest JUnit XML from RC artifacts. Currently `make scenario` / `make scenario-loops` do not write JUnit XML and the workflow uploads no scenario artifacts. This task is a hard prerequisite.

- [ ] **Step 1: Confirm no JUnit upload exists today**

```bash
grep -n "junitxml\|junit" .github/workflows/rc-promotion-scenario.yml Makefile
```

Expected: no matches. If matches appear, inspect and adapt — the loop code in Task F3 will use whatever artifact name the workflow exports.

- [ ] **Step 2: Extend the Makefile to honor `JUNIT_DIR`**

Modify `Makefile:210-218` — replace the `scenario` and `scenario-loops` recipes:

```make
scenario: deps
	@echo "$(BLUE)Running scenario tests...$(RESET)"
	@mkdir -p $(if $(JUNIT_DIR),$(JUNIT_DIR),.)
	@cd $(HYDRAFLOW_DIR) && PYTHONPATH=src $(UV) pytest tests/scenarios/ -m scenario -v \
		$(if $(JUNIT_DIR),--junitxml=$(JUNIT_DIR)/junit-scenario.xml,)
	@echo "$(GREEN)Scenario tests passed$(RESET)"

scenario-loops: deps
	@echo "$(BLUE)Running scenario loop tests...$(RESET)"
	@mkdir -p $(if $(JUNIT_DIR),$(JUNIT_DIR),.)
	@cd $(HYDRAFLOW_DIR) && PYTHONPATH=src $(UV) pytest tests/scenarios/ -m scenario_loops -v \
		$(if $(JUNIT_DIR),--junitxml=$(JUNIT_DIR)/junit-scenario-loops.xml,)
	@echo "$(GREEN)Scenario loop tests passed$(RESET)"
```

- [ ] **Step 3: Extend the RC workflow to emit + upload JUnit XML**

Modify `.github/workflows/rc-promotion-scenario.yml:89-95` — replace the `Scenario suite` + `Scenario loops suite` steps within the `scenario` job:

```yaml
      - name: Install dependencies
        run: uv sync --all-extras
      - name: Scenario suite
        run: make scenario JUNIT_DIR=${{ github.workspace }}/junit
      - name: Scenario loops suite
        run: make scenario-loops JUNIT_DIR=${{ github.workspace }}/junit
      - name: Upload JUnit artifacts
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: junit-scenario
          path: junit/*.xml
          retention-days: 14
```

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/rc-promotion-scenario.yml Makefile
git commit -m "ci(rc): emit pytest --junitxml and upload junit-scenario artifact (§4.5 prereq)"
```

---

### Task F1: Add flake-tracker state fields + mixin

**Files:**
- Modify: `src/models.py:1754-1767` (append fields to `StateData`)
- Create: `src/state/_flake_tracker.py`
- Modify: `src/state/__init__.py` (import + MRO)
- Create: `tests/test_state_flake_tracker.py`

- [ ] **Step 1: Write the failing mixin test**

Create `tests/test_state_flake_tracker.py`:

```python
"""Tests for FlakeTrackerStateMixin."""

from __future__ import annotations

from pathlib import Path

from state import StateTracker


def _tracker(tmp_path: Path) -> StateTracker:
    return StateTracker(state_file=tmp_path / "state.json")


def test_set_and_get_flake_counts(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    st.set_flake_counts({"tests/foo.py::test_bar": 4})
    assert st.get_flake_counts() == {"tests/foo.py::test_bar": 4}


def test_inc_flake_attempts_is_monotonic(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    assert st.get_flake_attempts("tests/foo.py::test_bar") == 0
    st.inc_flake_attempts("tests/foo.py::test_bar")
    st.inc_flake_attempts("tests/foo.py::test_bar")
    assert st.get_flake_attempts("tests/foo.py::test_bar") == 2


def test_clear_flake_attempts(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    st.inc_flake_attempts("tests/foo.py::test_bar")
    st.clear_flake_attempts("tests/foo.py::test_bar")
    assert st.get_flake_attempts("tests/foo.py::test_bar") == 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
PYTHONPATH=src uv run pytest tests/test_state_flake_tracker.py -v
```

Expected: FAIL — `AttributeError: 'StateTracker' object has no attribute 'set_flake_counts'`.

- [ ] **Step 3: Add StateData fields**

Modify `src/models.py:1757` — after `code_grooming_filed: list[str] = Field(default_factory=list)`, insert:

```python
    # Trust fleet — caretaker loops (Plan 5)
    flake_counts: dict[str, int] = Field(default_factory=dict)
    flake_attempts: dict[str, int] = Field(default_factory=dict)
    skill_prompt_last_green: dict[str, str] = Field(default_factory=dict)
    skill_prompt_attempts: dict[str, int] = Field(default_factory=dict)
    fake_coverage_last_known: dict[str, list[str]] = Field(default_factory=dict)
    fake_coverage_attempts: dict[str, int] = Field(default_factory=dict)
```

- [ ] **Step 4: Create the mixin**

Create `src/state/_flake_tracker.py`:

```python
"""State accessors for FlakeTrackerLoop (spec §4.5)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import StateData


class FlakeTrackerStateMixin:
    """Flake counts + per-test repair attempts."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    def get_flake_counts(self) -> dict[str, int]:
        return dict(self._data.flake_counts)

    def set_flake_counts(self, counts: dict[str, int]) -> None:
        self._data.flake_counts = dict(counts)
        self.save()

    def get_flake_attempts(self, test_name: str) -> int:
        return int(self._data.flake_attempts.get(test_name, 0))

    def inc_flake_attempts(self, test_name: str) -> int:
        current = int(self._data.flake_attempts.get(test_name, 0)) + 1
        attempts = dict(self._data.flake_attempts)
        attempts[test_name] = current
        self._data.flake_attempts = attempts
        self.save()
        return current

    def clear_flake_attempts(self, test_name: str) -> None:
        attempts = dict(self._data.flake_attempts)
        attempts.pop(test_name, None)
        self._data.flake_attempts = attempts
        self.save()
```

- [ ] **Step 5: Register the mixin**

Modify `src/state/__init__.py:28-46` — add import:

```python
from ._flake_tracker import FlakeTrackerStateMixin
```

Modify `src/state/__init__.py:55-75` — add `FlakeTrackerStateMixin` to the `StateTracker` MRO (append before the closing `):`). Example:

```python
class StateTracker(
    IssueStateMixin,
    WorkspaceStateMixin,
    # ... existing mixins unchanged ...
    TraceRunsMixin,
    FlakeTrackerStateMixin,
):
```

- [ ] **Step 6: Run test to verify it passes**

```bash
PYTHONPATH=src uv run pytest tests/test_state_flake_tracker.py -v
```

Expected: 3 PASS.

- [ ] **Step 7: Commit**

```bash
git add src/models.py src/state/_flake_tracker.py src/state/__init__.py tests/test_state_flake_tracker.py
git commit -m "feat(state): FlakeTrackerStateMixin + flake_counts/flake_attempts fields (§4.5)"
```

---

### Task F2: Add `flake_tracker_interval` + `flake_threshold` config + env override

**Files:**
- Modify: `src/config.py:164-174` (`_INT_ENV_OVERRIDES`)
- Modify: `src/config.py` at the HydraFlowConfig field block (immediately after `retrospective_interval` ~line 1619)

- [ ] **Step 1: Write the failing config test**

Create (or append to) `tests/test_config_caretaker_fleet.py`:

```python
"""Tests for caretaker-fleet config fields (Plan 5)."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from config import HydraFlowConfig


def test_flake_tracker_interval_default() -> None:
    cfg = HydraFlowConfig()
    assert cfg.flake_tracker_interval == 14400
    assert cfg.flake_threshold == 3


def test_flake_tracker_interval_env_override() -> None:
    with patch.dict(os.environ, {"HYDRAFLOW_FLAKE_TRACKER_INTERVAL": "3600"}):
        cfg = HydraFlowConfig.from_env()
        assert cfg.flake_tracker_interval == 3600


def test_flake_tracker_interval_bounds() -> None:
    with pytest.raises(ValueError):
        HydraFlowConfig(flake_tracker_interval=30)  # below 3600 minimum
    with pytest.raises(ValueError):
        HydraFlowConfig(flake_tracker_interval=10_000_000)  # above 30d
```

- [ ] **Step 2: Run test to verify it fails**

```bash
PYTHONPATH=src uv run pytest tests/test_config_caretaker_fleet.py -v
```

Expected: FAIL — `flake_tracker_interval` not defined.

- [ ] **Step 3: Add the config fields**

Modify `src/config.py` — immediately after the `retrospective_interval` field (~line 1614-1619), insert:

```python
    # Trust fleet — FlakeTrackerLoop (spec §4.5)
    flake_tracker_interval: int = Field(
        default=14400,
        ge=3600,
        le=2_592_000,
        description="Seconds between FlakeTrackerLoop ticks (default 4h)",
    )
    flake_threshold: int = Field(
        default=3,
        ge=2,
        le=20,
        description="Flake count in last 20 runs that triggers an issue (>=)",
    )
```

- [ ] **Step 4: Add env override**

Modify `src/config.py:174` — append to `_INT_ENV_OVERRIDES`:

```python
    ("flake_tracker_interval", "HYDRAFLOW_FLAKE_TRACKER_INTERVAL", 14400),
    ("flake_threshold", "HYDRAFLOW_FLAKE_THRESHOLD", 3),
```

- [ ] **Step 5: Run test to verify it passes**

```bash
PYTHONPATH=src uv run pytest tests/test_config_caretaker_fleet.py::test_flake_tracker_interval_default tests/test_config_caretaker_fleet.py::test_flake_tracker_interval_env_override tests/test_config_caretaker_fleet.py::test_flake_tracker_interval_bounds -v
```

Expected: 3 PASS.

- [ ] **Step 6: Commit**

```bash
git add src/config.py tests/test_config_caretaker_fleet.py
git commit -m "feat(config): flake_tracker_interval + flake_threshold + env overrides (§4.5)"
```

---

### Task F3: `FlakeTrackerLoop` skeleton + JUnit parsing helper

**Files:**
- Create: `src/flake_tracker_loop.py`
- Create: `tests/test_flake_tracker_loop.py`

This task creates the shell plus the pure-function JUnit parser that the tick will call. Keep the tick body thin — subsequent tasks fill it in.

- [ ] **Step 1: Write the failing test**

Create `tests/test_flake_tracker_loop.py`:

```python
"""Tests for FlakeTrackerLoop (spec §4.5)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus
from flake_tracker_loop import FlakeTrackerLoop, parse_junit_xml


def _deps(stop: asyncio.Event) -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: True,
    )


@pytest.fixture
def loop_env(tmp_path: Path):
    cfg = HydraFlowConfig(data_root=tmp_path, repo="hydra/hydraflow")
    state = MagicMock()
    state.get_flake_counts.return_value = {}
    state.get_flake_attempts.return_value = 0
    pr_manager = AsyncMock()
    pr_manager.create_issue = AsyncMock(return_value=42)
    dedup = MagicMock()
    dedup.get.return_value = set()
    return cfg, state, pr_manager, dedup


def test_skeleton_worker_name_and_interval(loop_env) -> None:
    cfg, state, pr, dedup = loop_env
    stop = asyncio.Event()
    loop = FlakeTrackerLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )
    assert loop._worker_name == "flake_tracker"
    assert loop._get_default_interval() == 14400


def test_parse_junit_xml_counts_failures_per_test() -> None:
    xml = b"""<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest">
    <testcase classname="tests.scenarios" name="test_alpha" />
    <testcase classname="tests.scenarios" name="test_bravo">
      <failure message="AssertionError"/>
    </testcase>
    <testcase classname="tests.scenarios" name="test_charlie">
      <error message="Timeout"/>
    </testcase>
  </testsuite>
</testsuites>
"""
    results = parse_junit_xml(xml)
    assert results == {
        "tests.scenarios.test_alpha": "pass",
        "tests.scenarios.test_bravo": "fail",
        "tests.scenarios.test_charlie": "fail",
    }
```

- [ ] **Step 2: Run test to verify it fails**

```bash
PYTHONPATH=src uv run pytest tests/test_flake_tracker_loop.py -v
```

Expected: FAIL — `ImportError: cannot import name 'FlakeTrackerLoop'`.

- [ ] **Step 3: Create the loop skeleton + parser**

Create `src/flake_tracker_loop.py`:

```python
"""FlakeTrackerLoop — 4h detector for persistently flaky tests.

Spec: `docs/superpowers/specs/2026-04-22-trust-architecture-hardening-design.md`
§4.5. Reads JUnit XML from the last 20 RC runs (uploaded by
`rc-promotion-scenario.yml`), counts mixed pass/fail occurrences per
test, and files a `hydraflow-find` + `flaky-test` issue when a test's
flake count crosses `flake_threshold` (default 3, comparison `>=`).

After 3 repair attempts for the same test_name the loop files a
second issue labeled `hitl-escalation` + `flaky-test-stuck`. The
dedup key clears when the escalation issue is closed (spec §3.2).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from models import WorkCycleResult

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from dedup_store import DedupStore
    from pr_manager import PRManager
    from state import StateTracker

logger = logging.getLogger("hydraflow.flake_tracker_loop")

_MAX_ATTEMPTS = 3
_RUN_WINDOW = 20


def parse_junit_xml(xml_bytes: bytes) -> dict[str, str]:
    """Return ``{test_id: "pass"|"fail"}`` per test case in a JUnit XML doc.

    ``test_id`` is ``{classname}.{name}``. A testcase is ``fail`` if it
    has any ``<failure>`` or ``<error>`` child element; ``skip`` is
    treated as ``pass`` (skipped tests are not flakes).
    """
    results: dict[str, str] = {}
    root = ET.fromstring(xml_bytes)
    for case in root.iter("testcase"):
        cls = case.get("classname") or ""
        name = case.get("name") or ""
        test_id = f"{cls}.{name}".lstrip(".")
        failed = any(
            c.tag in ("failure", "error") for c in case
        )
        results[test_id] = "fail" if failed else "pass"
    return results


class FlakeTrackerLoop(BaseBackgroundLoop):
    """Detects persistently flaky tests in the RC window (spec §4.5)."""

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
            worker_name="flake_tracker",
            config=config,
            deps=deps,
            run_on_startup=False,
        )
        self._state = state
        self._pr = pr_manager
        self._dedup = dedup

    def _get_default_interval(self) -> int:
        return self._config.flake_tracker_interval

    async def _do_work(self) -> WorkCycleResult:
        """Skeleton — subsequent tasks fill in the tick."""
        return {"status": "noop"}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
PYTHONPATH=src uv run pytest tests/test_flake_tracker_loop.py::test_skeleton_worker_name_and_interval tests/test_flake_tracker_loop.py::test_parse_junit_xml_counts_failures_per_test -v
```

Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/flake_tracker_loop.py tests/test_flake_tracker_loop.py
git commit -m "feat(loop): FlakeTrackerLoop skeleton + JUnit parser (§4.5)"
```

---

### Task F4: RC artifact downloader + tick logic

**Files:**
- Modify: `src/flake_tracker_loop.py` — add `_fetch_recent_runs`, `_download_junit`, `_tally_flakes`, and full `_do_work`
- Modify: `tests/test_flake_tracker_loop.py` — add tick-behavior tests

- [ ] **Step 1: Write the failing test**

Append to `tests/test_flake_tracker_loop.py`:

```python
async def test_tally_flakes_counts_mixed_results(loop_env) -> None:
    cfg, state, pr, dedup = loop_env
    stop = asyncio.Event()
    loop = FlakeTrackerLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )
    # Three runs: alpha always passes, bravo fails twice, charlie fails once.
    runs = [
        {"tests.scenarios.test_alpha": "pass", "tests.scenarios.test_bravo": "fail"},
        {"tests.scenarios.test_alpha": "pass", "tests.scenarios.test_bravo": "fail"},
        {"tests.scenarios.test_alpha": "pass", "tests.scenarios.test_charlie": "fail"},
    ]
    counts = loop._tally_flakes(runs)
    assert counts["tests.scenarios.test_bravo"] == 2
    assert counts["tests.scenarios.test_charlie"] == 1
    assert "tests.scenarios.test_alpha" not in counts  # no failures recorded


async def test_do_work_files_issue_when_threshold_hit(loop_env, monkeypatch) -> None:
    cfg, state, pr, dedup = loop_env
    stop = asyncio.Event()
    loop = FlakeTrackerLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )

    fake_runs = [
        {"tests.foo.test_flake": "fail"},
        {"tests.foo.test_flake": "pass"},
        {"tests.foo.test_flake": "fail"},
        {"tests.foo.test_flake": "fail"},
    ]

    async def fake_fetch():
        return [{"databaseId": i, "url": f"u{i}"} for i in range(len(fake_runs))]

    async def fake_download(run):
        return fake_runs[run["databaseId"]]

    async def fake_reconcile():
        return None

    monkeypatch.setattr(loop, "_fetch_recent_runs", fake_fetch)
    monkeypatch.setattr(loop, "_download_junit", fake_download)
    monkeypatch.setattr(loop, "_reconcile_closed_escalations", fake_reconcile)

    stats = await loop._do_work()
    assert stats["filed"] == 1
    title = pr.create_issue.await_args.args[0]
    assert "test_flake" in title
    labels = pr.create_issue.await_args.args[2]
    assert "flaky-test" in labels
```

- [ ] **Step 2: Run test to verify it fails**

```bash
PYTHONPATH=src uv run pytest tests/test_flake_tracker_loop.py::test_tally_flakes_counts_mixed_results tests/test_flake_tracker_loop.py::test_do_work_files_issue_when_threshold_hit -v
```

Expected: FAIL — `_tally_flakes` and full tick do not exist.

- [ ] **Step 3: Implement the tick**

Append to `src/flake_tracker_loop.py` inside `FlakeTrackerLoop`:

```python
    async def _fetch_recent_runs(self) -> list[dict[str, Any]]:
        """Return metadata for the last 20 RC promotion workflow runs."""
        cmd = [
            "gh", "run", "list",
            "--repo", self._config.repo,
            "--workflow", "rc-promotion-scenario.yml",
            "--limit", str(_RUN_WINDOW),
            "--json", "databaseId,url,conclusion,createdAt",
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
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
            return json.loads(stdout.decode() or "[]")
        except json.JSONDecodeError:
            logger.warning("gh run list non-JSON response; returning empty")
            return []

    async def _download_junit(self, run: dict[str, Any]) -> dict[str, str]:
        """Download the `junit-scenario` artifact for a run; return per-test results."""
        run_id = str(run.get("databaseId", ""))
        if not run_id:
            return {}
        # Use `gh run download` to a scratch dir, then read all *.xml files.
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as td:
            cmd = [
                "gh", "run", "download", run_id,
                "--repo", self._config.repo,
                "--name", "junit-scenario",
                "--dir", td,
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.info(
                    "no junit-scenario artifact for run %s: %s",
                    run_id, stderr.decode(errors="replace")[:200],
                )
                return {}
            combined: dict[str, str] = {}
            for xml_path in Path(td).rglob("*.xml"):
                try:
                    combined.update(parse_junit_xml(xml_path.read_bytes()))
                except ET.ParseError:
                    logger.debug("junit parse failed: %s", xml_path)
                    continue
            return combined

    def _tally_flakes(self, runs: list[dict[str, str]]) -> dict[str, int]:
        """Count fails per test across runs. Only tests with mixed pass+fail counted."""
        pass_tests: set[str] = set()
        fail_counts: dict[str, int] = {}
        for run in runs:
            for test_id, result in run.items():
                if result == "pass":
                    pass_tests.add(test_id)
                elif result == "fail":
                    fail_counts[test_id] = fail_counts.get(test_id, 0) + 1
        # A test that only ever failed isn't a flake — it's a broken test.
        # A test that only ever passed is clean. Both are filtered out.
        return {
            test: count
            for test, count in fail_counts.items()
            if test in pass_tests
        }

    async def _file_flake_issue(
        self, test_id: str, flake_count: int, runs: list[dict[str, Any]]
    ) -> int:
        """File a `hydraflow-find` + `flaky-test` issue. Returns the issue number."""
        title = f"Flaky test: {test_id} (flake rate: {flake_count}/{_RUN_WINDOW})"
        run_lines = "\n".join(
            f"- {r.get('url', '?')} ({r.get('createdAt', '?')})"
            for r in runs[:10]
        )
        body = (
            f"## Flake signal\n\n"
            f"Test `{test_id}` failed in {flake_count} of the last {_RUN_WINDOW} "
            f"RC promotion runs. This loop (`flake_tracker`, spec §4.5) filed "
            f"the issue so the standard implementer/reviewer pipeline can fix "
            f"the race, add a deterministic wait, or quarantine the test.\n\n"
            f"### Recent runs (up to 10)\n{run_lines}\n\n"
            f"_This issue was auto-filed by HydraFlow's `flake_tracker` loop._"
        )
        return await self._pr.create_issue(
            title, body, ["hydraflow-find", "flaky-test"]
        )

    async def _file_escalation(self, test_id: str, attempts: int) -> int:
        """File `hitl-escalation` + `flaky-test-stuck` after N failed repairs."""
        title = f"HITL: flaky test {test_id} unresolved after {attempts} attempts"
        body = (
            f"`flake_tracker` has filed `flaky-test` issues for `{test_id}` "
            f"{attempts} times without closure. Human review needed.\n\n"
            f"_Spec §3.2 escalation lifecycle: close this issue to clear the "
            f"dedup key and let the loop re-fire on the next drift._"
        )
        return await self._pr.create_issue(
            title, body, ["hitl-escalation", "flaky-test-stuck"]
        )

    async def _reconcile_closed_escalations(self) -> None:
        """Clear dedup keys whose escalation issue has been closed (spec §3.2)."""
        cmd = [
            "gh", "issue", "list",
            "--repo", self._config.repo,
            "--state", "closed",
            "--label", "hitl-escalation",
            "--label", "flaky-test-stuck",
            "--author", "@me",
            "--limit", "100",
            "--json", "title",
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
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
            # Title shape: "HITL: flaky test <id> unresolved after N attempts"
            for key in list(keep):
                if key.startswith("flake_tracker:") and key.split(":", 1)[1] in title:
                    keep.discard(key)
                    self._state.clear_flake_attempts(key.split(":", 1)[1])
        if keep != current:
            self._dedup.set_all(keep)

    async def _do_work(self) -> WorkCycleResult:
        """One flake-tracking cycle (spec §4.5)."""
        t0 = time.perf_counter()
        await self._reconcile_closed_escalations()

        runs = await self._fetch_recent_runs()
        if not runs:
            return {"status": "no_runs", "filed": 0}

        per_run_results: list[dict[str, str]] = []
        for run in runs:
            per_run_results.append(await self._download_junit(run))

        counts = self._tally_flakes(per_run_results)
        self._state.set_flake_counts(counts)

        threshold = self._config.flake_threshold
        filed = 0
        escalated = 0
        dedup = self._dedup.get()
        for test_id, count in counts.items():
            if count < threshold:
                continue
            key = f"flake_tracker:{test_id}"
            if key in dedup:
                continue
            attempts = self._state.inc_flake_attempts(test_id)
            if attempts >= _MAX_ATTEMPTS:
                await self._file_escalation(test_id, attempts)
                escalated += 1
            else:
                await self._file_flake_issue(test_id, count, runs)
                filed += 1
            dedup.add(key)
            self._dedup.set_all(dedup)

        self._emit_trace(t0, runs_seen=len(runs))
        return {"status": "ok", "filed": filed, "escalated": escalated,
                "tests_seen": len(counts)}

    def _emit_trace(self, t0: float, *, runs_seen: int) -> None:
        try:
            from trace_collector import emit_loop_subprocess_trace  # noqa: PLC0415
        except ImportError:
            return
        emit_loop_subprocess_trace(
            worker_name=self._worker_name,
            command=["gh", "run", "list", "rc-promotion-scenario.yml"],
            exit_code=0,
            duration_s=time.perf_counter() - t0,
            stdout_tail=f"runs_seen={runs_seen}",
            stderr_tail="",
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
PYTHONPATH=src uv run pytest tests/test_flake_tracker_loop.py -v
```

Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/flake_tracker_loop.py tests/test_flake_tracker_loop.py
git commit -m "feat(loop): FlakeTracker tick + GH artifact download + filing (§4.5)"
```

---

### Task F5: Escalation + dedup-close reconcile tests

**Files:**
- Modify: `tests/test_flake_tracker_loop.py` — add escalation + close-reconcile tests

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_flake_tracker_loop.py`:

```python
async def test_escalation_fires_after_three_attempts(loop_env, monkeypatch) -> None:
    cfg, state, pr, dedup = loop_env
    state.get_flake_attempts.return_value = 2  # next inc → 3
    state.inc_flake_attempts.return_value = 3
    stop = asyncio.Event()
    loop = FlakeTrackerLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )

    async def fake_fetch():
        return [{"databaseId": 0, "url": "u"}]

    async def fake_dl(_):
        return {"tests.scenarios.test_bad": "fail",
                "tests.scenarios.test_other": "pass"}

    async def fake_reconcile():
        return None

    # Threshold=1 so a single fail-in-mixed-set triggers.
    cfg.flake_threshold = 1
    monkeypatch.setattr(loop, "_fetch_recent_runs", fake_fetch)
    monkeypatch.setattr(loop, "_download_junit", fake_dl)
    monkeypatch.setattr(loop, "_reconcile_closed_escalations", fake_reconcile)

    stats = await loop._do_work()
    assert stats["escalated"] == 1
    labels = pr.create_issue.await_args.args[2]
    assert "hitl-escalation" in labels
    assert "flaky-test-stuck" in labels


async def test_reconcile_closed_escalations_clears_dedup(loop_env, monkeypatch) -> None:
    cfg, state, pr, dedup = loop_env
    dedup.get.return_value = {"flake_tracker:tests.foo.test_bar"}
    stop = asyncio.Event()
    loop = FlakeTrackerLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )

    class FakeProc:
        returncode = 0

        async def communicate(self):
            return (
                b'[{"title": "HITL: flaky test tests.foo.test_bar unresolved after 3 attempts"}]',
                b"",
            )

    async def fake_subproc(*args, **kwargs):
        return FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subproc)

    await loop._reconcile_closed_escalations()
    dedup.set_all.assert_called_once()
    remaining = dedup.set_all.call_args.args[0]
    assert "flake_tracker:tests.foo.test_bar" not in remaining
    state.clear_flake_attempts.assert_called_once_with("tests.foo.test_bar")
```

- [ ] **Step 2: Run tests to verify they pass**

```bash
PYTHONPATH=src uv run pytest tests/test_flake_tracker_loop.py::test_escalation_fires_after_three_attempts tests/test_flake_tracker_loop.py::test_reconcile_closed_escalations_clears_dedup -v
```

Expected: 2 PASS (tick logic from Task F4 already supports the assertions).

- [ ] **Step 3: Commit**

```bash
git add tests/test_flake_tracker_loop.py
git commit -m "test(loop): FlakeTracker escalation + dedup close-reconcile (§3.2 + §4.5)"
```

---

### Task F6: Five-checkpoint wiring for `flake_tracker`

All five sub-steps use the exact string `flake_tracker`. `tests/test_loop_wiring_completeness.py` auto-discovers via regex, so the five touchpoints must agree verbatim.

- [ ] **Step 1: `src/service_registry.py`**

Modify `src/service_registry.py:63` — add import:

```python
from flake_tracker_loop import FlakeTrackerLoop  # noqa: TCH001
```

Modify `src/service_registry.py:168` area — append to the `ServiceRegistry` dataclass:

```python
    flake_tracker_loop: FlakeTrackerLoop
```

Modify `src/service_registry.py` — inside `build_services`, immediately after the `retrospective_loop = RetrospectiveLoop(...)` block at line 806-813, add:

```python
    flake_tracker_dedup = DedupStore(
        "flake_tracker",
        config.data_root / "dedup" / "flake_tracker.json",
    )
    flake_tracker_loop = FlakeTrackerLoop(  # noqa: F841
        config=config,
        state=state,
        pr_manager=prs,
        dedup=flake_tracker_dedup,
        deps=loop_deps,
    )
```

In the final `ServiceRegistry(...)` call (around line 815-871), append:

```python
        flake_tracker_loop=flake_tracker_loop,
```

Commit:

```bash
git add src/service_registry.py
git commit -m "feat(wiring): FlakeTrackerLoop + DedupStore in service registry"
```

- [ ] **Step 2: `src/orchestrator.py`**

Modify `src/orchestrator.py:159` — append in `bg_loop_registry`:

```python
            "flake_tracker": svc.flake_tracker_loop,
```

Modify `src/orchestrator.py:909` — append in `loop_factories`:

```python
            ("flake_tracker", self._svc.flake_tracker_loop.run),
```

Commit:

```bash
git add src/orchestrator.py
git commit -m "feat(wiring): orchestrator runs FlakeTrackerLoop + registers worker"
```

- [ ] **Step 3: `src/ui/src/constants.js`**

Modify `src/ui/src/constants.js`:

1. Line 252 (`EDITABLE_INTERVAL_WORKERS`): add `'flake_tracker'` to the Set literal.
2. Line 259-274 (`SYSTEM_WORKER_INTERVALS`): add `flake_tracker: 14400,`.
3. Line 293-313 (`BACKGROUND_WORKERS`): append:

```js
  { key: 'flake_tracker', label: 'Flake Tracker', description: 'Detects persistently flaky tests across the last 20 RC runs and files fix-or-quarantine issues.', color: theme.yellow, group: 'repo_health', tags: ['quality'] },
```

Commit:

```bash
git add src/ui/src/constants.js
git commit -m "feat(ui): register flake_tracker in BACKGROUND_WORKERS"
```

- [ ] **Step 4: `src/dashboard_routes/_common.py`**

Modify `src/dashboard_routes/_common.py:32-56` — append inside `_INTERVAL_BOUNDS`:

```python
    "flake_tracker": (3600, 2_592_000),  # 1h min, 30d max
```

Commit:

```bash
git add src/dashboard_routes/_common.py
git commit -m "feat(dashboard): interval bounds for flake_tracker (1h–30d)"
```

- [ ] **Step 5: Verify `tests/test_loop_wiring_completeness.py`**

```bash
PYTHONPATH=src uv run pytest tests/test_loop_wiring_completeness.py -v
```

Expected: PASS — the regex discovery picks up `flake_tracker` in all four wiring sources.

If FAIL, locate the missing mention and commit:

```bash
git add -u
git commit -m "chore(wiring): fix flake_tracker gap flagged by completeness test"
```

---

### Task F7: MockWorld scenario — flaky test detected across 20 runs

**Files:**
- Create: `tests/scenarios/test_flake_tracker_scenario.py`

- [ ] **Step 1: Write the scenario**

Create `tests/scenarios/test_flake_tracker_scenario.py`:

```python
"""MockWorld scenario for FlakeTrackerLoop (spec §4.5).

One scenario: 20 RC runs where `tests.scenarios.test_flaky` fails 4
times and passes 16 times — above the default threshold of 3.
FlakeTrackerLoop must file exactly one `flaky-test` issue.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.loop_port_seeding import seed_ports as _seed_ports

pytestmark = pytest.mark.scenario_loops


class TestFlakeTracker:
    """§4.5 — flake detector."""

    async def test_files_issue_when_threshold_crossed(self, tmp_path) -> None:
        world = MockWorld(tmp_path)
        fake_pr = AsyncMock()
        fake_pr.create_issue = AsyncMock(return_value=101)

        # 20 runs; test_flaky fails on runs 0, 3, 7, 14.
        def make_run_results(i: int) -> dict[str, str]:
            bad = i in {0, 3, 7, 14}
            return {
                "tests.scenarios.test_flaky": "fail" if bad else "pass",
                "tests.scenarios.test_alpha": "pass",
            }

        fake_runs = [{"databaseId": i, "url": f"u{i}",
                      "createdAt": f"2026-04-{i+1:02d}"} for i in range(20)]
        fake_fetch = AsyncMock(return_value=fake_runs)
        fake_download = AsyncMock(side_effect=lambda run: make_run_results(run["databaseId"]))
        fake_reconcile = AsyncMock(return_value=None)

        _seed_ports(
            world,
            pr_manager=fake_pr,
            flake_fetch_runs=fake_fetch,
            flake_download_junit=fake_download,
            flake_reconcile_closed=fake_reconcile,
        )

        await world.run_with_loops(["flake_tracker"], cycles=1)

        assert fake_pr.create_issue.await_count == 1
        title, body, labels = fake_pr.create_issue.await_args.args[:3]
        assert "test_flaky" in title
        assert "flake rate: 4/20" in title
        assert "flaky-test" in labels
        assert "hydraflow-find" in labels

    async def test_no_file_below_threshold(self, tmp_path) -> None:
        world = MockWorld(tmp_path)
        fake_pr = AsyncMock()
        fake_pr.create_issue = AsyncMock(return_value=0)

        # Only 2 fails — below default threshold 3.
        def make_run_results(i: int) -> dict[str, str]:
            return {
                "tests.scenarios.test_slow": "fail" if i in {2, 9} else "pass",
                "tests.scenarios.test_alpha": "pass",
            }

        fake_runs = [{"databaseId": i, "url": f"u{i}"} for i in range(20)]
        _seed_ports(
            world,
            pr_manager=fake_pr,
            flake_fetch_runs=AsyncMock(return_value=fake_runs),
            flake_download_junit=AsyncMock(side_effect=lambda r: make_run_results(r["databaseId"])),
            flake_reconcile_closed=AsyncMock(return_value=None),
        )

        await world.run_with_loops(["flake_tracker"], cycles=1)
        assert fake_pr.create_issue.await_count == 0
```

- [ ] **Step 2: Wire the scenario ports**

Modify `tests/scenarios/helpers/loop_port_seeding.py` — add handling for `flake_fetch_runs`, `flake_download_junit`, `flake_reconcile_closed` keys. If the helper file does not exist at that path (check with `ls tests/scenarios/helpers/`), use the scenario's `MockWorld.register_loop_factory` hook — in that case the scenario builds the loop directly and injects the mocks via `monkeypatch.setattr(loop, "_fetch_recent_runs", fake_fetch_runs)` etc. Adjust the scenario to use whichever mechanism MockWorld already exposes (`PrinciplesAuditLoop`'s sibling scenario is the canonical example if uncertain).

- [ ] **Step 3: Run the scenario**

```bash
PYTHONPATH=src uv run pytest tests/scenarios/test_flake_tracker_scenario.py -v -m scenario_loops
```

Expected: 2 PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/scenarios/test_flake_tracker_scenario.py tests/scenarios/helpers/loop_port_seeding.py
git commit -m "test(scenario): FlakeTracker 20-run window detection (§4.5)"
```

---

### Task F8: Phase 1 close-out — `make quality` and intermediate push

- [ ] **Step 1: Run quality gate**

```bash
cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening
make quality
```

Expected: PASS. If the wiring completeness test fails, it means one of the four wiring sources is missing the `flake_tracker` string — rerun Task F6.

- [ ] **Step 2: Commit nothing new; push branch**

```bash
git push -u origin trust-arch-hardening
```

(Phases 2 + 3 continue on the same branch; the PR opens after Phase 3.)

---

## Phase 2 — SkillPromptEvalLoop (§4.6)

### Task S1: Add `skill_prompt_eval_interval` config + env override

**Files:**
- Modify: `src/config.py` (field + env-override row)
- Modify: `tests/test_config_caretaker_fleet.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_config_caretaker_fleet.py`:

```python
def test_skill_prompt_eval_interval_default() -> None:
    cfg = HydraFlowConfig()
    assert cfg.skill_prompt_eval_interval == 604800


def test_skill_prompt_eval_interval_env_override() -> None:
    with patch.dict(os.environ, {"HYDRAFLOW_SKILL_PROMPT_EVAL_INTERVAL": "86400"}):
        cfg = HydraFlowConfig.from_env()
        assert cfg.skill_prompt_eval_interval == 86400
```

- [ ] **Step 2: Run test to verify it fails**

```bash
PYTHONPATH=src uv run pytest tests/test_config_caretaker_fleet.py::test_skill_prompt_eval_interval_default -v
```

Expected: FAIL.

- [ ] **Step 3: Add the field + env row**

Modify `src/config.py` — near the `flake_tracker_interval` block, add:

```python
    # Trust fleet — SkillPromptEvalLoop (spec §4.6)
    skill_prompt_eval_interval: int = Field(
        default=604800,
        ge=86400,
        le=2_592_000,
        description="Seconds between SkillPromptEvalLoop ticks (default 7d)",
    )
```

Modify `src/config.py:174` — append to `_INT_ENV_OVERRIDES`:

```python
    ("skill_prompt_eval_interval", "HYDRAFLOW_SKILL_PROMPT_EVAL_INTERVAL", 604800),
```

- [ ] **Step 4: Run test**

```bash
PYTHONPATH=src uv run pytest tests/test_config_caretaker_fleet.py -v
```

Expected: 5 PASS total.

- [ ] **Step 5: Commit**

```bash
git add src/config.py tests/test_config_caretaker_fleet.py
git commit -m "feat(config): skill_prompt_eval_interval + env override (§4.6)"
```

---

### Task S2: Add skill-prompt state mixin

**Files:**
- Create: `src/state/_skill_prompt_eval.py`
- Modify: `src/state/__init__.py`
- Create: `tests/test_state_skill_prompt_eval.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_state_skill_prompt_eval.py`:

```python
"""Tests for SkillPromptEvalStateMixin."""

from __future__ import annotations

from pathlib import Path

from state import StateTracker


def _tracker(tmp_path: Path) -> StateTracker:
    return StateTracker(state_file=tmp_path / "state.json")


def test_last_green_roundtrip(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    snap = {"case_diff_shrink_001": "PASS", "case_scope_creep_002": "PASS"}
    st.set_skill_prompt_last_green(snap)
    assert st.get_skill_prompt_last_green() == snap


def test_attempt_counter(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    assert st.get_skill_prompt_attempts("case_x") == 0
    assert st.inc_skill_prompt_attempts("case_x") == 1
    assert st.inc_skill_prompt_attempts("case_x") == 2
    st.clear_skill_prompt_attempts("case_x")
    assert st.get_skill_prompt_attempts("case_x") == 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
PYTHONPATH=src uv run pytest tests/test_state_skill_prompt_eval.py -v
```

Expected: FAIL.

- [ ] **Step 3: Create the mixin**

Create `src/state/_skill_prompt_eval.py`:

```python
"""State accessors for SkillPromptEvalLoop (spec §4.6)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import StateData


class SkillPromptEvalStateMixin:
    """Last-green eval snapshot + per-case repair attempts."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    def get_skill_prompt_last_green(self) -> dict[str, str]:
        return dict(self._data.skill_prompt_last_green)

    def set_skill_prompt_last_green(self, snap: dict[str, str]) -> None:
        self._data.skill_prompt_last_green = dict(snap)
        self.save()

    def get_skill_prompt_attempts(self, case_id: str) -> int:
        return int(self._data.skill_prompt_attempts.get(case_id, 0))

    def inc_skill_prompt_attempts(self, case_id: str) -> int:
        current = int(self._data.skill_prompt_attempts.get(case_id, 0)) + 1
        attempts = dict(self._data.skill_prompt_attempts)
        attempts[case_id] = current
        self._data.skill_prompt_attempts = attempts
        self.save()
        return current

    def clear_skill_prompt_attempts(self, case_id: str) -> None:
        attempts = dict(self._data.skill_prompt_attempts)
        attempts.pop(case_id, None)
        self._data.skill_prompt_attempts = attempts
        self.save()
```

- [ ] **Step 4: Register mixin**

Modify `src/state/__init__.py` — add import + MRO entry (same pattern as Task F1 Step 5):

```python
from ._skill_prompt_eval import SkillPromptEvalStateMixin
```

Add `SkillPromptEvalStateMixin` to the `StateTracker` MRO (after `FlakeTrackerStateMixin`).

- [ ] **Step 5: Run test**

```bash
PYTHONPATH=src uv run pytest tests/test_state_skill_prompt_eval.py -v
```

Expected: 2 PASS.

- [ ] **Step 6: Commit**

```bash
git add src/state/_skill_prompt_eval.py src/state/__init__.py tests/test_state_skill_prompt_eval.py
git commit -m "feat(state): SkillPromptEvalStateMixin (§4.6)"
```

---

### Task S3: `SkillPromptEvalLoop` skeleton + dual-role tick

**Files:**
- Create: `src/skill_prompt_eval_loop.py`
- Create: `tests/test_skill_prompt_eval_loop.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_skill_prompt_eval_loop.py`:

```python
"""Tests for SkillPromptEvalLoop (spec §4.6)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus
from skill_prompt_eval_loop import SkillPromptEvalLoop


def _deps(stop: asyncio.Event) -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: True,
    )


@pytest.fixture
def loop_env(tmp_path: Path):
    cfg = HydraFlowConfig(data_root=tmp_path, repo="hydra/hydraflow")
    state = MagicMock()
    state.get_skill_prompt_last_green.return_value = {}
    state.get_skill_prompt_attempts.return_value = 0
    pr = AsyncMock()
    pr.create_issue = AsyncMock(return_value=42)
    dedup = MagicMock()
    dedup.get.return_value = set()
    return cfg, state, pr, dedup


def test_skeleton_worker_name_and_interval(loop_env) -> None:
    cfg, state, pr, dedup = loop_env
    stop = asyncio.Event()
    loop = SkillPromptEvalLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )
    assert loop._worker_name == "skill_prompt_eval"
    assert loop._get_default_interval() == 604800


async def test_detects_regression_pass_to_fail(loop_env, monkeypatch) -> None:
    cfg, state, pr, dedup = loop_env
    state.get_skill_prompt_last_green.return_value = {
        "case_shrink_001": "PASS",
        "case_scope_002": "PASS",
    }
    stop = asyncio.Event()
    loop = SkillPromptEvalLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )

    async def fake_run_corpus() -> list[dict]:
        return [
            {"case_id": "case_shrink_001", "skill": "diff_sanity",
             "status": "FAIL", "provenance": "hand-crafted",
             "expected_catcher": "diff_sanity"},
            {"case_id": "case_scope_002", "skill": "scope_check",
             "status": "PASS", "provenance": "hand-crafted",
             "expected_catcher": "scope_check"},
        ]

    async def fake_reconcile():
        return None

    monkeypatch.setattr(loop, "_run_corpus", fake_run_corpus)
    monkeypatch.setattr(loop, "_reconcile_closed_escalations", fake_reconcile)

    stats = await loop._do_work()
    assert stats["filed"] == 1
    title = pr.create_issue.await_args.args[0]
    assert "diff_sanity" in title
    assert "case_shrink_001" in title
    labels = pr.create_issue.await_args.args[2]
    assert "skill-prompt-drift" in labels


async def test_weak_case_sampling_files_corpus_case_weak(loop_env, monkeypatch) -> None:
    cfg, state, pr, dedup = loop_env
    stop = asyncio.Event()
    loop = SkillPromptEvalLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )

    # 10 learning-loop cases, all PASS — loop expects some to be caught
    # (test provides `expected_catcher: diff_sanity` but the run returned
    # `skill=diff_sanity, status=PASS` meaning the skill let it through).
    cases = [
        {"case_id": f"case_learn_{i:03d}", "skill": "diff_sanity",
         "status": "PASS", "provenance": "learning-loop",
         "expected_catcher": "diff_sanity"}
        for i in range(10)
    ]

    async def fake_run_corpus() -> list[dict]:
        return cases

    async def fake_reconcile():
        return None

    monkeypatch.setattr(loop, "_run_corpus", fake_run_corpus)
    monkeypatch.setattr(loop, "_reconcile_closed_escalations", fake_reconcile)

    stats = await loop._do_work()
    # 10% of 10 = 1 case sampled. Sampled case is flagged because
    # its expected catcher passed it. So 1 corpus-case-weak issue.
    assert stats["weak_cases_flagged"] >= 1
    weak_calls = [
        c for c in pr.create_issue.await_args_list
        if "corpus-case-weak" in (c.args[2] if len(c.args) > 2 else [])
    ]
    assert len(weak_calls) >= 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
PYTHONPATH=src uv run pytest tests/test_skill_prompt_eval_loop.py -v
```

Expected: FAIL — module does not exist.

- [ ] **Step 3: Create the loop**

Create `src/skill_prompt_eval_loop.py`:

```python
"""SkillPromptEvalLoop — weekly corpus backstop + weak-case audit.

Spec: `docs/superpowers/specs/2026-04-22-trust-architecture-hardening-design.md`
§4.6. Two roles:

1. **Backstop.** Runs the *full* adversarial corpus weekly (§4.1). Once
   the corpus grows past `trust_rc_subset_size` the RC gate shifts to a
   sampled subset; this loop catches regressions the weekly sample
   misses. Files `skill-prompt-drift` issues for PASS→FAIL transitions.
2. **Weak-case audit.** Samples 10% of `provenance: learning-loop`
   cases and flags any whose `expected_catcher` skill passes them — a
   weak-case signal the §4.1 v2 learner uses. Files `corpus-case-weak`
   issues for human triage.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import random
import time
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from models import WorkCycleResult

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from dedup_store import DedupStore
    from pr_manager import PRManager
    from state import StateTracker

logger = logging.getLogger("hydraflow.skill_prompt_eval_loop")

_MAX_ATTEMPTS = 3
_WEAK_SAMPLE_RATE = 0.10


class SkillPromptEvalLoop(BaseBackgroundLoop):
    """Weekly skill-prompt drift detector + corpus-health auditor (spec §4.6)."""

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
            worker_name="skill_prompt_eval",
            config=config,
            deps=deps,
            run_on_startup=False,
        )
        self._state = state
        self._pr = pr_manager
        self._dedup = dedup

    def _get_default_interval(self) -> int:
        return self._config.skill_prompt_eval_interval

    async def _run_corpus(self) -> list[dict[str, Any]]:
        """Invoke `make trust-adversarial` → list of case-result dicts.

        Each dict carries ``{case_id, skill, status, provenance,
        expected_catcher}``. Owned by Plan 1 (`make trust-adversarial
        --format=json`). Missing keys are tolerated — cases without
        ``provenance`` are treated as ``hand-crafted``.
        """
        cmd = ["make", "trust-adversarial", "FORMAT=json"]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=self._config.repo_root,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode not in (0, 1):  # 1 = failures present; still valid output
            logger.warning(
                "trust-adversarial exit=%d: %s",
                proc.returncode, stderr.decode(errors="replace")[:400],
            )
            return []
        try:
            return json.loads(stdout.decode() or "[]")
        except json.JSONDecodeError:
            logger.warning("trust-adversarial non-JSON response")
            return []

    async def _file_drift_issue(
        self, case: dict[str, Any], last_status: str
    ) -> int:
        title = (
            f"Skill prompt drift: {case.get('skill', '?')} "
            f"missed {case.get('case_id', '?')}"
        )
        body = (
            f"## Regression\n\n"
            f"Case `{case.get('case_id')}` regressed "
            f"**{last_status} → {case.get('status')}** on "
            f"skill `{case.get('skill')}`.\n\n"
            f"**Expected catcher:** `{case.get('expected_catcher', '?')}`\n"
            f"**Provenance:** `{case.get('provenance', 'unknown')}`\n\n"
            f"_Spec §4.6 — filed by `skill_prompt_eval` loop. Standard "
            f"repair path: edit the skill prompt or the skill's code._"
        )
        return await self._pr.create_issue(
            title, body, ["hydraflow-find", "skill-prompt-drift"]
        )

    async def _file_weak_case_issue(self, case: dict[str, Any]) -> int:
        title = (
            f"Weak corpus case: {case.get('case_id')} "
            f"bypassed {case.get('expected_catcher')}"
        )
        body = (
            f"## Weak-case signal\n\n"
            f"Learning-loop case `{case.get('case_id')}` was PASSED by the "
            f"skill (`{case.get('skill')}`) that was *expected* to catch it "
            f"(`{case.get('expected_catcher')}`). This is the weak-case "
            f"signal the §4.1 v2 learner uses — flag it for human review "
            f"so the corpus self-improves.\n\n"
            f"_Spec §4.6 — filed by `skill_prompt_eval` loop._"
        )
        return await self._pr.create_issue(
            title, body, ["hydraflow-find", "corpus-case-weak"]
        )

    async def _file_escalation(self, case_id: str, attempts: int) -> int:
        title = f"HITL: skill prompt drift {case_id} unresolved after {attempts}"
        body = (
            f"`skill_prompt_eval` filed `skill-prompt-drift` for `{case_id}` "
            f"{attempts} times without closure. Human review needed.\n\n"
            f"_Spec §3.2: closing this issue clears the dedup key._"
        )
        return await self._pr.create_issue(
            title, body, ["hitl-escalation", "skill-prompt-stuck"]
        )

    async def _reconcile_closed_escalations(self) -> None:
        """Clear dedup keys for closed `skill-prompt-stuck` escalations."""
        cmd = [
            "gh", "issue", "list",
            "--repo", self._config.repo,
            "--state", "closed",
            "--label", "hitl-escalation",
            "--label", "skill-prompt-stuck",
            "--author", "@me",
            "--limit", "100",
            "--json", "title",
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
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
            for key in list(keep):
                if (
                    key.startswith("skill_prompt_eval:")
                    and key.split(":", 1)[1] in title
                ):
                    keep.discard(key)
                    self._state.clear_skill_prompt_attempts(key.split(":", 1)[1])
        if keep != current:
            self._dedup.set_all(keep)

    def _sample_learning_cases(
        self, cases: list[dict[str, Any]], seed: int = 0
    ) -> list[dict[str, Any]]:
        learning = [c for c in cases if c.get("provenance") == "learning-loop"]
        if not learning:
            return []
        n = max(1, math.ceil(len(learning) * _WEAK_SAMPLE_RATE))
        rng = random.Random(seed or 1)
        return rng.sample(learning, min(n, len(learning)))

    async def _do_work(self) -> WorkCycleResult:
        """Weekly eval — backstop + weak-case sampling."""
        t0 = time.perf_counter()
        await self._reconcile_closed_escalations()

        cases = await self._run_corpus()
        if not cases:
            return {"status": "no_cases", "filed": 0}

        # Role 1 — backstop. PASS→FAIL regressions.
        last_green = self._state.get_skill_prompt_last_green()
        current: dict[str, str] = {
            c["case_id"]: c.get("status", "UNKNOWN") for c in cases
        }
        filed = 0
        escalated = 0
        dedup = self._dedup.get()
        for case in cases:
            case_id = case.get("case_id")
            if not case_id:
                continue
            was = last_green.get(case_id, "PASS")
            now = case.get("status")
            if was == "PASS" and now == "FAIL":
                key = f"skill_prompt_eval:{case_id}"
                if key in dedup:
                    continue
                attempts = self._state.inc_skill_prompt_attempts(case_id)
                if attempts >= _MAX_ATTEMPTS:
                    await self._file_escalation(case_id, attempts)
                    escalated += 1
                else:
                    await self._file_drift_issue(case, was)
                    filed += 1
                dedup.add(key)
                self._dedup.set_all(dedup)

        # Save the new snapshot — tests that currently PASS become the
        # new last-green. Tests that remain FAIL stay in the dedup set.
        self._state.set_skill_prompt_last_green(
            {cid: "PASS" for cid, status in current.items() if status == "PASS"}
        )

        # Role 2 — weak-case audit. Learning-loop cases that expected
        # catcher passed through.
        weak_flagged = 0
        sample = self._sample_learning_cases(cases)
        for case in sample:
            skill = case.get("skill")
            catcher = case.get("expected_catcher")
            status = case.get("status")
            if skill == catcher and status == "PASS":
                key = f"skill_prompt_eval:weak:{case.get('case_id')}"
                if key in dedup:
                    continue
                await self._file_weak_case_issue(case)
                weak_flagged += 1
                dedup.add(key)
                self._dedup.set_all(dedup)

        self._emit_trace(t0, cases_seen=len(cases))
        return {
            "status": "ok",
            "filed": filed,
            "escalated": escalated,
            "weak_cases_flagged": weak_flagged,
            "cases_seen": len(cases),
        }

    def _emit_trace(self, t0: float, *, cases_seen: int) -> None:
        try:
            from trace_collector import emit_loop_subprocess_trace  # noqa: PLC0415
        except ImportError:
            return
        emit_loop_subprocess_trace(
            worker_name=self._worker_name,
            command=["make", "trust-adversarial", "FORMAT=json"],
            exit_code=0,
            duration_s=time.perf_counter() - t0,
            stdout_tail=f"cases={cases_seen}",
            stderr_tail="",
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
PYTHONPATH=src uv run pytest tests/test_skill_prompt_eval_loop.py -v
```

Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/skill_prompt_eval_loop.py tests/test_skill_prompt_eval_loop.py
git commit -m "feat(loop): SkillPromptEvalLoop backstop + weak-case sampling (§4.6)"
```

---

### Task S4: Escalation test + close-reconcile test

**Files:**
- Modify: `tests/test_skill_prompt_eval_loop.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_skill_prompt_eval_loop.py`:

```python
async def test_escalation_fires_after_three_attempts(loop_env, monkeypatch) -> None:
    cfg, state, pr, dedup = loop_env
    state.get_skill_prompt_last_green.return_value = {"case_shrink_001": "PASS"}
    state.inc_skill_prompt_attempts.return_value = 3
    stop = asyncio.Event()
    loop = SkillPromptEvalLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )

    async def fake_run_corpus():
        return [{"case_id": "case_shrink_001", "skill": "diff_sanity",
                 "status": "FAIL", "provenance": "hand-crafted",
                 "expected_catcher": "diff_sanity"}]

    async def fake_reconcile():
        return None

    monkeypatch.setattr(loop, "_run_corpus", fake_run_corpus)
    monkeypatch.setattr(loop, "_reconcile_closed_escalations", fake_reconcile)

    stats = await loop._do_work()
    assert stats["escalated"] == 1
    labels = pr.create_issue.await_args.args[2]
    assert "hitl-escalation" in labels
    assert "skill-prompt-stuck" in labels


async def test_reconcile_closed_escalations(loop_env, monkeypatch) -> None:
    cfg, state, pr, dedup = loop_env
    dedup.get.return_value = {"skill_prompt_eval:case_alpha"}
    stop = asyncio.Event()
    loop = SkillPromptEvalLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )

    class FakeProc:
        returncode = 0

        async def communicate(self):
            return (
                b'[{"title": "HITL: skill prompt drift case_alpha unresolved after 3"}]',
                b"",
            )

    async def fake_subproc(*a, **kw):
        return FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subproc)

    await loop._reconcile_closed_escalations()
    dedup.set_all.assert_called_once()
    remaining = dedup.set_all.call_args.args[0]
    assert "skill_prompt_eval:case_alpha" not in remaining
    state.clear_skill_prompt_attempts.assert_called_once_with("case_alpha")
```

- [ ] **Step 2: Run**

```bash
PYTHONPATH=src uv run pytest tests/test_skill_prompt_eval_loop.py -v
```

Expected: 5 PASS total.

- [ ] **Step 3: Commit**

```bash
git add tests/test_skill_prompt_eval_loop.py
git commit -m "test(loop): SkillPromptEval escalation + close-reconcile (§3.2 + §4.6)"
```

---

### Task S5: Five-checkpoint wiring for `skill_prompt_eval`

The string `skill_prompt_eval` lands in five places, verbatim.

- [ ] **Step 1: `src/service_registry.py`**

Modify `src/service_registry.py:63` — add import:

```python
from skill_prompt_eval_loop import SkillPromptEvalLoop  # noqa: TCH001
```

Modify `src/service_registry.py` dataclass (line 168 area) — append field:

```python
    skill_prompt_eval_loop: SkillPromptEvalLoop
```

Modify `src/service_registry.py` inside `build_services` — after the `flake_tracker_loop` block from Task F6, add:

```python
    skill_prompt_eval_dedup = DedupStore(
        "skill_prompt_eval",
        config.data_root / "dedup" / "skill_prompt_eval.json",
    )
    skill_prompt_eval_loop = SkillPromptEvalLoop(  # noqa: F841
        config=config,
        state=state,
        pr_manager=prs,
        dedup=skill_prompt_eval_dedup,
        deps=loop_deps,
    )
```

Append to the `ServiceRegistry(...)` call:

```python
        skill_prompt_eval_loop=skill_prompt_eval_loop,
```

Commit:

```bash
git add src/service_registry.py
git commit -m "feat(wiring): SkillPromptEvalLoop in service registry"
```

- [ ] **Step 2: `src/orchestrator.py`**

Modify `src/orchestrator.py:159` — add to `bg_loop_registry`:

```python
            "skill_prompt_eval": svc.skill_prompt_eval_loop,
```

Modify `src/orchestrator.py:909` — add to `loop_factories`:

```python
            ("skill_prompt_eval", self._svc.skill_prompt_eval_loop.run),
```

Commit:

```bash
git add src/orchestrator.py
git commit -m "feat(wiring): orchestrator runs SkillPromptEvalLoop"
```

- [ ] **Step 3: `src/ui/src/constants.js`**

1. `EDITABLE_INTERVAL_WORKERS` (line 252): add `'skill_prompt_eval'`.
2. `SYSTEM_WORKER_INTERVALS` (line 259+): add `skill_prompt_eval: 604800,`.
3. `BACKGROUND_WORKERS` (line 293+): append:

```js
  { key: 'skill_prompt_eval', label: 'Skill Prompt Eval', description: 'Runs the full adversarial skill corpus weekly and files drift + weak-case issues.', color: theme.blue, group: 'learning', tags: ['quality'] },
```

Commit:

```bash
git add src/ui/src/constants.js
git commit -m "feat(ui): register skill_prompt_eval in BACKGROUND_WORKERS"
```

- [ ] **Step 4: `src/dashboard_routes/_common.py`**

Modify `src/dashboard_routes/_common.py:32` — add:

```python
    "skill_prompt_eval": (86400, 2_592_000),  # 1d min, 30d max
```

Commit:

```bash
git add src/dashboard_routes/_common.py
git commit -m "feat(dashboard): interval bounds for skill_prompt_eval (1d–30d)"
```

- [ ] **Step 5: Verify wiring completeness**

```bash
PYTHONPATH=src uv run pytest tests/test_loop_wiring_completeness.py -v
```

Expected: PASS.

---

### Task S6: MockWorld scenario — corpus drift + weak-case sampling

**Files:**
- Create: `tests/scenarios/test_skill_prompt_eval_scenario.py`

- [ ] **Step 1: Write the scenario**

Create `tests/scenarios/test_skill_prompt_eval_scenario.py`:

```python
"""MockWorld scenario for SkillPromptEvalLoop (spec §4.6).

Two scenarios:
1. Drift — one hand-crafted case regressed PASS→FAIL; expect one
   `skill-prompt-drift` issue.
2. Weak-case — 10 learning-loop cases all PASS; the sampled 10% are
   the weak-case signal (expected_catcher == skill but status=PASS).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.loop_port_seeding import seed_ports as _seed_ports

pytestmark = pytest.mark.scenario_loops


class TestSkillPromptEval:
    """§4.6 — skill-prompt drift + weak-case audit."""

    async def test_drift_regression_files_issue(self, tmp_path) -> None:
        world = MockWorld(tmp_path)
        world.state.set_skill_prompt_last_green({
            "case_shrink_001": "PASS", "case_scope_002": "PASS",
        })
        fake_pr = AsyncMock()
        fake_pr.create_issue = AsyncMock(return_value=301)

        corpus_result = [
            {"case_id": "case_shrink_001", "skill": "diff_sanity",
             "status": "FAIL", "provenance": "hand-crafted",
             "expected_catcher": "diff_sanity"},
            {"case_id": "case_scope_002", "skill": "scope_check",
             "status": "PASS", "provenance": "hand-crafted",
             "expected_catcher": "scope_check"},
        ]

        _seed_ports(
            world,
            pr_manager=fake_pr,
            skill_corpus_runner=AsyncMock(return_value=corpus_result),
            skill_reconcile_closed=AsyncMock(return_value=None),
        )

        await world.run_with_loops(["skill_prompt_eval"], cycles=1)

        assert fake_pr.create_issue.await_count == 1
        title = fake_pr.create_issue.await_args.args[0]
        assert "diff_sanity" in title
        assert "case_shrink_001" in title
        labels = fake_pr.create_issue.await_args.args[2]
        assert "skill-prompt-drift" in labels

    async def test_weak_case_sampling(self, tmp_path) -> None:
        world = MockWorld(tmp_path)
        fake_pr = AsyncMock()
        fake_pr.create_issue = AsyncMock(return_value=302)

        corpus_result = [
            {"case_id": f"case_learn_{i:03d}", "skill": "diff_sanity",
             "status": "PASS", "provenance": "learning-loop",
             "expected_catcher": "diff_sanity"}
            for i in range(10)
        ]

        _seed_ports(
            world,
            pr_manager=fake_pr,
            skill_corpus_runner=AsyncMock(return_value=corpus_result),
            skill_reconcile_closed=AsyncMock(return_value=None),
        )

        await world.run_with_loops(["skill_prompt_eval"], cycles=1)

        weak_calls = [
            c for c in fake_pr.create_issue.await_args_list
            if "corpus-case-weak" in (c.args[2] if len(c.args) > 2 else [])
        ]
        assert len(weak_calls) >= 1
```

- [ ] **Step 2: Add ports to `loop_port_seeding.py`**

Modify `tests/scenarios/helpers/loop_port_seeding.py` — add support for `skill_corpus_runner` (monkey-patches `loop._run_corpus`) and `skill_reconcile_closed` (patches `loop._reconcile_closed_escalations`). Pattern-match on the `PrinciplesAuditLoop` ports if unsure.

- [ ] **Step 3: Run**

```bash
PYTHONPATH=src uv run pytest tests/scenarios/test_skill_prompt_eval_scenario.py -v -m scenario_loops
```

Expected: 2 PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/scenarios/test_skill_prompt_eval_scenario.py tests/scenarios/helpers/loop_port_seeding.py
git commit -m "test(scenario): SkillPromptEval drift + weak-case (§4.6)"
```

---

### Task S7: Phase 2 close-out — quality gate

- [ ] **Step 1**

```bash
make quality
```

Expected: PASS.

- [ ] **Step 2: Push incrementally**

```bash
git push
```

---

## Phase 3 — FakeCoverageAuditorLoop (§4.7)

### Task C1: Add `fake_coverage_auditor_interval` config + env override

**Files:**
- Modify: `src/config.py`
- Modify: `tests/test_config_caretaker_fleet.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_config_caretaker_fleet.py`:

```python
def test_fake_coverage_interval_default() -> None:
    cfg = HydraFlowConfig()
    assert cfg.fake_coverage_auditor_interval == 604800


def test_fake_coverage_interval_env_override() -> None:
    with patch.dict(os.environ, {"HYDRAFLOW_FAKE_COVERAGE_AUDITOR_INTERVAL": "86400"}):
        cfg = HydraFlowConfig.from_env()
        assert cfg.fake_coverage_auditor_interval == 86400
```

- [ ] **Step 2: Run test to verify it fails**

```bash
PYTHONPATH=src uv run pytest tests/test_config_caretaker_fleet.py::test_fake_coverage_interval_default -v
```

- [ ] **Step 3: Add the field + env row**

Modify `src/config.py` — near the `skill_prompt_eval_interval` block, add:

```python
    # Trust fleet — FakeCoverageAuditorLoop (spec §4.7)
    fake_coverage_auditor_interval: int = Field(
        default=604800,
        ge=86400,
        le=2_592_000,
        description="Seconds between FakeCoverageAuditorLoop ticks (default 7d)",
    )
```

Append to `_INT_ENV_OVERRIDES`:

```python
    ("fake_coverage_auditor_interval", "HYDRAFLOW_FAKE_COVERAGE_AUDITOR_INTERVAL", 604800),
```

- [ ] **Step 4: Run + commit**

```bash
PYTHONPATH=src uv run pytest tests/test_config_caretaker_fleet.py -v
git add src/config.py tests/test_config_caretaker_fleet.py
git commit -m "feat(config): fake_coverage_auditor_interval + env override (§4.7)"
```

---

### Task C2: Add fake-coverage state mixin

**Files:**
- Create: `src/state/_fake_coverage.py`
- Modify: `src/state/__init__.py`
- Create: `tests/test_state_fake_coverage.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_state_fake_coverage.py`:

```python
"""Tests for FakeCoverageStateMixin."""

from __future__ import annotations

from pathlib import Path

from state import StateTracker


def _tracker(tmp_path: Path) -> StateTracker:
    return StateTracker(state_file=tmp_path / "state.json")


def test_last_known_roundtrip(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    known = {"FakeGitHub": ["create_issue", "close_issue"]}
    st.set_fake_coverage_last_known(known)
    assert st.get_fake_coverage_last_known() == known


def test_attempt_counter(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    key = "FakeGitHub.create_issue:adapter-surface"
    assert st.get_fake_coverage_attempts(key) == 0
    assert st.inc_fake_coverage_attempts(key) == 1
    st.clear_fake_coverage_attempts(key)
    assert st.get_fake_coverage_attempts(key) == 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
PYTHONPATH=src uv run pytest tests/test_state_fake_coverage.py -v
```

- [ ] **Step 3: Create the mixin**

Create `src/state/_fake_coverage.py`:

```python
"""State accessors for FakeCoverageAuditorLoop (spec §4.7)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import StateData


class FakeCoverageStateMixin:
    """Last-known covered method list + per-gap repair attempts."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    def get_fake_coverage_last_known(self) -> dict[str, list[str]]:
        return {k: list(v) for k, v in self._data.fake_coverage_last_known.items()}

    def set_fake_coverage_last_known(self, known: dict[str, list[str]]) -> None:
        self._data.fake_coverage_last_known = {
            k: list(v) for k, v in known.items()
        }
        self.save()

    def get_fake_coverage_attempts(self, key: str) -> int:
        return int(self._data.fake_coverage_attempts.get(key, 0))

    def inc_fake_coverage_attempts(self, key: str) -> int:
        current = int(self._data.fake_coverage_attempts.get(key, 0)) + 1
        attempts = dict(self._data.fake_coverage_attempts)
        attempts[key] = current
        self._data.fake_coverage_attempts = attempts
        self.save()
        return current

    def clear_fake_coverage_attempts(self, key: str) -> None:
        attempts = dict(self._data.fake_coverage_attempts)
        attempts.pop(key, None)
        self._data.fake_coverage_attempts = attempts
        self.save()
```

- [ ] **Step 4: Register mixin**

Modify `src/state/__init__.py` — add import + MRO entry:

```python
from ._fake_coverage import FakeCoverageStateMixin
```

Append to MRO after `SkillPromptEvalStateMixin`.

- [ ] **Step 5: Run + commit**

```bash
PYTHONPATH=src uv run pytest tests/test_state_fake_coverage.py -v
git add src/state/_fake_coverage.py src/state/__init__.py tests/test_state_fake_coverage.py
git commit -m "feat(state): FakeCoverageStateMixin (§4.7)"
```

---

### Task C3: `FakeCoverageAuditorLoop` + AST introspection helpers

**Files:**
- Create: `src/fake_coverage_auditor_loop.py`
- Create: `tests/test_fake_coverage_auditor_loop.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_fake_coverage_auditor_loop.py`:

```python
"""Tests for FakeCoverageAuditorLoop (spec §4.7)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus
from fake_coverage_auditor_loop import (
    FakeCoverageAuditorLoop,
    catalog_fake_methods,
    catalog_cassette_methods,
)


def _deps(stop: asyncio.Event) -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: True,
    )


@pytest.fixture
def loop_env(tmp_path: Path):
    cfg = HydraFlowConfig(data_root=tmp_path, repo="hydra/hydraflow", repo_root=tmp_path)
    state = MagicMock()
    state.get_fake_coverage_last_known.return_value = {}
    state.get_fake_coverage_attempts.return_value = 0
    pr = AsyncMock()
    pr.create_issue = AsyncMock(return_value=42)
    dedup = MagicMock()
    dedup.get.return_value = set()
    return cfg, state, pr, dedup


def test_skeleton_worker_name_and_interval(loop_env) -> None:
    cfg, state, pr, dedup = loop_env
    stop = asyncio.Event()
    loop = FakeCoverageAuditorLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )
    assert loop._worker_name == "fake_coverage_auditor"
    assert loop._get_default_interval() == 604800


def test_catalog_fake_methods_splits_surface_vs_helper(tmp_path: Path) -> None:
    fake_dir = tmp_path / "fakes"
    fake_dir.mkdir()
    (fake_dir / "fake_github.py").write_text(
        "from dataclasses import dataclass\n\n"
        "class FakeGitHub:\n"
        "    async def create_issue(self, title, body, labels): ...\n"
        "    async def close_issue(self, num): ...\n"
        "    def script_ci(self, events): ...\n"
        "    def fail_service(self, reason): ...\n"
        "    def _private(self): ...\n"
    )

    cat = catalog_fake_methods(fake_dir)
    assert "FakeGitHub" in cat
    surface = set(cat["FakeGitHub"]["adapter-surface"])
    helpers = set(cat["FakeGitHub"]["test-helper"])
    assert surface == {"create_issue", "close_issue"}
    assert helpers == {"script_ci", "fail_service"}


def test_catalog_cassette_methods_reads_input_command(tmp_path: Path) -> None:
    cassettes = tmp_path / "cassettes" / "github"
    cassettes.mkdir(parents=True)
    (cassettes / "create_issue.json").write_text(
        json.dumps({"input": {"command": "create_issue"}, "output": {}})
    )
    (cassettes / "close_issue.json").write_text(
        json.dumps({"input": {"command": "close_issue"}, "output": {}})
    )
    methods = catalog_cassette_methods(cassettes)
    assert methods == {"create_issue", "close_issue"}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
PYTHONPATH=src uv run pytest tests/test_fake_coverage_auditor_loop.py -v
```

Expected: FAIL — module does not exist.

- [ ] **Step 3: Create the loop + helpers**

Create `src/fake_coverage_auditor_loop.py`:

```python
"""FakeCoverageAuditorLoop — weekly un-cassetted-method detector.

Spec: `docs/superpowers/specs/2026-04-22-trust-architecture-hardening-design.md`
§4.7. Introspects fake classes under `tests/scenarios/fakes/` via
``ast.parse`` and compares two method sets to their coverage sources:

- ``adapter-surface`` — public non-private methods. Covered by a
  cassette under ``tests/trust/contracts/cassettes/<adapter>/`` whose
  ``input.command`` names the method.
- ``test-helper`` — helpers the scenarios drive (``script_*``,
  ``fail_service``, ``heal_service``, ``set_state``). Covered by a
  scenario test under ``tests/scenarios/`` that calls the helper.

Files `hydraflow-find` + `fake-coverage-gap` + one of
`adapter-surface` | `test-helper` per uncovered method. Escalates
after 3 attempts to `hitl-escalation` + `fake-coverage-stuck`.
"""

from __future__ import annotations

import asyncio
import ast
import json
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from models import WorkCycleResult

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from dedup_store import DedupStore
    from pr_manager import PRManager
    from state import StateTracker

logger = logging.getLogger("hydraflow.fake_coverage_auditor_loop")

_MAX_ATTEMPTS = 3
_HELPER_PREFIXES = ("script_",)
_HELPER_NAMES = frozenset({"fail_service", "heal_service", "set_state"})


def _is_helper(name: str) -> bool:
    return any(name.startswith(p) for p in _HELPER_PREFIXES) or name in _HELPER_NAMES


def catalog_fake_methods(fake_dir: Path) -> dict[str, dict[str, list[str]]]:
    """AST-scan `fake_dir/*.py` for classes starting with ``Fake``.

    Returns::

        {
          "FakeGitHub": {
            "adapter-surface": ["create_issue", "close_issue", ...],
            "test-helper":     ["script_ci", "fail_service", ...],
          },
          ...
        }
    """
    catalog: dict[str, dict[str, list[str]]] = {}
    for path in sorted(fake_dir.glob("*.py")):
        if path.name.startswith("test_") or path.name == "__init__.py":
            continue
        try:
            tree = ast.parse(path.read_text(), filename=str(path))
        except SyntaxError:
            logger.debug("syntax error parsing %s", path)
            continue
        for node in ast.iter_child_nodes(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if not node.name.startswith("Fake"):
                continue
            surface: list[str] = []
            helpers: list[str] = []
            for child in node.body:
                if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                name = child.name
                if name.startswith("_"):
                    continue
                if _is_helper(name):
                    helpers.append(name)
                else:
                    surface.append(name)
            catalog[node.name] = {
                "adapter-surface": sorted(surface),
                "test-helper": sorted(helpers),
            }
    return catalog


def catalog_cassette_methods(cassette_dir: Path) -> set[str]:
    """Return the set of real-adapter methods recorded under `cassette_dir`.

    Each cassette is a JSON file with an ``input.command`` field naming
    the method invoked.
    """
    methods: set[str] = set()
    if not cassette_dir.exists():
        return methods
    for path in cassette_dir.rglob("*.json"):
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        cmd = data.get("input", {}).get("command")
        if isinstance(cmd, str):
            methods.add(cmd)
    return methods


# Map from fake class name → cassette sub-directory.
_FAKE_TO_CASSETTE_DIR: dict[str, str] = {
    "FakeGitHub": "github",
    "FakeDocker": "docker",
    "FakeGit": "git",
    "FakeBeads": "beads",
    "FakeSentry": "sentry",
    "FakeHindsight": "hindsight",
    "FakeHttp": "http",
    "FakeSubprocessRunner": "subprocess",
    "FakeFs": "fs",
    "FakeLLM": "llm",
}


class FakeCoverageAuditorLoop(BaseBackgroundLoop):
    """Weekly fake-surface coverage auditor (spec §4.7)."""

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
            worker_name="fake_coverage_auditor",
            config=config,
            deps=deps,
            run_on_startup=False,
        )
        self._state = state
        self._pr = pr_manager
        self._dedup = dedup

    def _get_default_interval(self) -> int:
        return self._config.fake_coverage_auditor_interval

    async def _grep_scenario_for_helper(self, helper: str) -> bool:
        """Return True iff `tests/scenarios/` contains a call to `helper`."""
        repo = self._config.repo_root
        scenario_dir = repo / "tests" / "scenarios"
        if not scenario_dir.exists():
            return False
        cmd = [
            "rg", "--type=py", "-l", "--fixed-strings",
            f"{helper}(", str(scenario_dir),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        # rg exits 0 on match, 1 on no-match, 2+ on error.
        return proc.returncode == 0 and bool(stdout.strip())

    async def _file_surface_gap(self, fake: str, method: str) -> int:
        title = f"Un-cassetted adapter method: {fake}.{method}"
        body = (
            f"## Fake coverage gap — adapter surface\n\n"
            f"Fake class `{fake}` exposes a public method `{method}` with no "
            f"matching cassette under "
            f"`tests/trust/contracts/cassettes/{_FAKE_TO_CASSETTE_DIR.get(fake, '?')}/`.\n\n"
            f"**Repair:** record a cassette that exercises the real-adapter "
            f"counterpart and commit. Spec §4.7; filed by `fake_coverage_auditor`."
        )
        return await self._pr.create_issue(
            title, body,
            ["hydraflow-find", "fake-coverage-gap", "adapter-surface"],
        )

    async def _file_helper_gap(self, fake: str, method: str) -> int:
        title = f"Un-exercised test helper: {fake}.{method}"
        body = (
            f"## Fake coverage gap — test helper\n\n"
            f"Fake class `{fake}` exposes helper `{method}` but no scenario "
            f"under `tests/scenarios/` invokes it (grep-based search).\n\n"
            f"**Repair:** add a scenario that calls `{method}` so the helper "
            f"is part of the working contract. Spec §4.7."
        )
        return await self._pr.create_issue(
            title, body,
            ["hydraflow-find", "fake-coverage-gap", "test-helper"],
        )

    async def _file_escalation(self, key: str, attempts: int) -> int:
        title = f"HITL: fake coverage gap {key} unresolved after {attempts}"
        body = (
            f"`fake_coverage_auditor` has re-filed the `{key}` gap "
            f"{attempts} times without closure. Human review needed.\n\n"
            f"_Spec §3.2: closing this issue clears the dedup key._"
        )
        return await self._pr.create_issue(
            title, body, ["hitl-escalation", "fake-coverage-stuck"]
        )

    async def _reconcile_closed_escalations(self) -> None:
        cmd = [
            "gh", "issue", "list",
            "--repo", self._config.repo,
            "--state", "closed",
            "--label", "hitl-escalation",
            "--label", "fake-coverage-stuck",
            "--author", "@me",
            "--limit", "100",
            "--json", "title",
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
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
            for key in list(keep):
                if (
                    key.startswith("fake_coverage_auditor:")
                    and key.split(":", 1)[1] in title
                ):
                    keep.discard(key)
                    self._state.clear_fake_coverage_attempts(
                        key.split(":", 1)[1]
                    )
        if keep != current:
            self._dedup.set_all(keep)

    async def _do_work(self) -> WorkCycleResult:
        """Scan fakes, compare to cassettes + scenario grep, file gaps."""
        t0 = time.perf_counter()
        await self._reconcile_closed_escalations()

        repo = self._config.repo_root
        fake_dir = repo / "tests" / "scenarios" / "fakes"
        cassette_root = repo / "tests" / "trust" / "contracts" / "cassettes"
        catalog = catalog_fake_methods(fake_dir)
        if not catalog:
            return {"status": "no_fakes", "filed": 0}

        filed = 0
        escalated = 0
        dedup = self._dedup.get()
        all_known: dict[str, list[str]] = {}
        for fake, sets in catalog.items():
            surface_methods = sets["adapter-surface"]
            helper_methods = sets["test-helper"]
            cassette_subdir = cassette_root / _FAKE_TO_CASSETTE_DIR.get(fake, "")
            cassetted = catalog_cassette_methods(cassette_subdir)

            covered: list[str] = []
            for method in surface_methods:
                if method in cassetted:
                    covered.append(method)
                    continue
                key = f"fake_coverage_auditor:{fake}.{method}:adapter-surface"
                if key in dedup:
                    continue
                attempts = self._state.inc_fake_coverage_attempts(
                    f"{fake}.{method}:adapter-surface"
                )
                if attempts >= _MAX_ATTEMPTS:
                    await self._file_escalation(
                        f"{fake}.{method}:adapter-surface", attempts
                    )
                    escalated += 1
                else:
                    await self._file_surface_gap(fake, method)
                    filed += 1
                dedup.add(key)
                self._dedup.set_all(dedup)

            for method in helper_methods:
                if await self._grep_scenario_for_helper(method):
                    covered.append(method)
                    continue
                key = f"fake_coverage_auditor:{fake}.{method}:test-helper"
                if key in dedup:
                    continue
                attempts = self._state.inc_fake_coverage_attempts(
                    f"{fake}.{method}:test-helper"
                )
                if attempts >= _MAX_ATTEMPTS:
                    await self._file_escalation(
                        f"{fake}.{method}:test-helper", attempts
                    )
                    escalated += 1
                else:
                    await self._file_helper_gap(fake, method)
                    filed += 1
                dedup.add(key)
                self._dedup.set_all(dedup)

            all_known[fake] = sorted(covered)

        self._state.set_fake_coverage_last_known(all_known)
        self._emit_trace(t0, fakes_seen=len(catalog))
        return {
            "status": "ok",
            "filed": filed,
            "escalated": escalated,
            "fakes_seen": len(catalog),
        }

    def _emit_trace(self, t0: float, *, fakes_seen: int) -> None:
        try:
            from trace_collector import emit_loop_subprocess_trace  # noqa: PLC0415
        except ImportError:
            return
        emit_loop_subprocess_trace(
            worker_name=self._worker_name,
            command=["ast.parse", "fakes/"],
            exit_code=0,
            duration_s=time.perf_counter() - t0,
            stdout_tail=f"fakes={fakes_seen}",
            stderr_tail="",
        )
```

- [ ] **Step 4: Run tests**

```bash
PYTHONPATH=src uv run pytest tests/test_fake_coverage_auditor_loop.py -v
```

Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/fake_coverage_auditor_loop.py tests/test_fake_coverage_auditor_loop.py
git commit -m "feat(loop): FakeCoverageAuditorLoop + AST + cassette catalog (§4.7)"
```

---

### Task C4: Tick behavior test — gap filing + subtype labels

**Files:**
- Modify: `tests/test_fake_coverage_auditor_loop.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_fake_coverage_auditor_loop.py`:

```python
async def test_do_work_files_surface_gap(loop_env, monkeypatch, tmp_path) -> None:
    cfg, state, pr, dedup = loop_env
    # Layout: one fake, one un-cassetted method.
    fake_dir = tmp_path / "tests" / "scenarios" / "fakes"
    fake_dir.mkdir(parents=True)
    (fake_dir / "fake_github.py").write_text(
        "class FakeGitHub:\n"
        "    async def create_issue(self, title): ...\n"
        "    async def close_issue(self, n): ...\n"
    )
    cassettes = tmp_path / "tests" / "trust" / "contracts" / "cassettes" / "github"
    cassettes.mkdir(parents=True)
    (cassettes / "create_issue.json").write_text(
        json.dumps({"input": {"command": "create_issue"}})
    )
    # close_issue uncassetted → expect one adapter-surface gap.

    stop = asyncio.Event()
    loop = FakeCoverageAuditorLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )

    async def fake_reconcile():
        return None

    monkeypatch.setattr(loop, "_reconcile_closed_escalations", fake_reconcile)

    stats = await loop._do_work()
    assert stats["filed"] == 1
    labels = pr.create_issue.await_args.args[2]
    assert "adapter-surface" in labels
    assert "fake-coverage-gap" in labels


async def test_do_work_files_helper_gap(loop_env, monkeypatch, tmp_path) -> None:
    cfg, state, pr, dedup = loop_env
    fake_dir = tmp_path / "tests" / "scenarios" / "fakes"
    fake_dir.mkdir(parents=True)
    (fake_dir / "fake_docker.py").write_text(
        "class FakeDocker:\n"
        "    def script_run(self, events): ...\n"
    )
    cassettes = tmp_path / "tests" / "trust" / "contracts" / "cassettes" / "docker"
    cassettes.mkdir(parents=True)

    stop = asyncio.Event()
    loop = FakeCoverageAuditorLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )

    async def fake_reconcile():
        return None

    async def fake_grep(helper):
        return False  # no scenario calls the helper

    monkeypatch.setattr(loop, "_reconcile_closed_escalations", fake_reconcile)
    monkeypatch.setattr(loop, "_grep_scenario_for_helper", fake_grep)

    stats = await loop._do_work()
    assert stats["filed"] == 1
    labels = pr.create_issue.await_args.args[2]
    assert "test-helper" in labels
    title = pr.create_issue.await_args.args[0]
    assert "script_run" in title


async def test_escalation_fires_after_three_attempts(loop_env, monkeypatch, tmp_path) -> None:
    cfg, state, pr, dedup = loop_env
    state.inc_fake_coverage_attempts.return_value = 3
    fake_dir = tmp_path / "tests" / "scenarios" / "fakes"
    fake_dir.mkdir(parents=True)
    (fake_dir / "fake_github.py").write_text(
        "class FakeGitHub:\n    async def missing(self): ...\n"
    )
    (tmp_path / "tests" / "trust" / "contracts" / "cassettes" / "github").mkdir(parents=True)

    stop = asyncio.Event()
    loop = FakeCoverageAuditorLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )

    async def fake_reconcile():
        return None

    monkeypatch.setattr(loop, "_reconcile_closed_escalations", fake_reconcile)

    stats = await loop._do_work()
    assert stats["escalated"] == 1
    labels = pr.create_issue.await_args.args[2]
    assert "hitl-escalation" in labels
    assert "fake-coverage-stuck" in labels
```

- [ ] **Step 2: Run tests**

```bash
PYTHONPATH=src uv run pytest tests/test_fake_coverage_auditor_loop.py -v
```

Expected: 6 PASS total (3 from C3 + 3 new).

- [ ] **Step 3: Commit**

```bash
git add tests/test_fake_coverage_auditor_loop.py
git commit -m "test(loop): FakeCoverage surface/helper gap filing + escalation (§4.7)"
```

---

### Task C5: Five-checkpoint wiring for `fake_coverage_auditor`

- [ ] **Step 1: `src/service_registry.py`**

Modify `src/service_registry.py:63` — add:

```python
from fake_coverage_auditor_loop import FakeCoverageAuditorLoop  # noqa: TCH001
```

Dataclass field (line 168 area):

```python
    fake_coverage_auditor_loop: FakeCoverageAuditorLoop
```

Inside `build_services`, after Phase 2's `skill_prompt_eval_loop` block:

```python
    fake_coverage_auditor_dedup = DedupStore(
        "fake_coverage_auditor",
        config.data_root / "dedup" / "fake_coverage_auditor.json",
    )
    fake_coverage_auditor_loop = FakeCoverageAuditorLoop(  # noqa: F841
        config=config,
        state=state,
        pr_manager=prs,
        dedup=fake_coverage_auditor_dedup,
        deps=loop_deps,
    )
```

Append to `ServiceRegistry(...)`:

```python
        fake_coverage_auditor_loop=fake_coverage_auditor_loop,
```

Commit:

```bash
git add src/service_registry.py
git commit -m "feat(wiring): FakeCoverageAuditorLoop in service registry"
```

- [ ] **Step 2: `src/orchestrator.py`**

Modify `src/orchestrator.py:159` — add to `bg_loop_registry`:

```python
            "fake_coverage_auditor": svc.fake_coverage_auditor_loop,
```

Modify `src/orchestrator.py:909` — add to `loop_factories`:

```python
            ("fake_coverage_auditor", self._svc.fake_coverage_auditor_loop.run),
```

Commit:

```bash
git add src/orchestrator.py
git commit -m "feat(wiring): orchestrator runs FakeCoverageAuditorLoop"
```

- [ ] **Step 3: `src/ui/src/constants.js`**

1. `EDITABLE_INTERVAL_WORKERS` (line 252): add `'fake_coverage_auditor'`.
2. `SYSTEM_WORKER_INTERVALS` (line 259+): add `fake_coverage_auditor: 604800,`.
3. `BACKGROUND_WORKERS` (line 293+): append:

```js
  { key: 'fake_coverage_auditor', label: 'Fake Coverage Auditor', description: 'Flags un-cassetted fake adapter methods and un-exercised test helpers.', color: theme.accent, group: 'learning', tags: ['quality'] },
```

Commit:

```bash
git add src/ui/src/constants.js
git commit -m "feat(ui): register fake_coverage_auditor in BACKGROUND_WORKERS"
```

- [ ] **Step 4: `src/dashboard_routes/_common.py`**

Modify `src/dashboard_routes/_common.py:32` — add:

```python
    "fake_coverage_auditor": (86400, 2_592_000),  # 1d min, 30d max
```

Commit:

```bash
git add src/dashboard_routes/_common.py
git commit -m "feat(dashboard): interval bounds for fake_coverage_auditor (1d–30d)"
```

- [ ] **Step 5: Verify wiring**

```bash
PYTHONPATH=src uv run pytest tests/test_loop_wiring_completeness.py -v
```

Expected: PASS.

---

### Task C6: MockWorld scenario — uncovered adapter + helper

**Files:**
- Create: `tests/scenarios/test_fake_coverage_scenario.py`

- [ ] **Step 1: Write the scenario**

Create `tests/scenarios/test_fake_coverage_scenario.py`:

```python
"""MockWorld scenario for FakeCoverageAuditorLoop (spec §4.7).

Two scenarios:
1. Adapter-surface gap: a fake method without a cassette → issue
   labeled `adapter-surface`.
2. Test-helper gap: `script_*` helper not invoked by any scenario →
   issue labeled `test-helper`.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.loop_port_seeding import seed_ports as _seed_ports

pytestmark = pytest.mark.scenario_loops


class TestFakeCoverageAuditor:
    """§4.7 — fake coverage drift."""

    async def test_uncassetted_surface_files_adapter_gap(self, tmp_path) -> None:
        world = MockWorld(tmp_path)
        world.config.repo_root = tmp_path
        fake_dir = tmp_path / "tests" / "scenarios" / "fakes"
        fake_dir.mkdir(parents=True)
        (fake_dir / "fake_github.py").write_text(
            "class FakeGitHub:\n"
            "    async def create_issue(self, title, body, labels): ...\n"
            "    async def close_issue(self, num): ...\n"
        )
        cassettes = tmp_path / "tests" / "trust" / "contracts" / "cassettes" / "github"
        cassettes.mkdir(parents=True)
        (cassettes / "create_issue.json").write_text(
            json.dumps({"input": {"command": "create_issue"}})
        )

        fake_pr = AsyncMock()
        fake_pr.create_issue = AsyncMock(return_value=501)
        _seed_ports(
            world,
            pr_manager=fake_pr,
            fake_coverage_reconcile_closed=AsyncMock(return_value=None),
            fake_coverage_grep=AsyncMock(return_value=True),  # helpers covered
        )

        await world.run_with_loops(["fake_coverage_auditor"], cycles=1)

        assert fake_pr.create_issue.await_count == 1
        labels = fake_pr.create_issue.await_args.args[2]
        assert "adapter-surface" in labels
        assert "fake-coverage-gap" in labels

    async def test_unused_test_helper_files_helper_gap(self, tmp_path) -> None:
        world = MockWorld(tmp_path)
        world.config.repo_root = tmp_path
        fake_dir = tmp_path / "tests" / "scenarios" / "fakes"
        fake_dir.mkdir(parents=True)
        (fake_dir / "fake_docker.py").write_text(
            "class FakeDocker:\n"
            "    def script_run(self, events): ...\n"
        )
        (tmp_path / "tests" / "trust" / "contracts" / "cassettes" / "docker").mkdir(
            parents=True
        )

        fake_pr = AsyncMock()
        fake_pr.create_issue = AsyncMock(return_value=502)
        _seed_ports(
            world,
            pr_manager=fake_pr,
            fake_coverage_reconcile_closed=AsyncMock(return_value=None),
            fake_coverage_grep=AsyncMock(return_value=False),  # helper uncalled
        )

        await world.run_with_loops(["fake_coverage_auditor"], cycles=1)

        assert fake_pr.create_issue.await_count == 1
        labels = fake_pr.create_issue.await_args.args[2]
        assert "test-helper" in labels
```

- [ ] **Step 2: Add ports to `loop_port_seeding.py`**

Modify `tests/scenarios/helpers/loop_port_seeding.py` — add support for `fake_coverage_reconcile_closed` (monkey-patches `loop._reconcile_closed_escalations`) and `fake_coverage_grep` (patches `loop._grep_scenario_for_helper`).

- [ ] **Step 3: Run**

```bash
PYTHONPATH=src uv run pytest tests/scenarios/test_fake_coverage_scenario.py -v -m scenario_loops
```

Expected: 2 PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/scenarios/test_fake_coverage_scenario.py tests/scenarios/helpers/loop_port_seeding.py
git commit -m "test(scenario): FakeCoverage surface + helper gaps (§4.7)"
```

---

### Task C7: Phase 3 close-out — quality gate + PR

- [ ] **Step 1: Full quality gate**

```bash
make quality
```

Expected: PASS.

- [ ] **Step 2: Push**

```bash
git push
```

- [ ] **Step 3: Open the PR**

```bash
gh pr create --title "feat(trust): caretaker fleet part 1 — flake + skill-eval + fake-coverage (§4.5-§4.7)" --body "$(cat <<'EOF'
## Summary

Lands three caretaker background loops per the Trust Architecture Hardening spec, following the §4.4 `PrinciplesAuditLoop` template:

- `FlakeTrackerLoop` (§4.5, 4h) — reads JUnit XML from the last 20 RC runs via `gh api` + `gh run download`, files `flaky-test` issues at `flake_count >= flake_threshold` (default 3).
- `SkillPromptEvalLoop` (§4.6, weekly) — runs the full `make trust-adversarial` corpus as a backstop; samples 10% of `provenance: learning-loop` cases for weak-case audit.
- `FakeCoverageAuditorLoop` (§4.7, weekly) — AST-introspects `tests/scenarios/fakes/` and diffs two method sets (adapter-surface, test-helper) against cassettes under `tests/trust/contracts/cassettes/` and a scenario grep.

All three honor §12.2 kill-switch via `LoopDeps.enabled_cb(worker_name)` — no new `*_enabled` config fields. Escalations at 3 repair attempts → `hitl-escalation` + `<loop>-stuck`. Close-to-clear dedup wired per §3.2.

Prerequisite `ci(rc)` commit adds `--junitxml` + `actions/upload-artifact@v4` to `rc-promotion-scenario.yml` so FlakeTracker has something to read.

## Test plan

- [ ] `PYTHONPATH=src uv run pytest tests/test_state_flake_tracker.py tests/test_state_skill_prompt_eval.py tests/test_state_fake_coverage.py -v`
- [ ] `PYTHONPATH=src uv run pytest tests/test_config_caretaker_fleet.py -v`
- [ ] `PYTHONPATH=src uv run pytest tests/test_flake_tracker_loop.py tests/test_skill_prompt_eval_loop.py tests/test_fake_coverage_auditor_loop.py -v`
- [ ] `PYTHONPATH=src uv run pytest tests/test_loop_wiring_completeness.py -v`
- [ ] `PYTHONPATH=src uv run pytest tests/scenarios/test_flake_tracker_scenario.py tests/scenarios/test_skill_prompt_eval_scenario.py tests/scenarios/test_fake_coverage_scenario.py -v -m scenario_loops`
- [ ] `make quality`

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 4: Verify PR URL**

Copy the PR URL from gh's output into the executor's final report.

---

## Summary

| Phase | Tasks | Output |
|---|---|---|
| 1 — FlakeTrackerLoop | F0–F8 (9 tasks) | JUnit upload + loop + tests + wiring + scenario |
| 2 — SkillPromptEvalLoop | S1–S7 (7 tasks) | loop + tests + wiring + scenario |
| 3 — FakeCoverageAuditorLoop | C1–C7 (7 tasks) | loop + tests + wiring + scenario + PR |

**Total: 23 tasks across 3 phases.**

All three loops share the same skeleton: `BaseBackgroundLoop` subclass with `worker_name`, `_get_default_interval`, `_do_work` that calls `_reconcile_closed_escalations` first then performs the loop-specific detection and filing. All three use `LoopDeps.enabled_cb(worker_name)` for kill-switch (§12.2) and `DedupStore.set_all(...)` for clearance on close (§3.2 — no `remove` method exists).

## Self-Review

**Spec coverage:**

- §4.5 steps 1–4 — Task F0 (JUnit upload), F3 (skeleton + parser), F4 (tick + artifact download + filing), F5 (escalation + close-reconcile), F7 (scenario).
- §4.6 steps 1–4 — Task S3 (skeleton + tick), S4 (escalation + close-reconcile), S6 (scenario).
- §4.7 steps 1–5 — Task C3 (AST + skeleton), C4 (filing + escalation), C6 (scenario).
- §3.2 escalation lifecycle — `_reconcile_closed_escalations` helper tested per loop (F5, S4, C4 implicit via tick).
- §12.2 kill-switch — `enabled_cb` is inherited from `BaseBackgroundLoop`; no new config field (explicit decision #11).
- §4.5 "3 fails in 20 runs uses `>=`" — covered by `count < threshold: continue` in F4 Step 3 (the skip condition uses `<`, so `>=` fires).
- §4.6 weak-case sampling 10% — seed-stable `random.Random` in `_sample_learning_cases` (S3 Step 3).
- §4.7 two method sets with subtype labels — `catalog_fake_methods` returns both sets (C3 Step 3).

**Placeholder scan:** No "TBD", "TODO", "implement later", or "fill in details" blocks. The `loop_port_seeding.py` modifications are intentionally left flexible (tests reference `PrinciplesAuditLoop`'s sibling scenario for exact pattern) — see Task F7 Step 2, S6 Step 2, C6 Step 2.

**Type consistency:**

- `worker_name` strings are identical across config, mixin key prefixes, service registry, orchestrator, UI, dashboard bounds, test fixtures, issue titles, and escalation label suffixes: `flake_tracker`, `skill_prompt_eval`, `fake_coverage_auditor`.
- `DedupStore` uses `.get()` / `.add()` / `.set_all()` everywhere — no `.remove()` or `.discard()` (the real class doesn't have them).
- `PRManager.create_issue(title, body, labels)` three-arg form used consistently.
- State mixin method names (`get_*`, `set_*`, `inc_*_attempts`, `clear_*_attempts`) parallel the `CIMonitorStateMixin` reference template.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-22-caretaker-fleet-part-1.md`. Two execution options:

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks.
2. **Inline Execution** — execute tasks in this session using `superpowers:executing-plans`, batch with checkpoints.

Which approach?
