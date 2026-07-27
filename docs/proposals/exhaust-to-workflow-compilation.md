# Exhaust to workflow: compiling recurring probabilistic routes into deterministic graphs

**Status:** proposal (2026-07-26), capturing an active design direction. **Depends on:** the exhaust surfaces (convergence ledger, route-backs/laps, retrospective and review-insights series), the graduation conventions.

**Precedent:** trace-based JIT compilation (interpret until a path runs hot, compile the hot path, deoptimize on guard failure); case-based reasoning; system identification in control engineering (identify the plant from operating data, then replace feedback search with feedforward routing where the model is trusted). **Divergence:** the "program" being compiled is a work process discovered by a stochastic agent, and the compiled route's correctness is enforced by gates, not by semantics-preserving transformation.

## The gap

Some classes of work are solved by wandering: the probabilistic route works, but it thrashes — laps, route-backs, re-planning, the same class of change re-deriving the same path every time. The exhaust already records the stable route the wandering keeps finding (which stages, which artifacts, which checks mattered). Nothing compiles it. Every instance pays the discovery cost again, and the thrash is variance the system has already paid to reduce once.

## Design sketch

Decompose the probabilistic thing into a more deterministic route, on evidence:

1. **Mine** the exhaust per work class for recurring solve-shapes: stage sequences, artifact patterns, and check outcomes that repeat across instances with low variance.
2. **Propose** a workflow template (a small DAG) for a class once its route is stable across N instances: fixed steps, expected artifacts, pre-checks, and the narrow slots where the probabilistic agent still runs — bounded search inside steps, instead of open wandering between them.
3. **Guard** every compiled route with explicit preconditions. A guard failure deoptimizes: the instance drops back to the probabilistic route, and the deoptimization is recorded (a compiled route that keeps deoptimizing is miscompiled, and the record says so).
4. **Graduate, do not deploy.** A compiled workflow is a promotion with a signature, per the existing convention: proposed from evidence, accepted by a person, demotable by one deoptimization threshold without a meeting.

In control terms: the wandering is feedback search; the compiled route is feedforward for the well-identified region of the plant; the guards are the region boundary; deoptimization is the return to closed-loop control where the model is no longer trusted. Determinism where earned, probability only at the frontier.

## Open questions (deliberately unresolved)

- Template representation: what a workflow artifact is, where it lives, how it is versioned.
- Staleness: a compiled route rots like any encoding; it needs its own re-validation ratchet (deopt-rate as the erosion signal for workflows).
- Scope boundary against skills: a skill makes one step reliable; a workflow is the route between steps. Keep the two from blurring.
- Mining thresholds: what N and what variance bound earn a proposal.

## Acceptance

- Thrash metrics (laps and route-backs per class) drop on compiled classes and are reported per class.
- Deoptimization rate is visible per workflow; a threshold demotes automatically.
- No route is compiled without the evidence trail that proposed it, and none activates without a signature.
