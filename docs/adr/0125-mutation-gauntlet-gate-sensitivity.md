# ADR-0125: Mutation gauntlet — measuring gate sensitivity by injecting known faults

- **Status:** Proposed
- **Date:** 2026-08-02
- **Related:** [ADR-0108](0108-deterministic-simulation-fault-injection-evaluation.md) (Deterministic-Simulation Fault Injection on the Sandbox Compose — Evaluation) — the deferred, hypervisor-level fault-injection sibling this complements; [ADR-0044](0044-hydraflow-principles.md) (HydraFlow Principles — the audit contract for new and existing repos) — "make failure observable" applied to the gates themselves; [ADR-0094](0094-two-level-convergence-gate-and-ledger.md) (Two-level convergence: Gate + ConvergenceLedger) and [ADR-0102](0102-convergence-gate-general-availability.md) (Convergence gate general availability (flag removed)) — the gate whose sensitivity this measures
- **Enforcement:** enforced
- **Enforced by:** `pytest:tests/mutation/test_catalog.py`
- **Binds:** factory
- **Addresses:** #10835 (mutation-testing the gauntlet); prospective twin of #10367 (escape ledger)

> **This is a Proposed ADR — a design ruling for decision, not an accepted commitment.** It records the methodology and, deliberately, what is *real today* (this first slice) versus *deferred* to later phases. The instrument is an on-demand `scripts/`-invoked diagnostic, not a background loop, and it is not wired into CI. Accept, amend, or reject.

## Context

The factory publishes a claim it cannot currently check: **the gates are real.** A green gauntlet is consistent with *both* "the change was good" *and* "the gate is insensitive," and nothing today distinguishes those two worlds. Two live examples make the gap concrete:

- The prompt-prune eval (#10860) that stayed green while a reviewer *security instruction* was deleted — a gate blind to a fault it owned.
- Flaky gates (xdist isolation, #11004) whose red/green is not a faithful function of the change.

The escape ledger (`escape.ledger`, #10367) measures this property **retrospectively**: it records defects that already got through, at whatever rare, lagging rate reality supplies. That is necessary but slow and passive — you learn a gate was blind only after a real defect exploited it. What was missing is the **prospective** measurement: inject a known fault on demand and observe whether the gate that owns it goes red. The mutation gauntlet is that prospective twin.

This is deliberately *not* ADR-0108's deterministic-simulation fault injection. ADR-0108 targets concurrency/timing schedules at the hypervisor level and is deferred pending spend; the mutation gauntlet is cheap, in-repo, and code-level. They are complementary, not competing.

## Decision

Introduce the **mutation gauntlet**: a curated mutant catalog plus a runner that scores **gate kill rate** — the fraction of injected faults a gate catches.

### Ruling 1 — a curated, version-controlled catalog, one mutant per fault class

The catalog (`tests/mutation/catalog.py`) is **data**, not a whole-suite `mutmut`/`cosmic-ray` sweep. Each mutant is a real `(file, find, replace)` patch against real source, tagged with the `MutantClass` of fault it injects and the `target_gate` that MUST kill it. The class → owning-gate map localizes each miss to exactly one weak gate:

| Mutant class | Fault injected | Owning gate |
|---|---|---|
| `logic` | off-by-one / flipped comparison in a pure decision fn | unit tests |
| `contract` | adapter accepts a wrong shape / a Port swallows instead of raises | fake-coverage auditor + adapter contract tests |
| `scenario` | a loop advances a label it shouldn't / skips a checkpoint | MockWorld scenario tests |
| `vocabulary` | rename a ubiquitous-language term away from its anchor | UL conformance ("Gates Drift") |
| `adr` | violate an Accepted ADR's enforced structural rule | ADR conformance |
| `safety` | a fail-closed guard flipped to fail-open | the guard's own test, asserting fail-closed |

Every catalog mutant carries `expectation = KILLED`; a **survivor is a finding**, never the authored expectation.

### Ruling 2 — a pure core + a thin I/O shell

The verdict and kill-rate logic lives in a pure, fully unit-tested core (`src/mutation_gauntlet.py`): `src/mutation_gauntlet.py:plan_campaign`, `src/mutation_gauntlet.py:classify_result`, and `src/mutation_gauntlet.py:summarize`. It has no subprocess and no git dependency, so the load-bearing math is testable in isolation. The thin I/O shell (`scripts/mutation_gauntlet.py`) materializes a scratch git worktree at HEAD, applies the patch, runs **only** the mutant's `target_gate` via its real entrypoint, captures the exit code, calls back into the pure core to classify, and discards the worktree.

### Ruling 3 — honest, fail-closed verdict semantics

Three verdicts, and the boundary between them is load-bearing:

- **KILLED** — the gate ran and went red (nonzero exit). The fault was caught.
- **SURVIVED** — the gate ran and stayed green despite the fault. This is a **finding**: the gate is blind to a fault it owns.
- **ERRORED** — the gate could not run cleanly (the patch did not apply, or the gate crashed). An `ERRORED` mutant is **never** silently counted as `KILLED`; it is excluded from the kill-rate denominator but always counted and reported.

Kill rate = `killed / (killed + survived)` per gate and per class. An empty or all-errored bucket reports `None` (rendered `n/a`), not `0.0` — the honest reading of "no evidence," not "0% caught."

### Ruling 4 — on-demand only; not a loop, not in CI

The instrument runs one real gate per mutant, which is cost-prohibitive on the merge path. It is a `scripts/`-invoked diagnostic (`make mutation-gauntlet`), **not** a background loop — no seven-checkpoint wiring, no MockWorld shim. It emits `<data_root>/mutation/gate_kill_rate.jsonl` (append-only, one row per campaign) plus a stdout summary; a survivor exits nonzero so the caller surfaces a blind gate.

## What is real today (this first slice) vs deferred

**Real:** the pure core (models, `plan_campaign`, `classify_result`, `summarize`, the jsonl row + summary rendering); the I/O shell (scratch-worktree apply + single-gate run + append-only emit) with a fail-closed guard that never counts `ERRORED` as `KILLED`; a seed catalog of six mutants (one per class) against real source; the full unit suite for the pure core; a fixture-gate integration test proving **both** a KILLED and a SURVIVED verdict flow through the real worktree/patch/classify pipeline (the SURVIVED case proves the instrument can detect a blind gate — the #10860 failure mode one level up); and the on-demand `make mutation-gauntlet` target.

**Deferred (honestly):**

- **Phase 2** — broaden the catalog (auto-generate `logic` mutants for a critical module via AST) and add a *full-gauntlet* run mode where a mutant must be blocked from reaching `merged`, not merely fail one gate.
- **Phase 3** — a slow-cadence monitored series that tracks per-gate kill rate as a process variable against a setpoint and alarms on a *falling* gate (ties into the stillness setpoint program, #10824/#10826). This slice only *produces* the `.jsonl` substrate; it does not watch it.
- Running the seed catalog against its real gates in the automated test suite is deliberately out of scope (too slow); the catalog is validated as data (schema + anchor-resolution fidelity), and the real-gate runs are the on-demand `make mutation-gauntlet` job.

## Consequences

- **Positive:** "the gates are real" becomes a measurable, on-demand property rather than an article of faith. A survivor localizes exactly one weak gate and the fault class it missed, which is directly actionable (file a `hydraflow-find` naming the gate). The instrument itself is guarded against the very failure it hunts: a fixture-gate integration test proves it reports SURVIVED for a deliberately blind gate, so a runner that always reported KILLED would fail its own suite.
- **Cost:** each real campaign spends one full gate run per selected mutant — hence on-demand only, never on the merge path.
- **Negative / watch:** the catalog is hand-authored and can rot when a refactor moves a mutation point; the catalog fidelity test (anchor-resolution against the live tree) turns that rot into a loud failure rather than a silent `ERRORED`. A catalog that grows without curation would drift toward a slow `mutmut` sweep — the one-mutant-per-class discipline is the guard against that, to be revisited only at Phase 2.
