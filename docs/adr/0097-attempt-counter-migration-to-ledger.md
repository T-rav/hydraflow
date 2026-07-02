# ADR-0097: Attempt counter migration into the ledger (Phase 2c)

- **Status:** Accepted
- **Date:** 2026-07-01
- **Refines:** ADR-0094 (two-level convergence: Gate + ConvergenceLedger)
- **Extends:** ADR-0096 (boundary verdict recording)
- **Enforcement:** enforced
- **Enforced by:** pytest:tests/scenarios/test_convergence_counter_migration_mockworld.py

> **Superseded in part by [ADR-0101](0101-convergence-gate-general-availability.md):** the `convergence_gate_enabled` flag has been removed; the convergence gate is now the sole, always-on review path and the legacy ungated fallback is deleted. The flag-gated / dark-ship framing below is historical.

## Context

ADR-0094 introduced the `ConvergenceLedger` as the single source of truth for per-issue convergence state. Phase 1 migrated `review_attempts` and `review_blast_radii` from bespoke `StateData` fields into the ledger. Phase 2b (ADR-0096) added cross-boundary verdict recording into `StageRecord.last_verdict`.

Three per-issue attempt counters remained in bespoke storage after Phase 1:

- `StateData.auto_agent_attempts` (a dict keyed by issue number, incremented each time the AutoAgent runner is invoked for an issue)
- `StateData.sandbox_failure_fixer_attempts` (a dict keyed by PR number, tracking sandbox-fix tries per PR)
- A per-issue quality-fix count written into `WorkerResultMeta` and read by `retrospective.py`

This split state means the ledger did not hold a complete picture of retry activity, and changes to one counter required reasoning about two storage locations. Phase 2c closes that gap by migrating all three into `ConvergenceLedger.stage_state[<stage>].attempts`.

## Decision

### Move-not-copy, no dual-write

All three counters move into the ledger under named stages. No dual-write phase is introduced. The bespoke storage is deleted at the same time the ledger write is added:

- `auto_agent_attempts` moves to stage `"auto_agent"`.
- `sandbox_failure_fixer_attempts` (per-PR dict) moves to stage `"sandbox_fix"`, keyed by `str(pr.number)`.
- The per-issue quality-fix count moves to stage `"quality_fix"`.

The `StateData.auto_agent_attempts` and `StateData.sandbox_failure_fixer_attempts` fields are deleted. `quality_fix_attempts` is removed from the `WorkerResultMeta` TypedDict.

StateTracker accessor names and call signatures are preserved unchanged (all call-sites remain untouched). The accessor bodies now delegate to the ledger rather than to `StateData` fields.

This completes the single-source-of-truth arc that Phase 1 began with `review_attempts` and `review_blast_radii`.

### Serialization and migration cost

`StateData` uses `ConfigDict(extra="ignore")`. Old `state.json` files containing the removed keys (`auto_agent_attempts`, `sandbox_failure_fixer_attempts`) load without error, silently dropping those values. In-flight attempt counters reset to 0 on the first load after deploy.

This is acceptable because attempt counters are transient operational state, not durable data. The outcome matches the Phase 1 `review_attempts` precedent: no data-migration shim is provided, and no shim is needed. An issue that was mid-flight gets a fresh attempt budget, which is the safe direction.

### Sandbox counter keyed by PR number

GitHub PRs and issues share one number namespace per repo. The sandbox-fix loop already passes `pr.number` as the issue identity to the runner and workspace. Keying the sandbox counter's ledger entry by `str(pr.number)` is coherent and cannot collide with a real issue's ledger entry. No PR-to-issue lookup is required.

### quality_fix decision: count moves, within-run cap stays

The cap on quality-fix iterations is enforced within a single worker run by the local `for` loop in `Agent._run_quality_fix_loop`. That loop is untouched by this migration.

Only the per-issue COUNT is moved into the ledger. `implement_phase` writes it via `set_quality_fix_attempts`; `retrospective` reads it from the ledger. The count is per-run, not accumulating across runs. This is a deliberate no-behavior-change choice: the count tracks what happened in the most recent run, which is all `retrospective` needs for its analysis.

The global lifetime aggregate `lifetime_stats.total_quality_fix_rounds` and the `record_stage_retry` helper are unrelated concerns and are left untouched.

### Attempts vs verdicts on StageRecord

This migration writes `StageRecord.attempts` for the `"auto_agent"`, `"sandbox_fix"`, and `"quality_fix"` stages. The Phase 2b boundary recording (ADR-0096) writes `StageRecord.last_verdict` and `last_finding_signatures` for the Triage, Shape, Plan, and Review stages.

The three stages added here are attempt-only slots. No verdict is recorded for them, so `last_verdict` remains `"UNVISITED"` and they play no role in any gated-stage convergence check.

### Always-on storage, not flag-gated

The Gate decision path is behind `convergence_gate_enabled`. Ledger storage is always on, mirroring the Phase 1 split. These counter writes are not conditional on any flag.

## Rules and consequences

1. **Single source of truth for all attempt counters.** No attempt count lives outside the ledger. Adding a new per-issue attempt counter means adding a new stage to the ledger, not a new `StateData` field.
2. **Accessor signatures are stable.** Call-sites must not be updated when counter storage changes. The accessor layer absorbs storage evolution.
3. **Fresh budget on deploy.** In-flight attempt counters reset to 0 on the first load after any deploy that removes bespoke fields. Operators should treat in-flight issues as starting fresh attempt budgets after a Phase 2c deploy.
4. **Sandbox stage key is str(pr.number).** Any code that reads or writes the sandbox-fix attempt count must use `str(pr.number)` as the ledger key. Numeric keys would not match.
5. **quality_fix count is per-run.** Do not use the ledger count as a cross-run cap or accumulator. It reflects the most recent run's iteration count only.

## Scope (Phase 2c)

This ADR covers the direct migration of three attempt counters into the ledger without helper abstractions, and an integration scenario that exercises the `sandbox_fix` counter path through the real `SandboxFailureFixerLoop` (representative of the shared accessor-delegation pattern all three migrations use). Out of scope: Phase 2d's `ConvergenceOscillationLoop` caretaker, which consumes verdict history rather than attempt counts.

## Alternatives considered

1. **Keep bespoke counter dicts in `StateData`.** Rejected. Leaves the ledger as a partial view of per-issue retry state. The whole point of the convergence ledger arc is to consolidate so that a reader of the ledger sees the full picture.
2. **Migrate `quality_fix` as an accumulating lifetime cap.** Rejected. The within-run cap semantics are production behavior. Changing the count to accumulate across runs would silently tighten the cap for issues that have been processed multiple times, altering escalation behavior without any explicit signal. The safe migration moves the count with identical semantics.

## When to supersede this ADR

Supersede when: a new phase changes attempt counter semantics (for example, introducing cross-run accumulation); the `StageRecord` schema changes what "attempts" means; or a future refactor changes how accessor delegation to the ledger works.

## Source-file citations

- `src/state/_auto_agent.py`: StateTracker accessor for `auto_agent_attempts`, now delegating to the ledger under stage `"auto_agent"`.
- `src/state/_sandbox_failure_fixer.py`: StateTracker accessor for `sandbox_failure_fixer_attempts`, now delegating to the ledger under stage `"sandbox_fix"`, keyed by `str(pr.number)`.
- `src/state/_convergence.py`: `set_quality_fix_attempts` and related read accessor, delegating to stage `"quality_fix"`.
- `src/implement_phase.py`: writes quality-fix count via `set_quality_fix_attempts` at the end of a worker run.
- `src/retrospective.py`: reads quality-fix count from the ledger for post-run analysis.
- `tests/scenarios/test_convergence_counter_migration_mockworld.py`: integration scenario driving the real `SandboxFailureFixerLoop` to prove the `sandbox_fix` counter lands in the ledger through production code (representative of all three migrations' shared delegation pattern).
