# ADR-0093 — Loop fitness as a measured contract

**Status:** Accepted
**Date:** 2026-06-30
**Enforcement:** enforced
**Enforced by:** pytest:tests/test_loop_fitness_completeness.py

## Context

HydraFlow runs ~44 background loops. Nothing scored **per-loop effectiveness** — a loop's own conversion rate, FP rate, or throughput. `HealthMonitorLoop` already hill-climbs pipeline-level params; `TrustFleetSanityLoop` watches for fleet-level anomalies; `RetrospectiveLoop` verifies whether a past proposal reduced problem frequency. None of those surfaces intra-loop ROI.

The long-term destination is a full per-loop hill-climb optimizer: score candidate configs by **offline replay of recorded history**, shortlist winners, and prove the top candidate in a guarded online canary with auto-revert. That optimizer cannot exist without a read-only fitness layer to replay against.

This ADR builds only the prerequisite: a **measured fitness contract** on every loop, designed optimizer-ready from day one. No mutation, no tuning, no canary — purely observational.

## Decision

### 1. Required `loop_fitness` method on `BaseBackgroundLoop`

`src/base_background_loop.py:BaseBackgroundLoop` gains one required method alongside the existing abstract hooks `_do_work()` and `_get_default_interval()`:

```python
def loop_fitness(self, ctx: FitnessContext) -> LoopFitness: ...
```

A non-abstract default that returns `HOUSEKEEPING` is provided so that the ~44 existing loops are grandfathered without a migration wave. New loops shipped after this ADR must declare an explicit override — the ratchet in `tests/test_loop_fitness_completeness.py` enforces this by AST-discovering every subclass and failing if `loop_fitness` is not defined directly on it.

### 2. Purity constraint (the keystone)

`loop_fitness()` MUST read **only** from the injected `ctx: FitnessContext`. It MUST NOT read `self` mutable state, call the network, read the filesystem, call the clock, or touch any global.

`src/loop_fitness.py:FitnessContext` is a frozen Pydantic model — a data-only snapshot: the evaluation window (`window_start`, `window_end`), this loop's `BACKGROUND_WORKER_STATUS` events pre-filtered to the window, a snapshot of issues/PRs relevant to the loop, and optional per-loop cost. No live GitHub client is included or accessible.

This is the design pivot that allows one fitness function to serve two callers:

- **Scorecard now:** `ctx` is built from live recorded history.
- **Optimizer later:** `ctx` is built from replayed history for a candidate config.

A fitness function that called a live GitHub client would score a candidate against today's repo instead of the historical snapshot — silently wrong. The purity constraint prevents that class of bug and makes every fitness function a pure, unit-testable function over synthetic inputs.

### 3. `HOUSEKEEPING` declared escape hatch

Not every loop has a meaningful 0–1 fitness. `WorkspaceGCLoop`, `DiagramLoop`, `PricingRefreshLoop`, and others perform discrete maintenance with no proposal/acceptance lifecycle. Forcing a normalized score for these loops manufactures garbage.

`src/loop_fitness.py:FitnessKind` defines two variants:

- `SCORED` — emits a normalized `score` in [0, 1] plus raw `components`.
- `HOUSEKEEPING` — emits raw `components` only (`score = None`). A valid, explicit declaration, not a missing measurement.

The ratchet requires a **declaration**, not a non-`None` score. A loop that explicitly returns `HOUSEKEEPING` passes; a new loop that inherits the default without overriding fails the ratchet.

### 4. No cross-loop leaderboard rule

`src/loop_fitness.py:LoopFitness` carries a `score` field normalized 0–1. That normalization is valid **only for intra-loop use** — comparing this loop's score today vs. 30 days ago, or comparing two candidate configs for this same loop (future optimizer). It is explicitly invalid to rank loops against each other: a GC loop reclaiming 12 branches is not "better" or "worse" than a proposer loop with a 0.6 acceptance rate. Comparing scores across archetypes is meaningless by construction.

The generated artifact (`docs/arch/generated/loop-fitness.md`) MUST present per-loop trend views. It MUST NOT present a single fleet ranking.

### 5. Confidence by `sample_count`, not wall-clock window

Slow loops (e.g., daily) accumulate ~30 samples in a 30-day window; fast loops (~120 s) accumulate ~21,600. A fixed wall-clock window cannot express whether a sample is sufficient for either. Confidence is therefore keyed off `src/loop_fitness.py:LoopFitness.sample_count` against a per-loop threshold (default `min_samples = 20`).

`src/loop_fitness.py:Confidence` has two values: `OK` (score is trustworthy) and `INSUFFICIENT_DATA` (score is `None`; more observations needed). Slow loops sit in `INSUFFICIENT_DATA` for a long time — this is correct behavior and, deliberately, keeps the future optimizer's hands off loops with insufficient evidence.

### 6. `FitnessScorecardLoop` producer

`src/fitness_scorecard_loop.py:FitnessScorecardLoop` is a new caretaker loop (ADR-0029 shape): extends `BaseBackgroundLoop`, honors the `enabled_cb` kill-switch at the top of `_do_work()` (ADR-0049), and returns a stats dict. Each tick it:

1. Builds one `FitnessContext` per registered loop (batched event history + a single issue snapshot + optional cost).
2. Calls every registered loop's `loop_fitness(ctx)`.
3. Persists results to `.hydraflow/metrics/{repo_slug}/fitness.jsonl`.
4. Regenerates `docs/arch/generated/loop-fitness.md`.
5. Emits a `LOOP_FITNESS_UPDATE` event for the dashboard panel.

`FitnessScorecardLoop` itself declares `HOUSEKEEPING` fitness — it produces no GitHub artifacts.

Because the loop is read-only and mutates no loop state, it sits **off the ADR-0046 recursion ladder** — there is no bounded recursion to enforce when nothing mutates loop behavior.

### 7. Substrate position for the deferred optimizer

This ADR ships the observation layer and nothing more. The deferred optimizer will:

1. Read `fitness.jsonl` to identify underperforming loops.
2. Replay `FitnessContext` snapshots against candidate configs offline.
3. Promote the best-scoring candidate to a guarded online canary with auto-revert.

Step 2 is only possible if fitness functions satisfy the purity constraint from day one. This ADR locks that constraint in so the optimizer can be built against a stable substrate.

## Consequences

- Every new loop shipped after this ADR must define an explicit `loop_fitness()` override. The ratchet (`tests/test_loop_fitness_completeness.py`) enforces this at CI time.
- Fitness functions are pure, synthetic-input-testable functions. Unit tests for `loop_fitness()` do not require a running GitHub client.
- The `HOUSEKEEPING` escape means even maintenance-only loops are accounted for in the scorecard without manufacturing a fake normalized score.
- Cross-loop score comparison is architecturally invalid. Dashboard tooling must not present a fleet ranking.
- The purity constraint is a forward commitment: the optimizer spec can assume `FitnessContext` is the only input to any fitness function, without auditing each loop's implementation.

## References

- [ADR-0029](0029-caretaker-loop-pattern.md) — Caretaker Background Loop Pattern. `FitnessScorecardLoop` follows this shape: `BaseBackgroundLoop` extension, stats dict return, no `DedupStore` needed (read-only/idempotent).
- [ADR-0046](0046-meta-observability-bounded-recursion.md) — Meta-observability with bounded recursion. `FitnessScorecardLoop` is read-only and mutates no loop state, so it sits off the recursion ladder — there is nothing to bound.
- [ADR-0049](0049-trust-loop-kill-switch-convention.md) — Trust-loop kill-switch convention. `FitnessScorecardLoop._do_work()` gates on `enabled_cb("fitness_scorecard")` per convention.
- [ADR-0053](0053-ubiquitous-language-as-living-artifact.md) — Ubiquitous Language as a Living Artifact. Terms `loop fitness`, `fitness scorecard`, and `fitness context` are seeded in `docs/wiki/terms/`.
- `src/loop_fitness.py:FitnessContext` — pure data-only input model
- `src/loop_fitness.py:LoopFitness` — one loop's fitness for one window
- `src/loop_fitness.py:FitnessKind` — SCORED vs HOUSEKEEPING declaration
- `src/loop_fitness.py:proposal_acceptance_fitness` — reference implementation for proposer-archetype loops
- `src/base_background_loop.py:BaseBackgroundLoop` — contract host
- `src/fitness_scorecard_loop.py:FitnessScorecardLoop` — producer
