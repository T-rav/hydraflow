# ADR-0124: Tier-2 goal supervisor — a Fable "mini-me" over Tier-1's liveness signals

- **Status:** Proposed
- **Date:** 2026-08-02
- **Related:** [ADR-0029](0029-caretaker-loop-pattern.md) (caretaker-loop pattern), [ADR-0049](0049-trust-loop-kill-switch-convention.md) (kill-switch convention), [ADR-0045](0045-trust-architecture-hardening.md) (trust fleet / meta-observability), [ADR-0093](0093-loop-fitness-as-measured-contract.md) (fitness contract), [ADR-0119](0119-credit-failover-to-glm.md) (credit failover state the snapshot reads)
- **Addresses:** #10733 (two-tier OTP supervision — Tier-2 mini-me + vitals)

> **This is a Proposed ADR — a design ruling for decision, not an accepted commitment.** It records the target design and, deliberately, what is *real today* (this PR) versus *deferred* so the enable decision is made on evidence. The loop ships **default OFF**. Accept, amend, or reject.

## Context

Issue #10733 formalizes the "keep the factory running and flowing" monitor — currently a bespoke Claude agent an operator runs by hand — into a durable **two-tier supervision tree**: a boring deterministic Tier-1 liveness kernel that repairs *mechanism* (restart-to-known-good, no LLM), a goal-driven Tier-2 "mini-me" that redirects *mission* it can, and the human at the apex for anything the system may *become*. Each tier is a **monitor, not a link** — it survives the thing it watches dying.

Tier-1 signals already exist, scattered: per-loop heartbeats (`StateTracker.get_worker_heartbeats`), credit-pause / GLM-failover state (`credit_failover`, ADR-0119), boot-SHA / commits-behind staleness (`git_revision`), the event-loop watchdog marker (`event_loop_watchdog`), and the second-order vitals verdict. `HealthMonitorLoop` (ADR-0045 meta-observability) is the deterministic Tier-1 actuator that *consumes* some of these and restarts stalled loops. What was missing is the **Tier-2 layer**: a goal-driven agent that reads one assembled snapshot, diagnoses, and either nudges the reversible or surfaces the rest — the behavior the operator was doing by hand.

This ADR builds that Tier-2 layer as the `GoalSupervisorLoop`. It deliberately **defers** the heavy Tier-1 deterministic-kernel enumeration (the honest launchd liveness kernel, #10734; the formal give-up window as a first-class child, #10735) — those are separate children of #10733. Tier-2 consumes Tier-1's signals; it does not re-implement them.

## Decision

Introduce **`GoalSupervisorLoop`** (`src/goal_supervisor_loop.py`), a Tier-2 (meta-observability) caretaker loop (ADR-0029) that ticks on a cadence, assembles a read-only `HealthSnapshot` from the existing Tier-1 signals, hands it to a **Fable** agent (`claude-fable-5`) under the standing goal *"keep the factory alive & healthy,"* and records a `SupervisorObservation` to an append-only thread + the event bus. It ships **default OFF** (`goal_supervisor_loop_enabled=False`) behind the ADR-0049 kill-switch.

### Ruling 1 — it reuses Tier-1 signals; it does not re-detect

`build_health_snapshot(...)` (`src/supervisor_observation.py`) is a **pure** function over primitives — per-loop heartbeats + intervals, credit-failover state, boot-SHA/commits-behind, the watchdog marker, the vitals verdict. The loop is a thin actuator that reads those signals and passes them in; the snapshot never detects on its own and never mutates anything. A loop is *stalled* when its heartbeat age exceeds `3× interval` (mirroring `HealthMonitorLoop`'s `_WORKER_STALL_MULTIPLIER`); *errored* when its last heartbeat status is `error`; `disabled` loops are never flagged.

### Ruling 2 — authority is watch + surface + NUDGE, with a small explicit allowlist

The supervisor is a **monitor, not a fixer**. The reversible nudge allowlist (`NUDGE_ALLOWLIST`) is small and explicit: restart a stalled loop, poke a wedged promotion, re-run a flaky required check, re-arm a stuck credit-pause probe, flag boot-SHA staleness. Everything else escalates — **surfaced, never self-done** — including anything with blast radius: force-push, deletes, config/gate flips (the self-mod class), RC→main promotion, repeated failed heals. This mirrors [`docs/standards/factory_autonomy`](../standards/factory_autonomy/README.md) (act on tractable + reversible; ask on high-blast-radius).

### Ruling 3 — the operating contract is code, not prompt

The load-bearing safety lives in pure, unit-tested functions in `src/supervisor_observation.py`, *not* in the Fable prompt. The prompt is short and states the goal + a compressed contract; the code enforces it. The eight-rule operating contract, mined from how a capable operator actually runs this factory:

| # | Rule | Where enforced |
|---|------|----------------|
| 1 | **Classify before acting** — transient (flaky check, CDN/NodeSource 403, xdist contamination, stray file) → wait/re-run, spend no nudge; real → act or escalate | `classify_action` (pure); prompt rule 1 |
| 2 | **Tractable + reversible → self-do; blast-radius → escalate** | `decide` + `NUDGE_ALLOWLIST` (pure); prompt rule 2; mirrors factory_autonomy |
| 3 | **Root-cause first** — a nudge carries a one-line diagnosis pulled from the signal; a cause-less action is dropped as noise | `decide` (pure); recorded on every `SupervisorObservation` |
| 4 | **Bounded retries then escalate** (give-up window, reusing #10735) — an incident is nudged ≤ `GIVEUP_CAP` times, then escalates; the attempt ledger persists across ticks; never infinite-retry | `decide` + `load/save_attempts` |
| 5 | **Counter-metric self-check** (#10840) — repeat-without-improvement is over-reach; the give-up window *is* the counter-metric (a nudge that never clears its condition escalates instead of looping) | `decide` + `reconcile_ledger` |
| 6 | **Honest thread** — each observation states the truth: transient vs real, nudged-pending vs escalating; never a fabricated resolution | `SupervisorObservation` shape; nudges read `pending verify` |
| 7 | **Known-incident knowledge first** — recognized signatures (stale-boot, wedged loop, stuck credit-pause, event-loop freeze, diverging vitals) use the known remedy before the agent diagnoses cold | `derive_incidents` (pure) runs before agent actions |
| 8 | **Verify the nudge + re-arm** — a nudge is *pending* until a later tick confirms its condition cleared; a still-present incident counts toward the give-up window (rule 4) | `reconcile_ledger` at each tick start |

### Ruling 4 — the honest thread + a read endpoint the console consumes

Each tick appends a `SupervisorObservation` (`ts` · snapshot summary · `assessment` · `insights` · `nudges_taken` · `escalations` · `deferred`) to `<data_root>/supervisor_thread.jsonl` and emits a `SUPERVISOR_OBSERVATION` event. `GET /api/diagnostics/supervisor/thread?limit=N` surfaces the recent thread for the operator console's supervisor panel. When the factory is healthy the loop **no-ops without consulting the Fable agent** (cost control) — it only spends a Fable call on degradation.

### Ruling 5 — the tiers stay separate; no LLM in the deterministic kernel

`GoalSupervisorLoop` is registered standalone (not folded into `HealthMonitorLoop`) precisely because `HealthMonitorLoop` is the Tier-1 *mechanism* repairer (deterministic, no LLM) and this is the Tier-2 *mission* redirector (goal-driven Fable agent). Fusing them would put an LLM in the deterministic kernel — the opposite of the OTP two-tier intent. Both live in the `meta_observability` functional area.

## What is real today (this PR) vs deferred

**Real:** the loop + pure decision core (classify / known-incident / nudge-vs-escalate / give-up window / verify) + the Fable runner + the honest thread + the read endpoint + the reversible nudges `restart_stalled_loop` / `poke_wedged_promotion` / `rearm_credit_probe` / `flag_boot_sha_staleness`, all default-OFF and fully wired (seven-checkpoint + full-suite ratchets).

**Deferred (honestly):**

- `rerun_flaky_check` is a recognized allowlist *kind* but has **no CI re-run seam** wired yet — it defers to CI's own auto-retry and the observation says so (rather than fabricating a resolution). Wiring a real CI re-run verb is a follow-up.
- The give-up cap is a module constant (`GIVEUP_CAP = 1`), not yet a config knob.
- The counter-metric self-check is v1-simple (escalate on repeat-without-improvement via the give-up window). A richer "routed-around" fleet-oscillation sensor (#10840) is separate.
- The snapshot reads credit-failover state (ADR-0119) rather than the orchestrator's `run_status`/`credits_paused_until` — a deliberate choice to avoid a circular orchestrator reference and keep the loop's deps clean.
- The heavy Tier-1 deterministic liveness kernel (#10734) and the formal give-up window as a first-class supervised child (#10735) remain separate children of #10733.

## Consequences

- **Positive:** the by-hand "keep it flowing" monitor becomes a durable, kill-switched, cost-bounded loop with an honest, console-visible thread; the load-bearing safety is pure and unit-tested; the reversible/escalate boundary is explicit and mirrors the factory-autonomy standard.
- **Cost:** each degraded tick spends one Fable (`claude-fable-5`) call; healthy ticks are free (no agent). Cost attributes correctly (the runner prices against the Fable model).
- **Negative / watch:** a mis-tuned cadence or an over-eager agent could spend Fable calls on churn — the healthy→no-op gate and the give-up window bound this, and the counter-metric escalates rather than loops. Default OFF means no behavior change until an operator enables it.

## Enforced by

- Kill-switch (both gates): `tests/test_loop_kill_switch_completeness.py`, `tests/test_goal_supervisor_loop.py`.
- Loop wiring + fitness + functional-area + catalog: `tests/test_loop_wiring_completeness.py`, `tests/test_loop_fitness_completeness.py`, `tests/architecture/test_functional_area_coverage.py`, `tests/scenarios/catalog/test_catalog_completeness.py`.
- Pure decision core + loop behavior: `tests/test_goal_supervisor_loop.py`.
- MockWorld scenario (idle-healthy + fires-on-degraded): `tests/scenarios/test_goal_supervisor_scenario.py`.
