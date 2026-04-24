# Cost Waterfall Helper + Issue Endpoint — §4.11 (Points 1 + 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Land two load-bearing §4.11 deliverables — the `trace_collector.emit_loop_subprocess_trace` helper (spec point 3) and the `/api/diagnostics/issue/{issue}/waterfall` endpoint (spec point 1). This plan deliberately excludes §4.11 points 2, 4, 5, 6 (UI sub-tab, aggregate rollups, per-loop dashboard, cost budget alerts) — those belong to follow-up Plan 6b-2. This is the half that every other trust-fleet plan (principles-audit, rc-budget, wiki-rot, trust-fleet-sanity, flake-tracker, skill-prompt-eval, fake-coverage-auditor, corpus-learning, contract-refresh, staging-bisect) already lazy-imports — ship it and their `try/except ImportError` fallback resolves.

**Architecture:** One new module-level function `emit_loop_subprocess_trace` in `src/trace_collector.py` that writes a self-contained trace file (no `TraceCollector` instance, no stream). One new helper module `src/dashboard_routes/_waterfall_builder.py` that reads existing `SubprocessTrace` JSON files and `prompt_telemetry` inference rows, groups by phase, orders actions chronologically, and computes cost on the fly via `ModelPricing.estimate_cost`. One new route appended to `src/dashboard_routes/_diagnostics_routes.py`. Missing-telemetry paths degrade to partial rollups with a `missing_phases: [...]` field.

**Spec refs:** `docs/superpowers/specs/2026-04-22-trust-architecture-hardening-design.md` §4.11 points 1 + 3.

**Decisions locked (grounded in the codebase):**

1. **No `TraceCollector` singleton exists.** `TraceCollector` is instantiated per `claude -p` subprocess by `base_runner.py:151-153` and passed through `runner_utils.StreamConfig.trace_collector`. A module-level singleton would contradict that architecture. `emit_loop_subprocess_trace` is therefore a **free function** that writes a standalone `{kind: "loop", ...}` subprocess trace file directly — no delegation to a singleton, because there is none. (The task spec phrasing "delegates to the existing `TraceCollector` singleton" is a misread of the module; the correct factoring is free-function → filesystem, same directory layout as `TraceCollector._finalize_inner` at `src/trace_collector.py:348-357`.)
2. **Trace file layout mirrors existing.** Loop traces write to `<data_root>/traces/_loops/<loop_slug>/run-<ts>.json` — a dedicated `_loops` subtree since loops are not issue-scoped. `<loop_slug>` is `loop.lower()` with non-alnum → `_`. `<ts>` is an ISO-8601-derived monotonic-safe slug (`datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")`) so multiple ticks within the same second still get distinct files.
3. **Stderr truncation cap** is 2048 chars, tail-preserving (`stderr_excerpt[-2048:]`). A loop subprocess that dumps 50 MB of Python traceback should not bloat the trace; the tail usually carries the actionable error.
4. **Failure semantics match `TraceCollector`.** The helper is wrapped `try/except` + warning log. A broken trace write MUST NOT crash the loop tick. Returns `None`; callers don't check.
5. **Phase order is canonical seven** from the spec shape: `triage → discover → shape → plan → implement → review → merge`. `hitl` and other off-pipeline stages are **collapsed into the nearest pipeline phase** (`hitl → review`) so the waterfall stays a 7-row strip. (Rationale: the waterfall is a *factory-operator* view; off-pipeline stages live in the existing `/issue/{issue}/{phase}` drill-down.)
6. **Action ordering within phase** is by the action's `started_at` timestamp. Ties break by `(kind, model/skill/loop/command)` string to keep output deterministic for tests.
7. **Cost re-priced on every request.** The waterfall does **not** read stored `estimated_cost_usd` from prompt telemetry rows — it re-computes via `ModelPricing.estimate_cost(model, input_tokens, output_tokens, cache_write_tokens, cache_read_tokens)` so a post-hoc pricing-sheet update retroactively re-prices history. Storage is token counts only.
8. **Issue metadata source** is `IssueFetcher.fetch_issue_by_number` (already wired via `service_registry`). If the fetch fails (closed/deleted issue), fall back to the cached `GitHubIssue` shape with empty labels + title `"(unknown)"` rather than 404ing — the waterfall is a diagnostic; it should work on ghost issues too.
9. **Missing-phase policy.** A phase with zero actions AND zero subprocess traces is listed in top-level `missing_phases: [...]` and **omitted** from the `phases: [...]` array (not emitted as an empty row). The caller can distinguish "this phase didn't run" from "this phase ran with zero cost". A phase with actions-but-no-traces is rendered with what's available; it does **not** appear in `missing_phases`.
10. **`kind: "loop"` actions** come from the new `_loops` trace tree, not from prompt telemetry (loop-subprocess calls aren't LLM calls). `kind: "llm"` and `kind: "skill"` come from `prompt_telemetry.inferences.jsonl` filtered by `issue_number`. `kind: "subprocess"` comes from `SubprocessTrace.tool_calls` with `tool_name == "Bash"` aggregated by command. Loop-attribution-to-issue is inferred by temporal overlap: if a `_loops` trace's `started_at` falls between `first_seen` and `merged_at` of the issue, it attaches to the issue's current phase at that moment. This is **best-effort**; the primary home for loop costs is the per-loop dashboard in follow-up Plan 6b-2. In this plan the issue waterfall shows loop actions only when the loop was clearly running during that issue's active window.

---

## File structure

| File | Role | C/M |
|---|---|---|
| `src/trace_collector.py` | Append module-level `emit_loop_subprocess_trace` + helper `_loop_trace_dir`, `_slug_for_loop` | M |
| `tests/test_trace_collector_loop_helper.py` | Unit tests for the helper — emission shape, directory layout, stderr truncation, missing-dir tolerance, non-raising semantics | C |
| `src/dashboard_routes/_waterfall_builder.py` | New aggregator — reads traces + telemetry, groups by phase, computes cost on the fly | C |
| `tests/test_waterfall_builder.py` | Unit tests — all four `kind` values, chronological ordering, missing-phase handling, cost re-pricing, unknown-model fallback | C |
| `src/dashboard_routes/_diagnostics_routes.py` | Append `/issue/{issue}/waterfall` route + import wiring | M |
| `tests/test_diagnostics_waterfall_route.py` | Integration test — full fixture issue with all phases + all kinds; partial-telemetry path | C |

---

## Task 1 — Module-level helper in `trace_collector.py`

**Modify** `src/trace_collector.py` (append after class `TraceCollector` at EOF):

- [ ] **Step 1: Write failing tests** — `tests/test_trace_collector_loop_helper.py`:

```python
"""Tests for emit_loop_subprocess_trace (spec §4.11 point 3)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from trace_collector import (
    _loop_trace_dir,
    _slug_for_loop,
    emit_loop_subprocess_trace,
)


@pytest.fixture
def data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "data"
    root.mkdir()
    cfg = MagicMock()
    cfg.data_root = root
    monkeypatch.setattr("trace_collector._current_config", lambda: cfg)
    return root


def test_slug_for_loop_lowercases_and_replaces_nonalnum() -> None:
    assert _slug_for_loop("RCBudgetLoop") == "rcbudgetloop"
    assert _slug_for_loop("Trust Fleet / Sanity") == "trust_fleet___sanity"
    assert _slug_for_loop("") == "unknown"


def test_loop_trace_dir_nested_under_data_root(data_root: Path) -> None:
    out = _loop_trace_dir("CorpusLearningLoop")
    assert out.is_relative_to(data_root / "traces" / "_loops")
    assert out.name == "corpuslearningloop"


def test_emit_writes_trace_entry_with_required_shape(data_root: Path) -> None:
    emit_loop_subprocess_trace(
        loop="CorpusLearningLoop",
        command=["gh", "api", "repos/o/r/issues"],
        exit_code=0,
        duration_ms=1234,
    )
    files = list((data_root / "traces" / "_loops" / "corpuslearningloop").glob("run-*.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["kind"] == "loop"
    assert payload["loop"] == "CorpusLearningLoop"
    assert payload["command"] == ["gh", "api", "repos/o/r/issues"]
    assert payload["exit_code"] == 0
    assert payload["duration_ms"] == 1234
    assert payload["stderr"] is None
    assert "started_at" in payload  # ISO 8601


def test_emit_truncates_stderr_tail_preserving(data_root: Path) -> None:
    big = "A" * 4096 + "TAIL_MARKER"
    emit_loop_subprocess_trace(
        loop="X",
        command=["/bin/true"],
        exit_code=1,
        duration_ms=5,
        stderr_excerpt=big,
    )
    files = list((data_root / "traces" / "_loops" / "x").glob("run-*.json"))
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["stderr"] is not None
    assert len(payload["stderr"]) == 2048
    assert payload["stderr"].endswith("TAIL_MARKER")


def test_emit_never_raises_on_missing_config_or_oserror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # Case 1: no active config — must no-op silently.
    monkeypatch.setattr("trace_collector._current_config", lambda: None)
    emit_loop_subprocess_trace(loop="Z", command=["x"], exit_code=0, duration_ms=1)
    assert not any(tmp_path.rglob("run-*.json"))

    # Case 2: config present, filesystem broken — must log + swallow.
    cfg = MagicMock()
    cfg.data_root = tmp_path
    monkeypatch.setattr("trace_collector._current_config", lambda: cfg)
    monkeypatch.setattr(Path, "write_text", lambda *a, **kw: (_ for _ in ()).throw(OSError("full")))
    emit_loop_subprocess_trace(loop="Q", command=["x"], exit_code=0, duration_ms=1)
    assert any("emit_loop_subprocess_trace failed" in r.message for r in caplog.records)
```

- [ ] **Step 2: Run — expect FAIL** (helper does not exist yet).

- [ ] **Step 3: Append to `src/trace_collector.py` (EOF):**

```python
# ---------------------------------------------------------------------------
# Loop-subprocess trace helper (spec §4.11 point 3)
# ---------------------------------------------------------------------------
#
# Loops (CorpusLearningLoop, ContractRefreshLoop, StagingBisectLoop,
# PrinciplesAuditLoop, FlakeTrackerLoop, SkillPromptEvalLoop,
# FakeCoverageAuditorLoop, RCBudgetLoop, WikiRotDetectorLoop,
# TrustFleetSanityLoop) run outside the `claude -p` stream, so they cannot
# use the class-based `TraceCollector`. This free function writes a
# self-contained loop-kind trace file to `<data_root>/traces/_loops/<slug>/`.
# Every loop plan lazy-imports it via `try/except ImportError` so a missing
# helper degrades gracefully; once this module lands, those imports resolve.

import re
import threading

_STDERR_TRUNC_CAP = 2048
_CONFIG_LOCK = threading.Lock()
_ACTIVE_CONFIG: HydraFlowConfig | None = None


def set_active_config(config: HydraFlowConfig | None) -> None:
    """Register the process-wide active config for free-function helpers.

    Called once during orchestrator startup (see `src/orchestrator.py` —
    wire this in Task 1 Step 4). Free-function helpers like
    `emit_loop_subprocess_trace` read it to resolve `data_root` without
    threading a config through every loop subprocess call.
    """
    global _ACTIVE_CONFIG
    with _CONFIG_LOCK:
        _ACTIVE_CONFIG = config


def _current_config() -> HydraFlowConfig | None:
    with _CONFIG_LOCK:
        return _ACTIVE_CONFIG


def _slug_for_loop(loop: str) -> str:
    slug = re.sub(r"[^a-z0-9]", "_", (loop or "").lower()).strip("_")
    return slug or "unknown"


def _loop_trace_dir(loop: str) -> Path:
    cfg = _current_config()
    if cfg is None:
        raise RuntimeError("No active HydraFlowConfig registered")
    from pathlib import Path  # noqa: PLC0415 — local to avoid top-level churn
    return Path(cfg.data_root) / "traces" / "_loops" / _slug_for_loop(loop)


def emit_loop_subprocess_trace(
    loop: str,
    command: list[str],
    exit_code: int,
    duration_ms: int,
    stderr_excerpt: str | None = None,
) -> None:
    """Emit a per-loop subprocess trace file.

    Writes `{"kind": "loop", "loop": "<name>", "command": [...], "exit_code":
    N, "duration_ms": N, "stderr": "..."}` to `<data_root>/traces/_loops/
    <slug>/run-<iso>.json`. Stderr is tail-truncated to 2048 chars.

    Never raises. A broken filesystem, missing config, or any other error
    is logged at WARNING and swallowed — a loop tick must survive this.
    """
    try:
        cfg = _current_config()
        if cfg is None:
            logger.debug("emit_loop_subprocess_trace: no active config; skipping")
            return

        from pathlib import Path  # noqa: PLC0415

        stderr = stderr_excerpt[-_STDERR_TRUNC_CAP:] if stderr_excerpt else None
        started_at = datetime.now(UTC).isoformat()
        slug_ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")

        payload = {
            "kind": "loop",
            "loop": loop,
            "command": list(command),
            "exit_code": int(exit_code),
            "duration_ms": int(duration_ms),
            "stderr": stderr,
            "started_at": started_at,
        }

        out_dir = _loop_trace_dir(loop)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"run-{slug_ts}.json"
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception:
        logger.warning("emit_loop_subprocess_trace failed", exc_info=True)
```

- [ ] **Step 4: Wire `set_active_config` into orchestrator startup** —
`Modify` `src/orchestrator.py` (after `HydraFlowConfig` is resolved, before loops boot):

```
Modify: src/orchestrator.py:<startup-init block, search for "config = load_config"> — add immediately after:
    from trace_collector import set_active_config  # noqa: PLC0415
    set_active_config(config)
```

The orchestrator is the single process-wide lifecycle owner. Tests stub `_current_config` directly; production code wires once at boot.

- [ ] **Step 5: Run — expect PASS.**

- [ ] **Step 6: Commit** `feat(trace): emit_loop_subprocess_trace helper (§4.11 point 3)`

---

## Task 2 — Phase-action aggregator module

**Create** `src/dashboard_routes/_waterfall_builder.py`.

- [ ] **Step 1: Write failing tests** — `tests/test_waterfall_builder.py`:

```python
"""Tests for waterfall_builder (spec §4.11 point 1 aggregator)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from dashboard_routes._waterfall_builder import (
    PHASE_ORDER,
    build_waterfall,
    _phase_for_source,
)


@pytest.fixture
def config(tmp_path: Path) -> MagicMock:
    cfg = MagicMock()
    cfg.data_root = tmp_path
    cfg.data_path = lambda *parts: tmp_path.joinpath(*parts)
    cfg.repo = "o/r"
    return cfg


def _write_trace(config: MagicMock, issue: int, phase: str, run_id: int, idx: int, payload: dict) -> None:
    run_dir = config.data_root / "traces" / str(issue) / phase / f"run-{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / f"subprocess-{idx}.json").write_text(json.dumps(payload), encoding="utf-8")


def _write_inference(config: MagicMock, **fields) -> None:
    inf_dir = config.data_root / "metrics" / "prompt"
    inf_dir.mkdir(parents=True, exist_ok=True)
    path = inf_dir / "inferences.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(fields) + "\n")


def _write_loop_trace(config: MagicMock, loop: str, **fields) -> None:
    from trace_collector import _slug_for_loop  # noqa: PLC0415
    d = config.data_root / "traces" / "_loops" / _slug_for_loop(loop)
    d.mkdir(parents=True, exist_ok=True)
    payload = {"kind": "loop", "loop": loop, **fields}
    (d / f"run-{fields.get('started_at', '2026-04-22T10:00:00+00:00').replace(':', '')}.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def test_phase_order_is_canonical_seven() -> None:
    assert PHASE_ORDER == (
        "triage", "discover", "shape", "plan", "implement", "review", "merge",
    )


def test_phase_for_source_collapses_offpipeline() -> None:
    assert _phase_for_source("hitl") == "review"
    assert _phase_for_source("decomposition") == "triage"
    assert _phase_for_source("planner") == "plan"
    assert _phase_for_source("unknown_xyz") == "unknown_xyz"


def test_builds_empty_waterfall_with_all_phases_missing(config) -> None:
    issue_meta = {"number": 1234, "title": "t", "labels": []}
    result = build_waterfall(config, issue=1234, issue_meta=issue_meta)
    assert result["issue"] == 1234
    assert result["title"] == "t"
    assert result["labels"] == []
    assert result["phases"] == []
    assert set(result["missing_phases"]) == set(PHASE_ORDER)
    assert result["total"]["cost_usd"] == 0.0


def test_llm_action_sourced_from_prompt_telemetry(config) -> None:
    _write_inference(
        config,
        timestamp="2026-04-22T10:00:00+00:00",
        source="implementer",
        tool="claude",
        model="claude-sonnet-4-6",
        issue_number=1234,
        input_tokens=1000,
        output_tokens=500,
        cache_creation_input_tokens=100,
        cache_read_input_tokens=200,
        duration_seconds=12.3,
        status="success",
    )
    pricing = MagicMock()
    pricing.estimate_cost.return_value = 0.042
    result = build_waterfall(
        config, issue=1234, issue_meta={"number": 1234, "title": "t", "labels": []}, pricing=pricing
    )
    phases = {p["phase"]: p for p in result["phases"]}
    assert "implement" in phases
    actions = phases["implement"]["actions"]
    assert len(actions) == 1
    a = actions[0]
    assert a["kind"] == "llm"
    assert a["model"] == "claude-sonnet-4-6"
    assert a["tokens_in"] == 1000
    assert a["tokens_out"] == 500
    assert a["cost_usd"] == 0.042
    pricing.estimate_cost.assert_called_once_with(
        "claude-sonnet-4-6",
        input_tokens=1000,
        output_tokens=500,
        cache_write_tokens=100,
        cache_read_tokens=200,
    )


def test_skill_action_from_subprocess_trace_skill_results(config) -> None:
    _write_trace(
        config, issue=1234, phase="review", run_id=1, idx=1,
        payload={
            "issue_number": 1234, "phase": "review", "source": "reviewer",
            "run_id": 1, "subprocess_idx": 1, "backend": "claude",
            "started_at": "2026-04-22T11:00:00+00:00",
            "ended_at": "2026-04-22T11:00:30+00:00",
            "success": True,
            "tokens": {"prompt_tokens": 0, "completion_tokens": 0,
                       "cache_read_tokens": 0, "cache_creation_tokens": 0,
                       "cache_hit_rate": 0.0},
            "tools": {"tool_counts": {}, "tool_errors": {}, "total_invocations": 0},
            "tool_calls": [],
            "skill_results": [
                {"skill_name": "diff-sanity", "passed": True, "attempts": 1,
                 "duration_seconds": 3.5, "blocking": True},
            ],
            "inference_count": 0, "turn_count": 0,
        },
    )
    result = build_waterfall(
        config, issue=1234, issue_meta={"number": 1234, "title": "t", "labels": []}
    )
    phases = {p["phase"]: p for p in result["phases"]}
    actions = phases["review"]["actions"]
    skill = next(a for a in actions if a["kind"] == "skill")
    assert skill["skill"] == "diff-sanity"
    assert skill["duration_ms"] == 3500


def test_subprocess_action_from_bash_tool_calls(config) -> None:
    _write_trace(
        config, issue=1234, phase="implement", run_id=1, idx=1,
        payload={
            "issue_number": 1234, "phase": "implement", "source": "implementer",
            "run_id": 1, "subprocess_idx": 1, "backend": "claude",
            "started_at": "2026-04-22T10:00:00+00:00",
            "ended_at": "2026-04-22T10:05:00+00:00",
            "success": True,
            "tokens": {"prompt_tokens": 0, "completion_tokens": 0,
                       "cache_read_tokens": 0, "cache_creation_tokens": 0,
                       "cache_hit_rate": 0.0},
            "tools": {"tool_counts": {"Bash": 2}, "tool_errors": {}, "total_invocations": 2},
            "tool_calls": [
                {"tool_name": "Bash",
                 "started_at": "2026-04-22T10:01:00+00:00",
                 "duration_ms": 800,
                 "input_summary": "pytest tests/test_x.py",
                 "succeeded": True, "tool_use_id": "t1"},
                {"tool_name": "Bash",
                 "started_at": "2026-04-22T10:02:00+00:00",
                 "duration_ms": 120,
                 "input_summary": "git status",
                 "succeeded": True, "tool_use_id": "t2"},
            ],
            "skill_results": [], "inference_count": 0, "turn_count": 0,
        },
    )
    result = build_waterfall(
        config, issue=1234, issue_meta={"number": 1234, "title": "t", "labels": []}
    )
    phases = {p["phase"]: p for p in result["phases"]}
    sp = [a for a in phases["implement"]["actions"] if a["kind"] == "subprocess"]
    assert len(sp) == 2
    assert sp[0]["command"].startswith("pytest")
    assert sp[0]["duration_ms"] == 800
    assert sp[1]["command"] == "git status"


def test_loop_attached_only_when_in_issue_window(config) -> None:
    _write_loop_trace(
        config, loop="CorpusLearningLoop",
        command=["gh", "api", "search/issues"],
        exit_code=0, duration_ms=2200,
        started_at="2026-04-22T10:30:00+00:00",  # inside window
    )
    _write_loop_trace(
        config, loop="CorpusLearningLoop",
        command=["x"], exit_code=0, duration_ms=1,
        started_at="2026-04-25T10:30:00+00:00",  # after merge — excluded
    )
    issue_meta = {
        "number": 1234, "title": "t", "labels": [],
        "first_seen": "2026-04-22T10:00:00+00:00",
        "merged_at": "2026-04-22T11:00:00+00:00",
    }
    result = build_waterfall(config, issue=1234, issue_meta=issue_meta)
    loops = [a for p in result["phases"] for a in p["actions"] if a["kind"] == "loop"]
    assert len(loops) == 1
    assert loops[0]["duration_ms"] == 2200


def test_ordering_total_and_missing_phases(config) -> None:
    # Two impl inferences (out-of-order write) + one reviewer inference.
    _write_inference(
        config, timestamp="2026-04-22T10:05:00+00:00",
        source="implementer", tool="claude", model="claude-sonnet-4-6",
        issue_number=1234, input_tokens=100, output_tokens=50,
        cache_creation_input_tokens=10, cache_read_input_tokens=20,
        duration_seconds=5, status="success",
    )
    _write_inference(
        config, timestamp="2026-04-22T10:02:00+00:00",
        source="implementer", tool="claude", model="claude-sonnet-4-6",
        issue_number=1234, input_tokens=20, output_tokens=10,
        cache_creation_input_tokens=0, cache_read_input_tokens=0,
        duration_seconds=1, status="success",
    )
    _write_inference(
        config, timestamp="2026-04-22T11:00:00+00:00",
        source="reviewer", tool="claude", model="claude-sonnet-4-6",
        issue_number=1234, input_tokens=200, output_tokens=80,
        cache_creation_input_tokens=0, cache_read_input_tokens=40,
        duration_seconds=7, status="success",
    )
    pricing = MagicMock()
    pricing.estimate_cost.side_effect = [0.01, 0.005, 0.02]
    result = build_waterfall(
        config, issue=1234, issue_meta={"number": 1234, "title": "t", "labels": []},
        pricing=pricing,
    )
    # Ordering within phase
    impl = next(p for p in result["phases"] if p["phase"] == "implement")
    assert [a["started_at"] for a in impl["actions"]] == sorted(
        a["started_at"] for a in impl["actions"]
    )
    # Total rollup across phases
    assert result["total"]["tokens_in"] == 320
    assert result["total"]["tokens_out"] == 140
    assert result["total"]["cache_read_tokens"] == 60
    assert result["total"]["cache_write_tokens"] == 10
    assert result["total"]["cost_usd"] == pytest.approx(0.035)
    # Missing phases: everything except implement + review
    assert set(result["missing_phases"]) == set(PHASE_ORDER) - {"implement", "review"}


def test_unknown_model_yields_zero_cost_no_crash(config) -> None:
    _write_inference(
        config, timestamp="2026-04-22T10:00:00+00:00",
        source="implementer", tool="claude", model="made-up-model-xyz",
        issue_number=1234, input_tokens=100, output_tokens=50,
        cache_creation_input_tokens=0, cache_read_input_tokens=0,
        duration_seconds=1, status="success",
    )
    pricing = MagicMock()
    pricing.estimate_cost.return_value = None
    result = build_waterfall(
        config, issue=1234, issue_meta={"number": 1234, "title": "t", "labels": []},
        pricing=pricing,
    )
    impl = next(p for p in result["phases"] if p["phase"] == "implement")
    # Unknown-model cost is 0.0 (not None) in the rollup; the action keeps model id.
    assert impl["cost_usd"] == 0.0
    assert impl["actions"][0]["cost_usd"] == 0.0
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Write `src/dashboard_routes/_waterfall_builder.py`:**

```python
"""Issue-level cost waterfall aggregator (spec §4.11 point 1).

Reads `<data_root>/traces/<issue>/<phase>/run-N/subprocess-*.json` and
`<data_root>/metrics/prompt/inferences.jsonl`, groups actions by canonical
phase, orders chronologically, and computes cost on the fly via
`ModelPricing.estimate_cost` so pricing-sheet updates retroactively
re-price historical issues.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from model_pricing import ModelPricingTable, load_pricing
from tracing_context import source_to_phase

if TYPE_CHECKING:
    from config import HydraFlowConfig

logger = logging.getLogger("hydraflow.dashboard.waterfall")

PHASE_ORDER: tuple[str, ...] = (
    "triage", "discover", "shape", "plan", "implement", "review", "merge",
)

# Off-pipeline sources that fold into a canonical phase for the waterfall.
_OFFPIPELINE_FOLD: dict[str, str] = {
    "hitl": "review",
    "find": "triage",
}


def _phase_for_source(source: str) -> str:
    """Map a runner source to a canonical waterfall phase."""
    canonical = source_to_phase(source)
    return _OFFPIPELINE_FOLD.get(canonical, canonical)


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts


def _load_inferences_for_issue(config: HydraFlowConfig, issue: int) -> list[dict[str, Any]]:
    path = config.data_path("metrics", "prompt", "inferences.jsonl")
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(rec, dict) and rec.get("issue_number") == issue:
                    rows.append(rec)
    except OSError:
        logger.warning("Failed to read inferences for waterfall", exc_info=True)
    return rows


def _load_subprocess_traces(
    config: HydraFlowConfig, issue: int
) -> list[dict[str, Any]]:
    base = config.data_root / "traces" / str(issue)
    if not base.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for sub_path in base.rglob("subprocess-*.json"):
        try:
            data = json.loads(sub_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            out.append(data)
    return out


def _load_loop_traces_in_window(
    config: HydraFlowConfig,
    first_seen: datetime | None,
    merged_at: datetime | None,
) -> list[dict[str, Any]]:
    if first_seen is None:
        return []
    base = config.data_root / "traces" / "_loops"
    if not base.is_dir():
        return []
    out: list[dict[str, Any]] = []
    upper = merged_at or datetime.now(UTC)
    for run_path in base.rglob("run-*.json"):
        try:
            data = json.loads(run_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict) or data.get("kind") != "loop":
            continue
        started = _parse_iso(data.get("started_at"))
        if started is None:
            continue
        if first_seen <= started <= upper:
            out.append(data)
    return out


def _action_llm(
    rec: dict[str, Any], pricing: ModelPricingTable
) -> dict[str, Any]:
    input_tokens = int(rec.get("input_tokens", 0) or 0)
    output_tokens = int(rec.get("output_tokens", 0) or 0)
    cache_write = int(rec.get("cache_creation_input_tokens", 0) or 0)
    cache_read = int(rec.get("cache_read_input_tokens", 0) or 0)
    model = str(rec.get("model", ""))
    cost = pricing.estimate_cost(
        model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_write_tokens=cache_write,
        cache_read_tokens=cache_read,
    )
    return {
        "kind": "llm",
        "model": model,
        "started_at": str(rec.get("timestamp", "")),
        "tokens_in": input_tokens,
        "tokens_out": output_tokens,
        "cache_read_tokens": cache_read,
        "cache_write_tokens": cache_write,
        "duration_ms": int(float(rec.get("duration_seconds", 0.0)) * 1000),
        "cost_usd": round(cost, 6) if cost is not None else 0.0,
    }


def _action_skill(
    skill: dict[str, Any], trace_started_at: str
) -> dict[str, Any]:
    return {
        "kind": "skill",
        "skill": str(skill.get("skill_name", "?")),
        "started_at": trace_started_at,
        "duration_ms": int(float(skill.get("duration_seconds", 0.0)) * 1000),
        "passed": bool(skill.get("passed", False)),
        "blocking": bool(skill.get("blocking", False)),
    }


def _action_subprocess(tc: dict[str, Any]) -> dict[str, Any] | None:
    if tc.get("tool_name") != "Bash":
        return None
    return {
        "kind": "subprocess",
        "command": str(tc.get("input_summary", ""))[:500],
        "started_at": str(tc.get("started_at", "")),
        "duration_ms": int(tc.get("duration_ms", 0) or 0),
        "succeeded": bool(tc.get("succeeded", False)),
    }


def _action_loop(data: dict[str, Any]) -> dict[str, Any]:
    cmd = data.get("command", [])
    cmd_str = " ".join(str(x) for x in cmd) if isinstance(cmd, list) else str(cmd)
    return {
        "kind": "loop",
        "loop": str(data.get("loop", "?")),
        "started_at": str(data.get("started_at", "")),
        "command": cmd_str[:500],
        "duration_ms": int(data.get("duration_ms", 0) or 0),
        "exit_code": int(data.get("exit_code", 0) or 0),
    }


def _phase_for_loop_time(
    started: datetime,
    phase_windows: dict[str, tuple[datetime, datetime]],
) -> str:
    """Return the canonical phase whose window contains `started`; fallback 'implement'."""
    for phase in PHASE_ORDER:
        win = phase_windows.get(phase)
        if win is None:
            continue
        lo, hi = win
        if lo <= started <= hi:
            return phase
    return "implement"


def _empty_phase_rollup(phase: str) -> dict[str, Any]:
    return {
        "phase": phase,
        "tokens_in": 0,
        "tokens_out": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "cost_usd": 0.0,
        "wall_clock_seconds": 0,
        "actions": [],
    }


def build_waterfall(
    config: HydraFlowConfig,
    *,
    issue: int,
    issue_meta: dict[str, Any],
    pricing: ModelPricingTable | None = None,
) -> dict[str, Any]:
    """Build the issue cost waterfall payload (spec §4.11 point 1).

    Args:
        config: HydraFlowConfig (for ``data_root`` / ``data_path``).
        issue: Issue number.
        issue_meta: Pre-fetched issue metadata dict with ``number``,
            ``title``, ``labels``, and optionally ``first_seen`` /
            ``merged_at`` ISO timestamps.
        pricing: Optional pre-loaded pricing table. Tests inject mocks.

    Returns:
        Waterfall payload matching spec §4.11 point 1 shape. Phases
        that produced zero telemetry are listed in ``missing_phases``
        and omitted from ``phases``.
    """
    pricing = pricing or load_pricing()
    first_seen = _parse_iso(issue_meta.get("first_seen"))
    merged_at = _parse_iso(issue_meta.get("merged_at"))

    inferences = _load_inferences_for_issue(config, issue)
    traces = _load_subprocess_traces(config, issue)
    loop_traces = _load_loop_traces_in_window(config, first_seen, merged_at)

    # Group actions by canonical phase.
    per_phase_actions: dict[str, list[dict[str, Any]]] = {p: [] for p in PHASE_ORDER}

    # Phase windows (started_at..ended_at) for loop-trace attribution.
    phase_windows: dict[str, tuple[datetime, datetime]] = {}

    for rec in inferences:
        phase = _phase_for_source(str(rec.get("source", "")))
        if phase not in per_phase_actions:
            per_phase_actions[phase] = []
        per_phase_actions[phase].append(_action_llm(rec, pricing))

    for tr in traces:
        phase = _phase_for_source(str(tr.get("source", tr.get("phase", ""))))
        if phase not in per_phase_actions:
            per_phase_actions[phase] = []
        started = _parse_iso(tr.get("started_at"))
        ended = _parse_iso(tr.get("ended_at")) or started
        if started and ended:
            lo, hi = phase_windows.get(phase, (started, ended))
            phase_windows[phase] = (min(lo, started), max(hi, ended))

        for skill in tr.get("skill_results", []) or []:
            if isinstance(skill, dict):
                per_phase_actions[phase].append(
                    _action_skill(skill, str(tr.get("started_at", "")))
                )
        for tc in tr.get("tool_calls", []) or []:
            if isinstance(tc, dict):
                act = _action_subprocess(tc)
                if act is not None:
                    per_phase_actions[phase].append(act)

    for loop in loop_traces:
        started = _parse_iso(loop.get("started_at"))
        if started is None:
            continue
        phase = _phase_for_loop_time(started, phase_windows)
        per_phase_actions.setdefault(phase, []).append(_action_loop(loop))

    # Build phase rollups in canonical order; flag missing phases.
    phases_out: list[dict[str, Any]] = []
    missing: list[str] = []
    total_in = total_out = total_cache_r = total_cache_w = 0
    total_cost = 0.0

    for phase in PHASE_ORDER:
        actions = per_phase_actions.get(phase, [])
        if not actions:
            missing.append(phase)
            continue
        actions.sort(key=lambda a: (a.get("started_at") or "", a.get("kind", "")))
        rollup = _empty_phase_rollup(phase)
        rollup["actions"] = actions
        for a in actions:
            rollup["tokens_in"] += int(a.get("tokens_in", 0) or 0)
            rollup["tokens_out"] += int(a.get("tokens_out", 0) or 0)
            rollup["cache_read_tokens"] += int(a.get("cache_read_tokens", 0) or 0)
            rollup["cache_write_tokens"] += int(a.get("cache_write_tokens", 0) or 0)
            rollup["cost_usd"] += float(a.get("cost_usd", 0.0) or 0.0)
        win = phase_windows.get(phase)
        if win is not None:
            rollup["wall_clock_seconds"] = max(
                0, int((win[1] - win[0]).total_seconds())
            )
        rollup["cost_usd"] = round(rollup["cost_usd"], 6)
        phases_out.append(rollup)

        total_in += rollup["tokens_in"]
        total_out += rollup["tokens_out"]
        total_cache_r += rollup["cache_read_tokens"]
        total_cache_w += rollup["cache_write_tokens"]
        total_cost += rollup["cost_usd"]

    wall = 0
    if first_seen and merged_at:
        wall = max(0, int((merged_at - first_seen).total_seconds()))

    return {
        "issue": issue,
        "title": str(issue_meta.get("title", "")),
        "labels": list(issue_meta.get("labels", []) or []),
        "total": {
            "tokens_in": total_in,
            "tokens_out": total_out,
            "cache_read_tokens": total_cache_r,
            "cache_write_tokens": total_cache_w,
            "cost_usd": round(total_cost, 6),
            "wall_clock_seconds": wall,
            "first_seen": first_seen.isoformat() if first_seen else None,
            "merged_at": merged_at.isoformat() if merged_at else None,
        },
        "phases": phases_out,
        "missing_phases": missing,
    }
```

- [ ] **Step 4: Run — expect PASS** (every test above).

- [ ] **Step 5: Commit** `feat(diagnostics): waterfall aggregator reads traces + telemetry`

---

## Task 3 — Route wiring in `_diagnostics_routes.py`

**Modify** `src/dashboard_routes/_diagnostics_routes.py`.

- [ ] **Step 1: Write failing integration test** — `tests/test_diagnostics_waterfall_route.py`:

```python
"""Integration test for /api/diagnostics/issue/{issue}/waterfall."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard_routes._diagnostics_routes import build_diagnostics_router


@pytest.fixture
def config(tmp_path: Path) -> MagicMock:
    cfg = MagicMock()
    cfg.data_root = tmp_path
    cfg.data_path = lambda *parts: tmp_path.joinpath(*parts)
    cfg.factory_metrics_path = tmp_path / "diagnostics" / "factory_metrics.jsonl"
    cfg.repo = "o/r"
    return cfg


@pytest.fixture
def client(config, monkeypatch) -> TestClient:
    fetcher = MagicMock()
    fetcher.fetch_issue_by_number = AsyncMock(
        return_value=MagicMock(
            number=1234, title="Test issue", labels=["hydraflow-ready"],
            created_at="2026-04-22T10:00:00+00:00",
        )
    )
    monkeypatch.setattr(
        "dashboard_routes._diagnostics_routes._build_issue_fetcher",
        lambda cfg: fetcher,
    )
    app = FastAPI()
    app.include_router(build_diagnostics_router(config))
    return TestClient(app)


def _write_inference(config, **fields) -> None:
    d = config.data_root / "metrics" / "prompt"
    d.mkdir(parents=True, exist_ok=True)
    with (d / "inferences.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(fields) + "\n")


def _write_trace(config, issue, phase, run_id, idx, payload) -> None:
    d = config.data_root / "traces" / str(issue) / phase / f"run-{run_id}"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"subprocess-{idx}.json").write_text(json.dumps(payload), encoding="utf-8")


def test_waterfall_route_full_issue_returns_all_kinds(client, config) -> None:
    _write_inference(
        config, timestamp="2026-04-22T10:00:00+00:00",
        source="triage", tool="claude", model="claude-sonnet-4-6",
        issue_number=1234, input_tokens=50, output_tokens=20,
        cache_creation_input_tokens=0, cache_read_input_tokens=0,
        duration_seconds=1, status="success",
    )
    _write_inference(
        config, timestamp="2026-04-22T10:05:00+00:00",
        source="implementer", tool="claude", model="claude-sonnet-4-6",
        issue_number=1234, input_tokens=500, output_tokens=200,
        cache_creation_input_tokens=10, cache_read_input_tokens=50,
        duration_seconds=30, status="success",
    )
    _write_trace(
        config, 1234, "implement", 1, 1,
        {
            "issue_number": 1234, "phase": "implement", "source": "implementer",
            "run_id": 1, "subprocess_idx": 1, "backend": "claude",
            "started_at": "2026-04-22T10:05:00+00:00",
            "ended_at": "2026-04-22T10:10:00+00:00",
            "success": True,
            "tokens": {"prompt_tokens": 0, "completion_tokens": 0,
                       "cache_read_tokens": 0, "cache_creation_tokens": 0,
                       "cache_hit_rate": 0.0},
            "tools": {"tool_counts": {"Bash": 1}, "tool_errors": {}, "total_invocations": 1},
            "tool_calls": [
                {"tool_name": "Bash",
                 "started_at": "2026-04-22T10:06:00+00:00",
                 "duration_ms": 900, "input_summary": "pytest",
                 "succeeded": True, "tool_use_id": "t1"},
            ],
            "skill_results": [
                {"skill_name": "diff-sanity", "passed": True, "attempts": 1,
                 "duration_seconds": 2.0, "blocking": True},
            ],
            "inference_count": 0, "turn_count": 0,
        },
    )
    resp = client.get("/api/diagnostics/issue/1234/waterfall")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["issue"] == 1234
    assert payload["title"] == "Test issue"
    assert "hydraflow-ready" in payload["labels"]
    kinds = {a["kind"] for p in payload["phases"] for a in p["actions"]}
    assert {"llm", "skill", "subprocess"}.issubset(kinds)
    assert payload["total"]["tokens_in"] >= 550
    assert payload["total"]["tokens_out"] >= 220


def test_waterfall_route_partial_telemetry_returns_missing_phases(client, config) -> None:
    _write_inference(
        config, timestamp="2026-04-22T10:00:00+00:00",
        source="implementer", tool="claude", model="claude-sonnet-4-6",
        issue_number=1234, input_tokens=1, output_tokens=1,
        cache_creation_input_tokens=0, cache_read_input_tokens=0,
        duration_seconds=1, status="success",
    )
    resp = client.get("/api/diagnostics/issue/1234/waterfall")
    assert resp.status_code == 200
    payload = resp.json()
    assert "missing_phases" in payload
    assert "triage" in payload["missing_phases"]
    assert "merge" in payload["missing_phases"]
    assert {p["phase"] for p in payload["phases"]} == {"implement"}


def test_waterfall_route_ghost_issue_still_returns_200(config, monkeypatch) -> None:
    # Separate client with a fetcher that returns None (deleted/closed issue).
    fetcher = MagicMock()
    fetcher.fetch_issue_by_number = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "dashboard_routes._diagnostics_routes._build_issue_fetcher",
        lambda cfg: fetcher,
    )
    app = FastAPI()
    app.include_router(build_diagnostics_router(config))
    resp = TestClient(app).get("/api/diagnostics/issue/9999/waterfall")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["title"] == "(unknown)"
    assert set(payload["missing_phases"]) == set(
        ("triage", "discover", "shape", "plan", "implement", "review", "merge")
    )
```

- [ ] **Step 2: Run — expect FAIL** (route does not exist; `_build_issue_fetcher` not defined).

- [ ] **Step 3: Patch `src/dashboard_routes/_diagnostics_routes.py`.**

```
Modify: src/dashboard_routes/_diagnostics_routes.py:19-36 — add imports:
    import asyncio
    from dashboard_routes._waterfall_builder import PHASE_ORDER, build_waterfall
```

After the existing `_load_json_file` helper (around line 127), add a fetcher builder.

```
Modify: src/dashboard_routes/_diagnostics_routes.py:127 — insert before build_diagnostics_router:

def _build_issue_fetcher(config: HydraFlowConfig):
    """Construct an IssueFetcher for the waterfall endpoint.

    Split out so tests can monkeypatch a mock in place without standing
    up the full ServiceRegistry. The production path constructs a real
    IssueFetcher with the runtime credentials object.
    """
    # Lazy import — issue_fetcher pulls in async/subprocess machinery we
    # don't want eager-loaded at dashboard import time.
    from credentials import Credentials  # noqa: PLC0415
    from issue_fetcher import IssueFetcher  # noqa: PLC0415

    credentials = Credentials.from_environment()
    return IssueFetcher(config, credentials)


def _issue_meta_from_github_issue(issue_number: int, gh_issue: Any) -> dict[str, Any]:
    """Convert a GitHubIssue model (or None) into the waterfall issue_meta shape."""
    if gh_issue is None:
        return {
            "number": issue_number,
            "title": "(unknown)",
            "labels": [],
            "first_seen": None,
            "merged_at": None,
        }
    return {
        "number": int(getattr(gh_issue, "number", issue_number)),
        "title": str(getattr(gh_issue, "title", "")),
        "labels": [str(lbl) for lbl in (getattr(gh_issue, "labels", []) or [])],
        "first_seen": str(getattr(gh_issue, "created_at", "") or "") or None,
        # merged_at is not on GitHubIssue; when available via issue_outcomes
        # the caller can hydrate it, but for v1 the spec treats None as fine.
        "merged_at": None,
    }
```

Append the route **after** the existing `@router.get("/cache")` handler inside `build_diagnostics_router`, immediately before `return router`:

```
Modify: src/dashboard_routes/_diagnostics_routes.py:237 — insert before `return router`:

    @router.get("/issue/{issue}/waterfall")
    def issue_waterfall(issue: int) -> dict[str, Any]:
        """Return the per-issue cost/phase waterfall (spec §4.11 point 1)."""
        fetcher = _build_issue_fetcher(config)
        try:
            gh_issue = asyncio.run(fetcher.fetch_issue_by_number(issue))
        except Exception:
            logger.warning(
                "waterfall: fetch_issue_by_number failed for #%d", issue,
                exc_info=True,
            )
            gh_issue = None
        issue_meta = _issue_meta_from_github_issue(issue, gh_issue)
        return build_waterfall(config, issue=issue, issue_meta=issue_meta)
```

- [ ] **Step 4: Run — expect PASS.**

- [ ] **Step 5: Commit** `feat(diagnostics): /api/diagnostics/issue/{issue}/waterfall route (§4.11 point 1)`

---

## Task 4 — Quality gate + PR

- [ ] **Step 1: Full quality sweep.**

```bash
PYTHONPATH=src uv run pytest tests/test_trace_collector_loop_helper.py tests/test_waterfall_builder.py tests/test_diagnostics_waterfall_route.py -v
make quality
```

Fix anything `ruff`, `mypy`, or `pytest` surfaces; **never** `--no-verify`.

- [ ] **Step 2: Push + PR.** Title `feat(diagnostics): cost waterfall helper + issue endpoint (§4.11 1+3)`. Body:

```
## Summary
- `trace_collector.emit_loop_subprocess_trace` — free function every trust-fleet loop already lazy-imports; writes `{kind: "loop", ...}` trace files under `<data_root>/traces/_loops/<slug>/`.
- `/api/diagnostics/issue/{issue}/waterfall` — per-issue cost/phase rollup reading existing subprocess traces + prompt telemetry; cost computed on the fly via `ModelPricing.estimate_cost` so pricing-sheet updates retroactively re-price history.
- Unblocks the telemetry tasks in Plans 1–5 (principles-audit, rc-budget, wiki-rot, trust-fleet-sanity, flake-tracker, skill-prompt-eval, fake-coverage-auditor, corpus-learning, contract-refresh, staging-bisect) — their `try/except ImportError` fallbacks now resolve.

## Test plan
- [ ] `PYTHONPATH=src uv run pytest tests/test_trace_collector_loop_helper.py -v`
- [ ] `PYTHONPATH=src uv run pytest tests/test_waterfall_builder.py -v`
- [ ] `PYTHONPATH=src uv run pytest tests/test_diagnostics_waterfall_route.py -v`
- [ ] `make quality`

## Out of scope (follow-up Plan 6b-2)
- §4.11 point 2: Diagnostics UI Waterfall sub-tab.
- §4.11 point 4: Aggregate rollups (`/cost/rolling-24h`, `/cost/top-issues`, `/cost/by-loop`).
- §4.11 point 5: Per-loop cost dashboard + `/api/diagnostics/loops/cost` endpoint.
- §4.11 point 6: Cost budget alerts (`daily_cost_budget_usd`, `issue_cost_alert_usd`).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

Return the PR URL.

---

## Test plan

- [ ] `PYTHONPATH=src uv run pytest tests/test_trace_collector_loop_helper.py -v`
- [ ] `PYTHONPATH=src uv run pytest tests/test_waterfall_builder.py -v`
- [ ] `PYTHONPATH=src uv run pytest tests/test_diagnostics_waterfall_route.py -v`
- [ ] `make quality`

---

## Appendix — quick reference

| Decision | Value | Source |
|---|---|---|
| Helper pattern | Free function (no singleton) | `src/trace_collector.py` has no singleton; `TraceCollector` is per-subprocess |
| Loop trace layout | `<data_root>/traces/_loops/<slug>/run-<iso>.json` | This plan §2 |
| Stderr truncation | Tail-preserving, 2048-char cap | This plan §3 |
| Phase set | `triage → discover → shape → plan → implement → review → merge` | Spec §4.11 point 1 shape |
| Off-pipeline fold | `hitl → review`, `find → triage` | `src/tracing_context.py` mapping |
| Cost re-pricing | On-the-fly via `ModelPricing.estimate_cost` | Spec §4.11 point 1 rationale |
| LLM action source | `prompt_telemetry.inferences.jsonl` filtered by `issue_number` | `src/prompt_telemetry.py` |
| Skill action source | `SubprocessTrace.skill_results` | `src/models.py:1557` |
| Subprocess action source | `SubprocessTrace.tool_calls` where `tool_name == "Bash"` | `src/models.py:1556` |
| Loop action source | `<data_root>/traces/_loops/**/run-*.json` within issue window | This plan §10 |
| Missing-phase policy | Omit from `phases`, list in `missing_phases` | This plan §9 |
| Ghost-issue policy | Still 200; title `"(unknown)"`, labels `[]` | This plan §8 |
| Active-config wiring | `trace_collector.set_active_config(config)` in orchestrator startup | This plan Task 1 Step 4 |
| Action ordering | `(started_at, kind)` tuple, ascending | This plan §6 |
