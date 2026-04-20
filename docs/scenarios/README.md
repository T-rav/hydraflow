# Scenario Testing Framework

Release-gating scenario tests that prove the full pipeline and background loops work before shipping.

## Architecture

Two layers: a **MockWorld** fixture that composes all external fakes into a controllable environment, and **scenario test files** grouped by happy/sad/edge/loop paths.

### MockWorld

A single test fixture that wires up every external service as a stateful fake, builds on top of `PipelineHarness`, and exposes a fluent API for seeding state and running the pipeline.

```
tests/scenarios/
  conftest.py              # MockWorld fixture
  fakes/
    mock_world.py          # MockWorld — composes all fakes
    fake_github.py         # Issues, PRs, labels, CI status, comments
    fake_llm.py            # Scripted triage/plan/implement/review results
    fake_hindsight.py      # Memory bank retain/recall with fail mode
    fake_workspace.py      # Worktree lifecycle tracking
    fake_sentry.py         # Breadcrumb/event capture
    fake_clock.py          # Deterministic time control
    scenario_result.py     # IssueOutcome + ScenarioResult dataclasses
  test_happy.py            # Happy path scenarios (mark: scenario)
  test_sad.py              # Failure + recovery scenarios (mark: scenario)
  test_edge.py             # Race conditions, mid-flight mutations (mark: scenario)
  test_loops.py            # Background loop scenarios (mark: scenario_loops)
```

### Stateful Fakes

Each fake is a real Python class with in-memory state (not `AsyncMock`). Assertions inspect the world's final state directly (e.g. `world.github.issue(1).labels`) rather than checking mock call counts.

| Fake | Replaces | State It Tracks |
|------|----------|----------------|
| `FakeGitHub` | `PRManager`, `IssueFetcher` | Issues, PRs, labels, CI, comments |
| `FakeLLM` | All 4 runners | Per-phase, per-issue scripted results (supports retry sequences) |
| `FakeHindsight` | `HindsightClient` | Per-bank memory entries, fail mode |
| `FakeWorkspace` | `WorkspaceManager` | Created/destroyed worktrees |
| `FakeSentry` | `sentry_sdk` | Breadcrumbs and events |
| `FakeClock` | `time.time` | Controllable time for TTL/staleness |

### MockWorld API

```python
# Seed the world (fluent, returns self)
world.add_issue(number, title, body, labels=...)
world.set_phase_result(phase, issue, result)
world.set_phase_results(phase, issue, [result1, result2])  # retry sequences
world.on_phase(phase, callback)                            # mid-flight hooks
world.fail_service(name)
world.heal_service(name)

# Run
result = await world.run_pipeline()              # pipeline phases
stats  = await world.run_with_loops(["ci_monitor"], cycles=1)  # background loops

# Inspect
world.github.issue(1).labels
world.github.pr_for_issue(1).merged
world.hindsight.bank_entries("learnings")
```

## Running

```bash
make scenario          # pipeline scenarios (pytest -m scenario)
make scenario-loops    # background loop scenarios (pytest -m scenario_loops)
make quality           # includes both in the quality gate
```

## Scenario Matrix

### Happy Paths (`test_happy.py`)

| # | Scenario | Asserts |
|---|----------|---------|
| H1 | Single issue end-to-end | find -> triage -> plan -> implement -> review -> done, PR merged |
| H2 | Multi-issue concurrent batch (3 issues) | All complete independently, no cross-contamination |
| H3 | HITL round-trip | Issue escalates to HITL, correction submitted, resumes |
| H4 | Review approve + merge | APPROVE verdict, CI passes, PR merged, cleanup runs |
| H5 | Plan produces sub-issues | Planner returns `new_issues`, sub-issues created |

### Sad Paths (`test_sad.py`)

| # | Scenario | Asserts |
|---|----------|---------|
| S1 | Plan fails then succeeds on retry | First plan `success=False`, retry succeeds |
| S2 | Implement exhausts attempts | Docker fails N times, issue does not complete |
| S3 | Review rejects -> route-back | REQUEST_CHANGES, routes back, re-review approves |
| S4 | GitHub API 5xx during PR creation | `fail_service("github")` mid-implement, recovery on heal |
| S5 | Hindsight down -> pipeline continues | Memory calls fail, pipeline completes without writes |
| S6 | CI fails -> auto-fix -> CI passes | `wait_for_ci` returns failure first, then passes |

### Edge Cases (`test_edge.py`)

| # | Scenario | Asserts |
|---|----------|---------|
| E1 | Duplicate issues (same title/body) | Both tracked by number, no crash |
| E2 | Issue relabeled mid-flight | `on_phase` hook fires, pipeline continues |
| E3 | Stale worktree during active processing | GC skips actively-processing issues |
| E4 | Epic with child ordering | Parent waits for children, dependency order |
| E5 | Zero-diff implement (already satisfied) | Agent produces 0 commits, `success=True` |

### Background Loop Scenarios (`test_loops.py`)

| # | Loop | Scenario | Asserts |
|---|------|----------|---------|
| L1 | HealthMonitor | Low first_pass_rate triggers config bump | `max_quality_fix_attempts` increased, decision audit written |
| L2 | WorkspaceGC | Cleans stale worktrees | Closed-issue worktrees destroyed, active preserved |
| L3 | StaleIssueGC | Closes inactive HITL issues | Old HITL issues auto-closed with comment, fresh untouched |
| L4 | PRUnsticker | Processes HITL items with open PRs | Unstick attempted on qualifying items |
| L5 | CIMonitor | CI failure creates issue | GitHub issue created with `hydraflow-ci-failure` label |
| L6 | CIMonitor | CI recovery closes issue | Failure issue auto-closed on green CI |
| L7 | DependabotMerge | Auto-merges bot PR on CI pass | PR approved, merged, processed set updated |
| L8 | DependabotMerge | Skips bot PR on CI failure | PR not merged, skip recorded |

## Relationship to Existing Tests

- **Unit tests (9K+):** Unchanged. Test individual functions/methods.
- **Integration tests (`PipelineHarness`):** Unchanged. Test phase wiring with mocked runners.
- **Scenario tests (this):** Test complete flows with stateful fakes. Additive, not replacing.

## ADR Reference

- [ADR-0022](../adr/0022-integration-test-architecture-cross-phase.md) — PipelineHarness pattern (foundation MockWorld builds on)

## Future: v2 Observability-Driven Scenarios

Auto-generation from production run traces:
1. Production run recorder captures external interactions
2. Trace-to-scenario converter builds MockWorld seed + assertions
3. Self-improvement loop adds scenarios when production diverges

Out of scope for v1. MockWorld API is designed to support it.

---

## Conventions (Tier 1 / 2 / 3 Helpers)

### Test Helpers

- **`init_test_worktree(path, *, branch="agent/issue-1", origin=None)`** — Helper at `tests/scenarios/helpers/git_worktree_fixture.py`. Initializes a git repo with a bare origin, main branch, and feature branch. Use for any realistic-agent scenario that runs `_count_commits`. Pass `origin=...` when multiple worktrees share a parent directory.

- **`seed_ports(world, **ports)`** — Helper at `tests/scenarios/helpers/loop_port_seeding.py`. Pre-seeds `world._loop_ports` with `AsyncMock` variants before `run_with_loops` runs the catalog builder. Use when a caretaker-loop scenario needs to observe calls on an inner delegate.

### MockWorld Constructor Flags

- **`MockWorld(use_real_agent_runner=True)`** — Opt-in flag that replaces the scripted `FakeLLM.agents` with a real production `AgentRunner` wired to `FakeDocker` via `FakeSubprocessRunner`. Default `False` preserves scripted-mode behavior.

- **`MockWorld(wiki_store=..., beads_manager=...)`** — Thread `RepoWikiStore` and `FakeBeads` into `PlanPhase`/`ImplementPhase`.

### MockWorld Methods

- **`MockWorld.fail_service("docker" | "github" | "hindsight")`** — Arms fault injection on the corresponding fake. Mirrored `heal_service(...)` clears.

### FakeDocker Scripting

- **`FakeDocker.script_run_with_commits(events, commits, cwd)`** — Script agent run events plus one commit to the worktree repo at `cwd`.

- **`FakeDocker.script_run_with_multiple_commits(events, commit_batches, cwd)`** — Script agent run events plus N separate commits, respectively. Use when the scenario must verify multi-commit push behavior.

### FakeGitHub Fault Injection

- **`FakeGitHub.add_alerts(*, branch, alerts)`** — Script code-scanning alerts for a branch. Keys by branch string to match `PRPort.fetch_code_scanning_alerts(branch)`.

### FakeWorkspace Fault Injection

- **`FakeWorkspace.fail_next_create(kind)`** — Single-shot fault: `permission | disk_full | branch_conflict`. The workspace raises on the next `create()` call then resets, so subsequent calls succeed.

---

## Scenario Catalog (Extended)

### Realistic-Agent Scenarios (`test_agent_realistic.py`)

| ID | Test | What it covers |
|----|------|----------------|
| A0 | `test_A0_happy_path_realistic_agent` | Base happy path: one issue, real AgentRunner, FakeDocker commits, merges. |
| A1 | `test_A1_docker_timeout_fails_issue_no_retry` | Docker timeout — production does NOT retry; issue fails with `worker_result.success=False`. |
| A2 | `test_A2_oom_fails_issue` | OOM (exit_code=137) causes agent failure; zero commits → `_verify_result` fails. |
| A3 | `test_A3_malformed_stream_recovers_to_failure` | Garbage stream events plus exit_code=1 — StreamParser skips unknowns, result is failure. |
| A4 | `test_A4_unknown_event_type_ignored_stream_continues` | `auth_retry_required` event silently skipped; trailing `result:success` still merges issue. |
| A5 | `test_A5_token_budget_exceeded_halts_implement` | Stream-level `budget_exceeded` event plus failure result → issue fails without merge. |
| A6 | `test_A6_github_rate_limit_at_triage_halts_pipeline` | Rate-limit armed before triage (remaining=0) — first GitHub call raises, pool absorbs, no PR created. |
| A7 | `test_A7_github_secondary_rate_limit_surfaces` | Secondary (abuse-detection) rate-limit is also absorbed; issue never progresses. |
| A8 | `test_A8_find_stage_to_done_realistic_agent` | Full pipeline from `hydraflow-find` through triage→plan→implement→review; issue merges. |
| A9 | `test_A9_hindsight_failure_realistic_agent_still_succeeds` | `fail_service('hindsight')` during realistic-agent run does not halt pipeline; issue merges. |
| A10 | `test_A10_quality_fix_loop_retries_then_passes` | `make quality` fails on first attempt; quality-fix agent commits fix; second quality run passes; merges. |
| A11 | `test_A11_review_fix_ci_loop_resolves` | CI fails after PR creation; `fix_ci` loop resolves it; CI passes; merge proceeds. |
| A12 | `test_A12_multi_commit_implement` | Real agent produces 3 commits; `git rev-list --count` confirms all three on branch. |
| A13 | `test_A13_zero_diff_fails_without_merge` | Agent claims success but writes no commits; `_verify_result` fails on commit count; no merge. |
| A14 | `test_A14_three_issues_concurrent_realistic` | Three issues processed concurrently via real AgentRunner; all merge; worktree isolation verified. |
| A15 | `test_A15_epic_decomposition_creates_children` | High-complexity issue decomposed via EpicManager stub; two child issues created in FakeGitHub. |
| A16 | `test_A16_credit_exhausted_halts_pipeline` | `CreditExhaustedError` from `_execute` propagates out of `run_pipeline` (re-raise allowlist). |
| A17 | `test_A17_authentication_error_halts_pipeline` | `AuthenticationError` from `_execute` propagates out of `run_pipeline` (re-raise allowlist). |
| A18 | `test_A18_rate_limit_heals_mid_pipeline` | Rate-limit armed with remaining=5; `on_phase("implement")` heals before it matters; merges. |
| A19 | `test_A19_code_scanning_alerts_reach_reviewer` | `add_alerts(branch=...)` seeds alerts; ReviewPhase fetches by branch; reviewer receives them unchanged. |
| A20 | `test_A20_workspace_create_permission_failure` | `PermissionError` from workspace creation is swallowed; issue does not merge; run_pipeline returns normally. |
| A20b | `test_A20b_workspace_create_disk_full` | `OSError(ENOSPC)` from FakeWorkspace is swallowed gracefully; issue does not merge. |
| A20c | `test_A20c_workspace_create_branch_conflict` | `RuntimeError` ("worktree already exists") from FakeWorkspace is swallowed; issue does not merge. |
| A21 | `test_A21_state_json_corruption_graceful_fallback` | Corrupt state.json before run; `StateTracker.load` falls back to empty `StateData()`; pipeline continues. |
| A22 | `test_A22_wiki_populated_plan_consults_it` | Pre-populated `RepoWikiStore` wired to `PlanPhase`; wiki accessible; pipeline completes without crash. |

**Boot smoke** (`test_realistic_agent_boot_smoke.py`): `test_real_agent_runner_single_event_smoke` — single invocation with tool_use + message + result events; proves the AgentRunner wiring stack boots.

### Bead Workflow Scenarios (`test_bead_workflow.py`)

| ID | Test | What it covers |
|----|------|----------------|
| B1 | `test_B1_bead_workflow_end_to_end` | Plan with Task Graph headers creates 2 beads; implement calls `init`; tasks stay open (claim/close are agent-subprocess concerns). |
| B1b | `test_B1_no_beads_without_task_graph_headers` | Plan text without `### P{N}` headers → `extract_phases` returns []; no beads created; `_initialized` stays False. |

### Background Loop Scenarios (`test_loops.py` + `test_caretaker_loops.py` + `test_caretaker_loops_part2.py`)

#### L1–L8 (`test_loops.py`)

| # | Loop | Scenario | Asserts |
|---|------|----------|---------|
| L1 | HealthMonitor | Low first_pass_rate triggers config bump | `max_quality_fix_attempts` increased, decision audit written |
| L2 | WorkspaceGC | Cleans stale worktrees | Closed-issue worktrees destroyed, active preserved |
| L3 | StaleIssueGC | Closes inactive HITL issues | Old HITL issues auto-closed with comment, fresh untouched |
| L4 | PRUnsticker | Processes HITL items with open PRs | Unstick attempted on qualifying items |
| L5 | CIMonitor | CI failure creates issue | GitHub issue created with `hydraflow-ci-failure` label |
| L6 | CIMonitor | CI recovery closes issue | Failure issue auto-closed on green CI |
| L7 | DependabotMerge | Auto-merges bot PR on CI pass | PR approved, merged, processed set updated |
| L8 | DependabotMerge | Skips bot PR on CI failure | PR not merged, skip recorded |

#### L9–L13 (`test_caretaker_loops.py`)

| ID | Class | What it covers |
|----|-------|----------------|
| L9 | `TestL9ADRReviewerLoop` | `ADRReviewerLoop._do_work` delegates to `adr_reviewer.review_proposed_adrs`; stats pass through; None passthrough preserved. |
| L10 | `TestL10MemorySyncLoop` | `MemorySyncLoop._do_work` calls `sync()` then `publish_sync_event(result)`; returned stats are a fresh copy. |
| L11 | `TestL11RetrospectiveLoop` | `RetrospectiveLoop` drains queue; empty queue → zero stats; `RETRO_PATTERNS` item → processed=1, acknowledged. |
| L12 | `TestL12EpicSweeperLoop` | `EpicSweeperLoop` sweeps open epics; no epics → zero counts; epic with all closed sub-issues auto-closed. |
| L13 | `TestL13SecurityPatchLoop` | `SecurityPatchLoop` files issues from Dependabot alerts; no alerts → filed=0; high-severity fixable → filed=1; dry_run → None. |

#### L14–L23 (`test_caretaker_loops_part2.py`)

| ID | Class | What it covers |
|----|-------|----------------|
| L14 | `TestL14CodeGrooming` | `CodeGroomingLoop`: disabled → `{"skipped": "disabled"}`; dry_run → None; enabled with no findings → stats shape with `"filed"` key. |
| L15 | `TestL15DiagnosticLoop` | `DiagnosticLoop` polls `hydraflow-diagnose` issues; no issues → zero counts; issue without escalation context → escalated=1. |
| L16 | `TestL16EpicMonitorLoop` | `EpicMonitorLoop` delegates to `EpicManager`; no stale epics → stale_count=0; 3 stale + 5 tracked → stats match. |
| L17 | `TestL17GitHubCacheLoop` | `GitHubCacheLoop` calls `cache.poll()` and forwards its stats; empty dict result → None (falsy guard). |
| L18 | `TestL18RepoWikiLoop` | `RepoWikiLoop` lints per-repo wikis; no repos → zero stats; one repo → `active_lint` called, stale_entries reflected. |
| L19 | `TestL19ReportIssueLoop` | `ReportIssueLoop` processes queued bug reports; dry_run → None; empty queue → None. |
| L20 | `TestL20RunsGCLoop` | `RunsGCLoop` purges expired/oversized runs; no artifacts → zero purge; 3 expired + 1 oversized → stats match. |
| L21 | `TestL21SentryLoop` | `SentryLoop` skips gracefully without credentials; empty org or empty token → `skipped=True` with reason. |
| L22 | `TestL22StagingPromotionLoop` | `StagingPromotionLoop`: disabled → `status=staging_disabled`; cadence not elapsed → `status=cadence_not_elapsed`; elapsed → RC branch cut, promotion PR opened. |
| L23 | `TestL23StaleIssueLoop` | `StaleIssueLoop` auto-closes stale issues; no issues → zero; fresh issue → scanned but not closed; stale + dry_run → closed=1, no API call; fetch failure → zero stats. |

---

## Caretaker-Loop Authoring Patterns

### Pattern A — Catalog-Driven (preferred)

Use `await world.run_with_loops(["loop_name"], cycles=1)`. Works when the loop is registered in `tests/scenarios/catalog/loop_registrations.py`. Minimal boilerplate.

```python
stats = await world.run_with_loops(["ci_monitor"], cycles=1)
assert stats["ci_monitor"]["cycles_completed"] == 1
```

### Pattern B — Direct Instantiation

Use `_make_loop_deps` from `tests/helpers.py` and construct the loop class directly. Required when:
- Config flags differ from catalog defaults, or
- The loop is not yet registered in the catalog (e.g. `staging_promotion_loop` as of this writing).

```python
from tests.helpers import _make_loop_deps
from src.loops.staging_promotion import StagingPromotionLoop

deps = _make_loop_deps(world, config_overrides={"staging_branch": "staging"})
loop = StagingPromotionLoop(**deps)
await loop.run_once()
```

Pattern A is simpler; use Pattern B only when Pattern A cannot accommodate the scenario.
