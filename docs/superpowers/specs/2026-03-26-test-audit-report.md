# Full Test Suite Audit Report

**Date:** 2026-03-26
**Scope:** 213 test files, ~133K lines, 8,411 tests
**Reviewers:** 6 parallel audit agents covering all domains

---

# Executive Summary

The HydraFlow test suite is **solid at the unit level** with good factory infrastructure (`TaskFactory`, `PRInfoFactory`, `ConfigFactory`, etc.) and strong coverage (93%). The best files — `test_triage.py`, `test_docker_runner.py`, `test_issue_store.py`, `test_state_machine.py` — demonstrate excellent single-responsibility tests with clear AAA structure.

**Main strengths:**
- Excellent factory/builder infrastructure across `conftest.py` and `helpers.py`
- Real-git E2E tests in `test_agent_lifecycle.py` for high-confidence verification
- Strong edge-case coverage in triage, scaffold, and state machine tests
- Good use of `supply_once` for async polling simulation

**Main weaknesses:**
- Massive mock setup duplication in review phase and PR manager tests (~150 lines of identical setup across 18+ tests)
- Missing parameterization opportunities (80+ tests in config validation alone)
- Mixed factory ecosystems (3 independent factory stacks in different files)
- Weak string-contains assertions where structured parsing is available
- Many tests assert mock call counts instead of observable behavioral outcomes

**Overall confidence:** High for unit behavior, medium for integration paths. The suite catches regressions reliably but has significant maintainability drag.

---

# Recurring Patterns

## P1 — Duplicated Inline Mock Setup (Critical)
**Files:** test_review_phase_core, test_review_phase_hitl, test_agent_output, test_post_merge_handler, test_pr_manager_core, test_manifest_issue_syncer
**Impact:** ~150 lines of identical 6-9 mock AsyncMock assignments repeated across 30+ tests
**Fix:** Extract `_setup_conflict_scenario()`, `_make_prs_mock()`, and class-level fixtures

## P2 — Missing Parameterization (High)
**Files:** test_config_validation (80 tests), test_reviewer (12 sanitize tests), test_memory (15 type-parse tests), test_adr_pre_validator (7 section tests), test_ci_scaffold (3 identical language tests)
**Impact:** ~200 tests that could be collapsed to ~40 parameterized tests
**Fix:** `@pytest.mark.parametrize` with data tables

## P3 — Mock-Call Assertions Instead of Behavioral Assertions (High)
**Files:** test_review_phase_core, test_plan_phase, test_hitl_phase, test_orchestrator_core
**Impact:** Tests verify mocks were called but not what was produced. A refactoring that maintains behavior but changes call patterns breaks tests unnecessarily.
**Fix:** Assert on result objects, state changes, and event data — use mock assertions as secondary confirmation only

## P4 — `call_count` Counter-Based Subprocess Dispatch (Medium)
**Files:** test_workspace_create, test_workspace_git, test_beads_manager, test_report_issue_loop
**Impact:** Tests dispatch mock responses by call position, not command identity. Adding a git command shifts all subsequent responses.
**Fix:** Dispatch on `args` content: `if args[:3] == ("git", "fetch", "origin"): return success_proc`

## P5 — Duplicate Factory Infrastructure (Medium)
**Files:** test_metrics_manager has its own `make_config`/`make_manager`; test_manifest_issue_syncer rebuilds PRManager mocks; test_issue_fetcher ignores `make_proc`
**Impact:** Config field changes require updates in 3+ places
**Fix:** Consolidate to `ConfigFactory` and `make_proc` from `helpers.py`

## P6 — Wide Tuple Returns from Factory Functions (Medium)
**Files:** test_pr_unsticker (9-element tuple), test_epic (5-element), test_report_issue_loop (4-element)
**Impact:** Every destructuring breaks when tuple grows; `_` discards hide what tests need
**Fix:** Return `SimpleNamespace` or `dataclass` instead of tuples

## P7 — Redundant `sys.path.insert` (Low)
**Files:** 8+ test files duplicate what conftest.py already does
**Fix:** Delete per-file inserts

## P8 — Inline `import json` in Test Bodies (Low)
**Files:** test_dashboard_routes_state (64 occurrences), test_pr_manager_queries (6)
**Fix:** Move to file-level imports

---

# BEADS Issues (All Domains)

## Critical Priority (P0)

### BEADS-1: Review phase mock duplication
**Scope:** test_review_phase_core.py, test_review_phase_hitl.py
**Lines:** 135-156, 247-291, 309-321 (core); 56-63, 92-99, 142-149, 177-183 (hitl)
Same 6-9 AsyncMock assignments appear in 11+ tests across two files. This is the single most impactful maintainability problem.
**Fix:** Extract `_setup_conflict_scenario(phase, config)` helper.

### BEADS-2: Config validation needs parameterization
**Scope:** test_config_validation.py (entire file)
~80 tests following identical 4-step pattern for ~15 integer fields. None use parametrize.
**Fix:** Single parametrized class with `(field, min, max, default)` table.

### BEADS-3: Config defaults test collapse
**Scope:** test_config_core.py lines 309-664
`TestHydraFlowConfigDefaults` (25+ tests) each construct a full config to assert one pre-known default. Tests Pydantic's constructor, not application logic.
**Fix:** Replace with introspection-based parametrized test reading from `model_fields`.

---

## High Priority (P1)

### BEADS-4: Event publishing scaffold repeated 7x
**File:** test_agent_output.py lines 606-831
7 event tests each independently set up 4 mock patches + event queue drain.
**Fix:** Extract `setup_method` + `_run_agent_and_collect_events()` helper.

### BEADS-5: _sanitize_summary parameterization
**File:** test_reviewer.py lines 302-358
12 rejection cases + 1 acceptance as 13 individual functions.
**Fix:** Two `@pytest.mark.parametrize` blocks.

### BEADS-6: PR manager ConfigFactory duplication
**Files:** test_pr_manager_core.py, test_pr_manager_queries.py
30+ tests repeat identical 3-line `ConfigFactory.create()` instead of using the `config` fixture.
**Fix:** Use `config` fixture; extract `mgr` fixture.

### BEADS-7: PR unsticker 9-element tuple
**File:** test_pr_unsticker.py
Every test destructures `unsticker, state, prs, agents, wt, fetcher, bus, _, resolver = _make_unsticker(...)`.
**Fix:** Return `UnstickerHarness` dataclass.

### BEADS-8: Post-merge handler setup duplication
**File:** test_post_merge_handler.py
`handle_approved` boilerplate (8-10 lines) repeated in 12+ tests.
**Fix:** Extract fixture with pre-wired happy path.

### BEADS-9: State tracking round-trip multi-concern
**File:** test_state_tracking.py line 155
`test_round_trip_preserves_data` calls 4 unrelated mutations and asserts all 4. Failure pinpoints nothing.
**Fix:** Split into 4 isolated tests.

### BEADS-10: Token-presence subprocess assertions
**File:** test_pr_manager_core.py lines 117-125, 187-191, 256-261
Assertions like `assert "42" in cmd` pass for wrong commands.
**Fix:** Assert `cmd[:4] == ("gh", "issue", "comment", "42")`.

### BEADS-11: Prompt telemetry mega-test
**File:** test_prompt_telemetry.py lines 36-93
60-line test with 15+ assertions tests entire `record()` output contract.
**Fix:** Split into 5 focused tests; add shared `telemetry` fixture.

### BEADS-12: Issue fetcher ignores make_proc
**File:** test_issue_fetcher.py
8+ tests manually construct mock procs when `helpers.make_proc` exists.
**Fix:** Replace with `make_proc()`.

### BEADS-13: Metrics manager duplicate factory
**File:** test_metrics_manager.py lines 26-60
`make_config`/`make_manager` duplicates `ConfigFactory`.
**Fix:** Migrate to `ConfigFactory.create()`.

### BEADS-14: Memory type parse parameterization
**File:** test_memory.py lines 122-242
15 nearly identical tests across 2 classes.
**Fix:** Two `@pytest.mark.parametrize` blocks.

### BEADS-15: ADR pre-validator fixture
**File:** test_adr_pre_validator.py
`ADRPreValidator()` instantiated in 30+ test bodies. Stateless — needs class fixture.
**Fix:** `@pytest.fixture` returning `ADRPreValidator()`.

### BEADS-16: Manifest issue syncer mock duplication
**File:** test_manifest_issue_syncer.py
6 tests copy-paste identical PRManager mock wiring.
**Fix:** Extract `_make_prs_mock()` factory.

### BEADS-17: Prep label dispatch boilerplate
**File:** test_prep.py
6 tests define identical inline async `side_effect` closures.
**Fix:** Extend `SubprocessMockBuilder` with `.with_label_list_and_creates()`.

---

## Medium Priority (P2)

### BEADS-18: Dashboard HITL tests split across two files
**Files:** test_dashboard_websocket.py (8 HITL classes), test_dashboard_routes_hitl.py
**Fix:** Consolidate into single file.

### BEADS-19: Dashboard state file noise
**File:** test_dashboard_routes_state.py
29 duplicate section banners + 64 inline `import json`.
**Fix:** Delete banners, move imports to file level.

### BEADS-20: Private attribute assertions in service registry
**File:** test_service_registry.py lines 39-79
`assert registry.worktrees._config is config` and `type()` comparison on runner.
**Fix:** Assert on public API or `isinstance`.

### BEADS-21: Orchestrator init wiring tests
**File:** test_orchestrator_core.py lines 33-112
12 tests each assert `isinstance` + `._config is config`. Pure wiring verification.
**Fix:** Collapse into parametrized table.

### BEADS-22: Report issue loop Pydantic bypass
**File:** test_report_issue_loop.py line 35
`object.__setattr__(deps.config, "dry_run", True)` bypasses Pydantic.
**Fix:** Use `ConfigFactory.create(dry_run=True)`.

### BEADS-23: call_count dispatch in workspace tests
**Files:** test_workspace_create.py, test_workspace_git.py (10+ tests)
**Fix:** Dispatch on arg content, not position.

### BEADS-24: Beads manager call_count + positional arg assertions
**File:** test_beads_manager.py
Sequential `call_count` closures and `args[4]` index assertions.
**Fix:** Use `side_effect` lists and named argument matching.

### BEADS-25: Smoke suite size magic number
**Files:** test_test_scaffold.py, test_polyglot_prep.py, test_ci_scaffold.py
`== 8` appears in 5+ tests.
**Fix:** Define `SMOKE_SUITE_SIZE = 8` in helpers.

---

# Prioritized Fix Plan

| Priority | BEADS | Effort | Impact |
|----------|-------|--------|--------|
| 1 | BEADS-1 (review phase mocks) | Medium | Highest — 11 tests, 2 files |
| 2 | BEADS-2 (config validation parametrize) | Large | 80 tests → ~20 |
| 3 | BEADS-4 (event publishing scaffold) | Small | 7 tests cleaned up |
| 4 | BEADS-5 (sanitize_summary parametrize) | Small | 13 → 2 tests |
| 5 | BEADS-6 (PR manager fixtures) | Medium | 30+ tests |
| 6 | BEADS-11 (prompt telemetry split) | Small | 1 mega-test → 5 |
| 7 | BEADS-14 (memory type parametrize) | Small | 15 → 2 tests |
| 8 | BEADS-7 (unsticker dataclass) | Small | Better ergonomics |
| 9 | BEADS-12+13 (factory consolidation) | Medium | Eliminate drift |
| 10 | BEADS-18+19 (dashboard cleanup) | Medium | File organization |

---

# Score Summary by Domain

| Domain | Avg Quality | Avg Assertions | Avg AAA | Avg Data | Strongest File |
|--------|-------------|---------------|---------|----------|----------------|
| Phases + Runners | 3.8 | 3.9 | 3.1 | 3.8 | test_triage.py (5/5/5/4) |
| PR + Git | 3.6 | 3.6 | 3.4 | 3.4 | test_workspace_docker.py (4/4/4/4) |
| Config + Models | 3.6 | 3.5 | 3.4 | 3.3 | test_state_machine.py (5/5/4/4) |
| Dashboard + API | 3.2 | 3.5 | 3.0 | 3.2 | test_server.py (4/3/4/4) |
| ADR + Memory + Prep | 3.8 | 3.3 | 3.3 | 3.5 | test_lint_scaffold.py (4/4/4/4) |
| Remaining | 3.6 | 3.4 | 3.1 | 3.3 | test_docker_runner.py (5/4/4/5) |
| **Overall** | **3.6** | **3.5** | **3.2** | **3.4** | |
