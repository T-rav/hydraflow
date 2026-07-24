# Goal-Seeking Control Layer for Background Workers (`signal_control`)

**Status:** Design — approved for implementation planning
**Date:** 2026-07-23
**Author:** HydraFlow factory (Travis + Claude)
**Related:** ADR-0045 (trust fleet), ADR-0049 (kill-switch convention), ADR-0042 (two-tier branch/RC promotion), `src/circuit_breaker.py`, `src/trust_fleet_anomaly_detectors.py`, `src/staging_promotion_loop.py`

---

## Problem

Background workers act on **raw instantaneous signals** as if they were ground truth, and over-react to transient noise:

- A rate-limit event was mislabeled "out of credits," which cascaded into a HITL storm.
- A single 24h-window spike tripped a trust-fleet anomaly detector into escalation; detectors flap between "broken" and "fine" and re-fire every tick because they compare `value >= threshold` with no smoothing, no hysteresis, and no historic baseline.
- The `StagingPromotionLoop` closes and re-cuts an RC PR on the **first** merge failure — even when the cause is a still-pending CI run or a benign auto-resolvable rebase.
- Oversubscription (too many concurrent agents) drove LLM rate-budget truncations up, which parked backlog and churned HITL — with no mechanism to throttle the fleet and ramp it back.

The common defect: **no separation between measuring a signal and acting on it, and no memory of what "normal" looks like.** This spec introduces one small, reusable control layer that every worker routes decisions through.

## Goal

A goal-seeking control framework so workers stop freaking out on faulty/noisy signals:

1. **Condition** raw signals into trustworthy state (smoothing, hysteresis, change-detection, corroboration) against **historic** baselines.
2. **Control** actuators toward a **setpoint** with bounded, stable moves (goal-seeking, not bang-bang).
3. Apply it concretely to: an **adaptive concurrency governor** (primary controller), the **trust-fleet detectors** and **credit handler** (conditioners), and **RC-merge resilience** (bounded fix-retry).
4. Ship fail-safe: bounded authority, kill-switches, conservative defaults, and legible controller state.

## Non-Goals

- Not a metrics/observability replacement. `factory_metrics` / `metrics_manager` remain the human dashboards; the control substrate is separate and sampled at control-tick resolution.
- Not a rewrite of the loops. Integration is thin and per-site; the toolkit is pure and reusable.
- No new ML/forecasting. Classical control theory only (EWMA, hysteresis, CUSUM, AIMD/PID, circuit breaker) — deterministic and testable.

---

## Scope: which loops adopt this

The framework is a **toolkit adopted by signal-reactive loops, not a rewrite of all workers.** Of the ~61 background loops, it applies **only** where a worker acts on a noisy/continuous signal or takes an expensive/irreversible action on a threshold. It does not touch the majority.

**Directly altered (initial PRs):**

| Site | Change | § |
|---|---|---|
| `staging_promotion_loop` | RC close-on-first-failure → bounded `RetryController` | §5 |
| `trust_fleet_anomaly_detectors` (5 detectors, consumed by `trust_fleet_sanity_loop`) | `value >= threshold` → composed conditioner chains | §3 |
| `orchestrator` `max_workers` | concurrency governor actuator | §2 |
| credit handler (shared, subprocess-spawning runners) | ad-hoc probe → `Corroborator` | §3 |

**Follow-on adopters (staged onto the landed toolkit, one small PR each — see rollout 4b):**

| Loop | Defect today | Toolkit fit |
|---|---|---|
| `flake_tracker_loop` | quarantine decisions flap on flake rate (the s75/s81 quarantine churn) | Hysteresis + Persistence |
| `health_monitor_loop` / `factory_health` | "is the factory wedged/stale" sensing on raw thresholds | CUSUM + Corroborator |
| `triage_retry_loop` | infra-park backoff via bespoke streak logic | `RetryController` + CircuitBreaker |

**Deliberately out of scope** — no signal to condition and re-running is cheap/safe, so the framework would be over-engineering: idempotent caretakers (DiagramLoop, RepoWikiLoop, arch-regen), event/label-driven routers, and pure producers (grooming, issue refinement).

---

## §1 — Core frame: *condition, then control*

Every worker decision routes through one pipeline:

```
raw signal → [Conditioner] → trustworthy state → [Controller] → bounded action
                  ↑                                     ↑
           historic signal store  ←──────────── setpoint / policy
```

- **Conditioners** turn noisy measurements into a belief you can act on.
- **Controllers** drive an actuator toward a setpoint with bounded, stable moves.
- A **historic signal store** (rolling, persisted) is the shared memory both layers read from.

Two collaborating layers, each a small unit with one job.

---

## §2 — Primary controller: adaptive concurrency governor

**Job:** keep the agent fleet as large as possible without oversubscribing the LLM rate budget — the failure that cascaded backlog into HITL.

| Element | Definition |
|---|---|
| **Measured `y(t)`** | Run-outcome health: EWMA fraction of recent agent runs ending in `rate_limit` / `out_of_credits` / truncation (`error_max_turns`, mid-stream `exit 1`) vs. clean `end_turn`. Read from the historic store, fed by `trace_collector` exit codes + `AGENT_ACTIVITY` outcomes + stream `rate_limit_event`s. |
| **Setpoint `r`** | A small target reject/truncation rate expressed as a **band** with a dead-band (e.g. trip above ~2%, only ramp when sustained below ~0.5%). The dead-band prevents hunting. |
| **Actuator `u(t)`** | A governor multiplier on the orchestrator's `max_workers` (per-stage concurrency cap, `orchestrator.py:865/1092`), plus a secondary spawn-admission delay. Hot-updatable via the existing config path. |

**Control law — AIMD, PID-framed.** For a saturating resource, AIMD (TCP-congestion-control shaped) is the robust default:

- error above band → **multiplicative decrease**: `cap ← max(round(cap·β), 1)` (β ≈ 0.5) — shed fast; harm compounds.
- error in dead-band, sustained for a hold-time → **additive increase**: `cap ← min(cap + 1, N)` — probe up slowly.

This is a PID with `Kd`-dominant-down / `Ki`-shaped-up; AIMD is the special case that is stable for this actuator without hand-tuning three gains. A general `PIDController` stays in the toolkit for continuous actuators (e.g. cadence) but the governor uses AIMD.

**Stability guards (mandatory for every controller):**

- **Saturation bounds** `[1, N]` — never 0 (deadlock), never unbounded.
- **Move-rate limit** — at most one adjustment per control period (~60s) → no oscillation.
- **Anti-windup** — the integral/probe term cannot accumulate against a saturated bound.
- **Fail-safe** — controller error or empty history → hold last good cap or fall to a conservative default. Never fail toward "spawn everything."
- **Kill-switch** — pin a fixed cap (`HYDRAFLOW_CONCURRENCY_GOVERNOR_DISABLED`).

---

## §3 — Conditioners (detector + credit side)

Small, pure, independently-testable units wrapping a raw metric. Detectors compose the chain they need instead of `value >= threshold`.

- **EWMA low-pass** — read a smoothed estimate, not the instantaneous count. `ewma ← α·x + (1-α)·ewma`.
- **Schmitt-trigger hysteresis** — two thresholds: trip at `T_high`, clear only at `T_low < T_high`. Kills the flap where alarms bounce between broken/fine and re-fire each tick.
- **Persistence / N-consecutive** — a breach must hold for `k` control periods before it counts (generalizes existing streak counters). Transients die in the debounce.
- **CUSUM change-point detection** — asks "has the process *sustainably shifted* from its recent baseline," not "is the value big now." Accumulates deviations and fires only on a real regime change; distinguishes a genuine step from noise, which a fixed threshold cannot.
- **Adaptive baseline thresholds** — thresholds derived from the store's rolling distribution (robust z-score / MAD), not hardcoded constants. "Anomalous" becomes relative to *this factory's normal*, so numbers don't rot as behavior drifts.
- **Corroborator** — promote the credit handler's ad-hoc "signal → live probe → act only if confirmed" to a first-class unit `Corroborator(probe, min_confirmations)`. Any high-blast-radius signal (credit exhaustion, "sensor broke," "loop wedged") must be independently re-observed before driving an irreversible action (pause, HITL, quarantine). Direct cure for the mislabeled-rate-limit storm.

Example compositions:
- issues-per-hour anomaly → `EWMA → AdaptiveThreshold → Hysteresis → CUSUM-confirm`.
- bare boolean sensor → `Persistence(k) → Corroborator`.
- repeated-failure signal → existing `circuit_breaker.py` as the open/half-open/closed conditioner.
- flake quarantine decision (`flake_tracker_loop`) → `EWMA(flake_rate) → Hysteresis → Persistence(k)` — a test must be *decisively* flaky before quarantine and *decisively* stable before release, killing the s75/s81 flap.
- factory-wedge / staleness sensing (`health_monitor_loop` / `factory_health`) → `CUSUM → Corroborator` — escalate only on a sustained regime shift, confirmed by a live probe.

The initial migration targets the trust-fleet detectors + credit handler; `flake_tracker_loop`, `health_monitor_loop`/`factory_health`, and `triage_retry_loop` adopt the same units as staged follow-ons (see Scope and rollout 4b).

---

## §4 — Historic signal store

Shared memory for both layers — small, single-purpose, no business logic.

- **Shape:** one bounded ring buffer per named signal (`agent_run_outcomes`, `rate_events`, `issues_per_hour`, `repair_ratio`, `rc_promotion_results`, …). Each entry `(monotonic_ts, value, tags)`. Bounded by count **and** age → O(1) memory per signal; old samples fall off.
- **Reads served** (computed once, cached per control tick): `ewma(α)`, `mean/std/median/MAD` over a window, `count_where(pred, window)`, `slope`, `cusum` accumulator. Detectors/governor call these instead of re-scanning raw event logs each tick.
- **Fed by** sources already emitting: `trace_collector` exit codes, `AGENT_ACTIVITY`/cost events on the bus, trust-loop metric collectors, `merge_promotion_pr` results. A thin `record(signal, value, tags)` sink subscribes once and appends — detectors stop their own ad-hoc 24h window scans.
- **Restart survival:** append-only JSONL per signal under the runs/state dir (same discipline as `DedupStore` disk-persist), reloaded on boot with age-pruning. Cold boot → conditioners return "insufficient history" and controllers **fail to conservative defaults** (governor holds a low cap; detectors don't fire) until the window refills. **Empty history never reads as "all clear."**
- **Not** a metrics system — it is the control substrate; coexists with `factory_metrics`/`metrics_manager`.

---

## §5 — RC-merge resilience as a bounded fix-controller

Today `merge_promotion_pr(auto_rebase=True)` does **one** rebase → re-poll-CI → merge cycle; on any failure `StagingPromotionLoop` immediately closes the RC PR, files the rolling feedback issue, and bumps the consecutive-failure streak. "Fail once → self-destruct" is the same twitchy pattern removed elsewhere.

**Reframe:** close + file-feedback is the *terminal action*; reaching it requires exhausting a bounded retry budget first.

- **`RetryController(max_attempts=2, backoff)`** wraps the fix cycle. Each attempt: re-fetch base, **re-rebase** RC branch onto current `main`, **re-poll CI to a terminal verdict** (a still-pending run is *waited on*, not counted as failure), then attempt merge.
- **Retryable vs terminal** classification: retryable = auto-resolvable rebase conflict, CI still pending, transient merge-race, 5xx. Terminal = genuine red required-check, hard conflict → short-circuit straight to close (don't burn attempt 2).
- **Backoff between attempts** so still-running CI can settle — bounded wait reusing the async-communicate timeout tiers, not an unbounded poll.
- **Only after both attempts (or a terminal failure)** run the existing close + feedback-issue + `increment_consecutive_rc_failures()` path. The feedback issue records *what each attempt hit* (attempt 1: rebase conflict in X; attempt 2: check Y red) so the next cadence starts better-informed.
- **Circuit-breaker tie-in:** `increment_consecutive_rc_failures()` → HITL escalation threshold is the outer breaker. Two nested loops: inner `RetryController` (fix this RC twice), outer circuit-breaker (RCs failing across cadences → stop auto-retrying, escalate).

Net: flaky-CI / benign-rebase RCs self-heal within cadence; only a real, repeated problem reaches a human.

---

## §6 — Fail-safe, kill-switches, observability

A layer that can throttle the factory and suppress alarms is itself high-blast-radius.

- **Per-controller kill-switch** (ADR-0049): `HYDRAFLOW_CONCURRENCY_GOVERNOR_DISABLED`, `..._ADAPTIVE_THRESHOLDS_DISABLED`, `..._RC_FIX_RETRY_DISABLED`. Disabled → revert to today's behavior (static `max_workers`, raw thresholds, one-shot RC).
- **Fail-safe, not fail-open.** Controller error or under-filled window → conservative action: governor holds a low cap; thin-history detectors don't fire (no cold-boot false alarms) *except* corroborated high-severity ones, which still require a live probe. The safety system fails cautious, never amplifying.
- **Bounded authority.** Governor writes only `[1, N]` on the concurrency knob — never labels, PRs, billing. Detectors may raise/clear alarms and request HITL but cannot take irreversible action without a corroborator. Separation of "sense" and "act."
- **Anti-windup + move-rate limits** apply to every controller.
- **Legibility.** Each control tick emits `{controller, measured, setpoint, error, action, cap_before→after, reason}` to the store + event bus. Surfaced via a `/api/control/governors` endpoint and a dashboard **"Controllers" panel** (per-controller state: cap, setpoint, last move, breaker open/closed, sparkline). When the factory throttles, you can see why — and tune `α`, band, β from evidence.

---

## §7 — Module layout, ADR, tests

### Module layout

```
src/signal_control/
  __init__.py          # public API surface
  store.py             # HistoricSignalStore: ring buffers + JSONL persist + reads (ewma/mean/MAD/cusum/count_where/slope)
  conditioners.py      # EWMA, SchmittHysteresis, Persistence(k), Cusum, AdaptiveThreshold(z/MAD), Corroborator(probe,min_conf)
  controllers.py       # AIMDController, PIDController, RetryController, CircuitBreaker (re-export/adapt existing circuit_breaker.py)
  governor.py          # ConcurrencyGovernor: composes store+conditioners+AIMD → max_workers cap; kill-switch; bounds; telemetry
```

- `store.py` / `conditioners.py` / `controllers.py` are **pure — no I/O, no factory imports** — trivially unit-testable and reusable.
- Integration is small per-site: `governor.py` reads store + writes orchestrator `max_workers`; trust-fleet detectors swap `value >= threshold` for a composed chain; `staging_promotion_loop` wraps its fix cycle in `RetryController`; credit handler's probe becomes `Corroborator`. Existing `circuit_breaker.py` is absorbed/adapted, not duplicated.

### ADR

New ADR (next in sequence): *"Control-theory signal conditioning and goal-seeking for background workers."* States the frame (§1), the mandate (new detectors/controllers compose from this toolkit, not raw thresholds), the fail-safe contract (§6), and kill-switches. Wiki entries + ubiquitous-language terms (`governor`, `setpoint`, `conditioner`, `corroborator`) follow.

### Test strategy — full pyramid + property-based controller simulation

- **Unit** — each conditioner/controller against known sequences: hysteresis doesn't flap on a sawtooth around threshold; CUSUM fires on a step, not on noise; AIMD backs off on breach and ramps on sustained headroom; RetryController exhausts exactly 2 attempts then falls through; store prunes by age+count and reloads from JSONL.
- **Property-based controller simulation (the addition)** — the controllers/conditioners are pure, so their stability properties are **searched, not hand-traced**, with `hypothesis` (new dev-dependency): generate arbitrary signal sequences (spikes, sawtooths, step shifts, empty windows) and assert the invariants hold for *all* of them, not just the traces we thought to write:
  - ALWAYS `cap ∈ [1, N]` and ≤ 1 move per control period (bounds + move-rate/anti-windup).
  - Hysteresis/persistence: no single-tick spike ever trips escalation ("don't freak out").
  - AIMD: sustained breach ⇒ decrease; sustained headroom ⇒ increase; no oscillation in the dead-band.
  - `RetryController`: ≤ 2 attempts and always terminates on any fault interleaving.
  - Fail-safe: empty/corrupt history ⇒ conservative default action.
  `hypothesis` finding a counterexample yields a minimal reproducing sequence — stability is validated **before** anything touches the live fleet.
- **MockWorld scenario** — oversubscription drives truncations up → assert governor throttles `max_workers` then recovers; RC scenario with flaky-then-green CI → assert RC self-heals within cadence instead of closing.
- **Sandbox e2e** — governor + "Controllers" panel wired end-to-end (load-bearing + dashboard-touching → earns the top layer per the testing standard).
- **System-level fault injection (out of scope here; separate spike + ADR)** — `hypothesis` searches *inputs* to pure units but cannot exercise concurrency/timing/fault schedules across the integrated factory. A deterministic-simulation platform (e.g. Antithesis, riding the existing `docker-compose.sandbox.yml` air-gap) is the right tool for the closed-loop system properties — governor recovery under whole-fleet load, `RetryController` under injected CI/GitHub faults, and label-state-machine race invariants (no double-build, no double-merge). Tracked as its own spike because it is a cross-cutting *testing-infrastructure* decision (cost, CI wiring, whole-system) broader than this control layer.

---

## Rollout / sequencing (for the implementation plan)

1. **Substrate** — `store.py` + `conditioners.py` + `controllers.py` (pure, fully unit + simulation tested) with no integration. Zero behavior change.
2. **RC-merge resilience** — wrap `StagingPromotionLoop` fix cycle in `RetryController` (§5). Self-contained, high-value, low blast radius; kill-switch `HYDRAFLOW_RC_FIX_RETRY_DISABLED`.
3. **Concurrency governor** — `governor.py` + orchestrator `max_workers` actuator (§2) behind `HYDRAFLOW_CONCURRENCY_GOVERNOR_DISABLED`, default-conservative.
4. **Detector conditioning (trust fleet + credit)** — migrate the 5 trust-fleet detectors + credit handler to composed conditioner chains (§3) behind `..._ADAPTIVE_THRESHOLDS_DISABLED`.
   - **4b. Follow-on adopters** — one small PR each onto the landed toolkit, same kill-switch discipline: `flake_tracker_loop` (quarantine hysteresis + persistence), `health_monitor_loop`/`factory_health` (wedge/staleness CUSUM + corroboration), `triage_retry_loop` (`RetryController` + circuit-breaker). Not required for §1–§4 to ship; sequenced after the toolkit and detector migration prove out.
5. **Observability** — `/api/control/governors` + dashboard "Controllers" panel (§6); ADR + wiki + UL terms.

Each stage is independently shippable and gated; nothing changes live behavior until its kill-switch defaults flip on.

## Open questions for planning

- Exact control period and default `α` / band / `β` — start conservative, tune from the Controllers panel once telemetry exists.
- `N` (max concurrency) source — reuse `config.max_workers` as the upper bound the governor multiplies within.
- Whether stage 4 migrates all trust-fleet detectors at once or one detector per PR (leaning one-per-PR for reviewability).
- Whether the 4b follow-on adopters each get their own kill-switch or share `..._ADAPTIVE_THRESHOLDS_DISABLED` (leaning per-loop switches for independent rollback).
