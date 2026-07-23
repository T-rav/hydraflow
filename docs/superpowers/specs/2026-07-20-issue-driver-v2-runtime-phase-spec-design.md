# IssueDriver v2 Runtime — Phase Spec (Scheduling Model as a Selectable Strategy)

**Date:** 2026-07-20
**Status:** Design (accepted anchor: ADR-0099)
**Issue:** #10038 (companion to #10037 / #10045 — work-queue discipline as a selectable strategy)
**Scope:** The runtime phase spec that [ADR-0099](../../adr/0099-orchestration-as-a-control-system.md) assumes but never got. ADR-0099 references v2 phases P2–P5 (`DriverManager`, `SchedulingPolicy`, `Governor`, `PolicyScorecard`, the P5 anchor cutover) as though specified elsewhere; they were not. This document is that specification. It defines the **scheduling model** as a selectable strategy — `phase_requeue` (today's implicit start-stop) vs `issue_controller` (the v2 servo) — and, crucially, states as a **design constraint** (not a late discovery) how `issue_controller` is built without weakening ADR-0002's crash-safety guarantee.
**Related:**
- [ADR-0099](../../adr/0099-orchestration-as-a-control-system.md) — Orchestration as a Control System (the conceptual anchor this realizes; the Servo / `SchedulingPolicy` / `DriverManager` / `Governor` / `PolicyScorecard` roles)
- [ADR-0002](../../adr/0002-labels-as-state-machine.md) — GitHub Labels as the Pipeline State Machine (the crash-safety guarantee this must preserve)
- [ADR-0094](../../adr/0094-two-level-convergence-gate-and-ledger.md) — `ConvergenceLedger` + `HybridGate` (the servo's error register + inner controller)
- #10037 / #10045 — `queue_strategy` (the companion axis; scheduling ⟂ queuing)
- `src/state/_driver.py:DriverStateMixin`, `src/models.py:ConvergenceLedger`, `src/models.py:SuspendRecord`, `src/models.py:PolicyEvent` — the per-issue driver state layer already landed (this spec's P1)

---

## 1. Problem & Goal

Queuing decides *what to pick next*. Scheduling decides *how a picked item is executed*. HydraFlow has exactly one scheduling model, it is implicit, and it is not selectable.

**Today — phase-requeue ("start-stop").** An issue is pulled by a phase, worked, relabelled on GitHub, and released back into the queue; the next phase re-acquires it independently. Mechanically:

- Six phase loops (`src/orchestrator.py`) never query GitHub directly; they pull from six in-memory deques.
- The single poller `src/issue_store.py:IssueStore.refresh` repopulates them every `data_poll_interval` (default 300s).
- `src/issue_store.py:IssueStore.enqueue_transition` is the eager path, but appends the promoted task to the **back** of the next stage's deque — a plan→ready issue lands behind every older ready issue.
- Each phase spawns a fresh agent subprocess; no context carries across, it is re-derived from GitHub + state files every hop.

Costs: inter-phase dead time (up to `data_poll_interval` per hop on the non-eager path, six hops per issue); no finish-what-you-start pressure (concurrency is workers-per-phase — `max_workers` / `max_planners` / `max_reviewers` / `max_triagers`, all default 1 — not issues-in-flight, so WIP accumulates instead of draining); context re-derivation paid six times per issue.

**Goal.** Make the scheduling model a first-class, selectable strategy on the orchestrator / phase-loop layer — the same "producer without a consumer → selectable discipline" move #10037 made for queuing — with today's behaviour as the migration default, and the alternative (`issue_controller`) fully specified so its build is turnkey and its ADR-0002 tension is resolved up front rather than discovered late.

**This ticket is the design, not the build.** Per #10038 the runtime is implemented in the phases below, after this spec and ADR-0099's acceptance. No `scheduling_model` knob or `issue_controller` runtime ships in the spec PR itself.

## 2. Position in the control-system model (ADR-0099)

ADR-0099 already names every role this spec fills; this section binds them to concrete v2 symbols so the phases below are designed against one decomposition:

| ADR-0099 role | v2 realization (this spec) | Landed today |
|---|---|---|
| **Plant** | the issue's lifecycle; durable state on `ConvergenceLedger` | `ConvergenceLedger` (state layer) |
| **Servo** | `IssueDriver` — drives one issue `driver_state` → `MERGED` | `DriverStateMixin` accessors (P1) |
| **Inner controller** | `HybridGate` (ADR-0094) — per-issue convergence gate | `src/convergence_gate.py:HybridGate` |
| **Error / state register** | `ConvergenceLedger` (`laps`, `route_backs`, `stage_state`) | landed |
| **Supervisory controller** | `SchedulingPolicy.select` over a frozen `SchedulingView` | — (P2) |
| **Capacity allocator** | `DriverManager` — N servos, WIP-limited | — (P2) |
| **Governor** | saturation limits + interlocks under the allocator | `max_*` semaphores, credit holds, kill switches (P3 formalizes) |
| **System identification** | `PolicyScorecard` + `ReplayDriverManager` (offline) | — (P4) |

The scheduling model *is* the `Servo` + `Supervisory controller` pair. `phase_requeue` is the degenerate case where the supervisory controller is FIFO-by-label (`IssueStore`) and there is no servo — each phase re-acquires from the queue. `issue_controller` is the case where a `DriverManager` allocates capacity to `IssueDriver` servos that each own an issue across phases.

## 3. The two scheduling models

### 3.1 `phase_requeue` (today; remains the default until `issue_controller` is proven)

Keep exactly as-is. Its virtues are load-bearing and the alternative must not silently discard them (Section 5): every phase boundary is a GitHub label write, so state lives entirely in labels; a crash at any point is fully recoverable from labels alone; per-phase worker caps throttle the expensive stages; a P0 arriving mid-pipeline is picked up at the next phase boundary because no worker holds an issue across phases.

### 3.2 `issue_controller` (the v2 servo — the variant this spec designs)

One `IssueDriver` task per in-flight issue, owning that issue from `TRIAGE` through `MERGED`, **swapping sub-processes per phase** rather than releasing the issue back into a queue between phases.

- Inter-phase latency collapses from up to `data_poll_interval` to process-swap time.
- Concurrency becomes a **WIP limit** — N issues in flight, each driven to completion — which is the finish-what-you-start behaviour `phase_requeue` cannot express.
- A single issue's timeline is one traceable unit (its `policy_log`) rather than six disjoint acquisitions.

Capacity is allocated by `DriverManager`: it holds ≤ `max_in_flight` live `IssueDriver`s, admits a new issue only when a slot frees and `SchedulingPolicy.select` (the supervisory controller, over a frozen `SchedulingView`) picks it, and never lets more than `max_workers` drivers occupy the implement stage at once (Section 5.4).

## 4. The IssueDriver state machine

The per-issue state layer is **already in the tree** (this spec's P1) and the state machine below uses it unchanged:

- `src/models.py:DriverState` — the 13-state literal: `TRIAGE`, `DISCOVER`, `SHAPE`, `PLAN`, `READY`, `REVIEW`, `HITL_WAIT`, `HITL_APPLY`, `DIAGNOSE`, `PARKED`, `MERGED`, `CLOSED`, `ESCALATED`.
- `src/models.py:ConvergenceLedger` — carries `driver_state`, `suspend`, `pending_correction`, `hitl_origin`, `hitl_cause`, `route_backs`, `issue_attempts`, `policy_log`.
- `src/models.py:SuspendRecord` — `reason` / `suspended_at` / `wake_signal` (`comment` | `correction` | `label`) / `resume_state`: the defined resume path (Section 5.2).
- `src/models.py:PolicyEvent` — one recorded `from_state`→`to_state` decision, appended to `policy_log` for audit/replay (feeds P4).
- `src/state/_driver.py:DriverStateMixin` — the read-modify-write-then-`save()` accessors (`get_driver_state`, `set_driver_state`, `suspend_driver`, `clear_suspend`, `set/take_pending_correction`) the driver runtime calls on every transition.

**Transition map (nominal path):** `TRIAGE → DISCOVER → SHAPE → PLAN → READY → REVIEW → MERGED`. Off-nominal edges: `REVIEW → DIAGNOSE` (CI red / route-back) → back to `READY`; any state `→ HITL_WAIT` (escalation) → `HITL_APPLY` (operator correction applied) → resume at `resume_state`; `→ PARKED` (suspended on a barrier: `ci_wait`, `epic_gap_barrier`, `shape_human_select`); `→ ESCALATED` / `CLOSED` (terminal). Each edge is a `PolicyEvent` and — the crux — a GitHub label write (Section 5).

**One-to-one with ADR-0002 labels.** Every `driver_state` that corresponds to a pipeline stage maps to exactly one pipeline label, so the driver's in-memory state is always a cache of the label, never a second source of truth. `DIAGNOSE`/`HITL_APPLY`/`PARKED` are sub-states of an existing labelled stage (they resolve back to `hydraflow-review` / `hydraflow-hitl` / the parked stage's label), not new pipeline labels — so the label set (`config.all_pipeline_labels`) does not change and no ADR-0002 label-set test moves.

## 5. The ADR-0002 crash-safety resolution (the crux — stated as a constraint, not discovered late)

`issue_controller` is in direct tension with ADR-0002, which makes GitHub labels the **sole** source of truth so the factory is crash-safe: kill the process anywhere and the labels tell the next boot exactly where every issue stands. A controller that holds an issue across phases holds in-memory state that a crash could strand with no external record. #10038 names the intended resolution; this spec **mandates** it:

> **Constraint C1 (label-at-every-boundary).** An `IssueDriver` MUST write the GitHub pipeline label via `src/pr_manager.py:swap_pipeline_labels` at every `driver_state` transition that crosses a pipeline-stage boundary, **before** spawning the next phase's sub-process. The in-memory `driver_state` is a cache of the label, never a substitute for it. Consequence: `issue_controller` is an **execution-model change only** — it changes *when* the next phase starts (process-swap vs re-poll), not *where truth lives*. **ADR-0002 survives intact.**

The four risks #10038 raises are each bounded by a constraint:

### 5.1 State ownership
Bounded by C1: labels remain the sole source of truth; `driver_state` / `ConvergenceLedger` are a durable *cache + audit log* (already persisted via `DriverStateMixin.save`), reconciled *from* labels on boot, never diverging as a competing authority.

### 5.2 Recovery
**Constraint C2 (resume-from-labels).** On boot, `DriverManager` reconstructs in-flight `IssueDriver`s from GitHub labels (the ADR-0002 re-poll), then hydrates each from its `ConvergenceLedger`: if a `SuspendRecord` is present the driver resumes at `resume_state` on its `wake_signal`; otherwise it resumes at the state implied by the current label. A driver that died mid-phase is re-derived exactly as `phase_requeue` re-derives today — the label says which stage, the sub-process is simply respawned. No in-memory-only state gates recovery. This is why `SuspendRecord` exists in the landed state layer: the intended answer is a **resumable** driver, not an in-memory-only one.

### 5.3 Preemption
**Constraint C3 (preempt at phase boundaries only).** A driver is preemptible only at a `driver_state` boundary (where C1 has just written the label, so yielding is free and crash-safe). Between boundaries a sub-process runs to completion or times out — the same granularity `phase_requeue` offers today. A P0 admitted by `SchedulingPolicy` while all slots are full waits for the next boundary of the lowest-priority in-flight issue, at which point that driver either yields its slot (state persisted, re-admitted later) or is allowed to finish, per policy. Mid-sub-process preemption is **not offered** in v2 (it would require killing an agent mid-work, losing the partial); this is an explicit non-goal, revisited only if starvation data justifies it (ADR-0099 known-open surface #2, the anti-starvation term).

### 5.4 Backpressure
**Constraint C4 (stage-aware WIP caps).** `DriverManager` enforces two limits: a global `max_in_flight` (total live drivers) and a per-expensive-stage cap that reuses today's semantics — no more than `max_workers` drivers in the implement stage, `max_reviewers` in review, etc. A WIP-limited model must not let N drivers pile into implement simultaneously; C4 makes the existing per-phase caps a property the allocator respects, not a throttle the model removes.

**Net:** with C1–C4, `issue_controller` preserves every virtue of `phase_requeue` (crash-safety, throttling, preemptability at boundaries) while collapsing inter-phase latency and expressing WIP. That outcome — ADR-0002 intact — is the **design target and acceptance bar**, not a hoped-for side effect.

## 6. The `scheduling_model` knob (config surface — specified here, built in P2)

Mirrors the `queue_strategy` wiring exactly (#10037), so scheduling and queuing are selected independently and identically:

- `src/scheduling_model.py:SchedulingModel(StrEnum)` — `PHASE_REQUEUE = "phase_requeue"`, `ISSUE_CONTROLLER = "issue_controller"` (parallel to `src/queue_strategy.py:QueueStrategy`).
- Triple-registered like `queue_strategy`: a `HydraFlowConfig` `Field(default=SchedulingModel.PHASE_REQUEUE, ...)`; a byte-equal `_ENV_*` default tuple (`("scheduling_model", "HYDRAFLOW_SCHEDULING_MODEL", SchedulingModel)`); a `src/settings_registry.py` `SettingSpec("Scheduling Model", live=..., order=...)` entry.
- **Migration default = `phase_requeue`** — zero behaviour change on merge, exactly as `queue_strategy` defaulted to `fifo`. The factory keeps start-stop scheduling until an operator flips the dial; flipping the default is a separate, factory-wide-blast-radius decision, not smuggled into the build PR.
- **Fail-loud on an unhandled member** — the `queue_strategy` follow-up (#10053) added a guard that raises rather than silently dispatching an unknown strategy as a default branch; the `scheduling_model` dispatcher MUST ship that guard from day one (a scheduler that silently picks the wrong discipline is the dangerous shape).

## 7. Composition with `queue_strategy` (the two axes are orthogonal)

Any queuing discipline composes with any scheduling model. `queue_strategy` decides *which issue `SchedulingPolicy.select` considers next*; `scheduling_model` decides *how the selected issue is executed*. Concretely, under `issue_controller` the `SchedulingPolicy` (supervisory controller) draws its candidate order from the same `queue_strategy` engine `IssueStore` uses today — the band-draw/priority/FIFO logic in `src/queue_strategy.py` is reused, not reimplemented. The two knobs are registered, defaulted, and flipped independently; no combination is disallowed.

## 8. Phase plan

| Phase | Deliverable | ADR-0099 role | Status |
|---|---|---|---|
| **P1** | Per-issue driver state layer (`DriverState`, `ConvergenceLedger` driver fields, `SuspendRecord`, `PolicyEvent`, `DriverStateMixin`) | Plant / error register | **Landed** (this spec documents it; no new code) |
| **P2** | `IssueDriver` servo + `DriverManager` + `SchedulingPolicy.select(SchedulingView)`; the `scheduling_model` knob (Section 6) with `phase_requeue` default; C1–C4 enforced | Servo + supervisory controller | Follows this spec |
| **P3** | `Governor` — saturation limits + interlocks (kill switches per ADR-0049, credit holds) formalized beneath the allocator | Governor | P2+ |
| **P4** | `PolicyScorecard` + `ReplayDriverManager` — offline scoring of control laws over recorded `policy_log`s (system identification); auto-tuner deliberately deferred | System identification | P3+ |
| **P5** | Anchor cutover — re-point ADR-0099's representative glossary anchors to the v2 symbols (Plant→`IssueDriver`, Sensor→`SchedulingView`, Controller→`SchedulingPolicy`/`HybridGate`, Governor→`Governor`); the ADR-0001 supersession ADR set | (all) | Last |

**v1 boundary for #10038:** this document (the spec) + ADR-0099 advanced from Proposed to Accepted (its conceptual model is now backed by a concrete phase spec) + the ADR-0002 resolution made explicit (Section 5). P2–P5 are separate build tickets that cite this spec.

## 9. Non-goals / deferred

- Mid-sub-process preemption (Section 5.3) — never in v2.
- The autonomous policy auto-tuner (ADR-0099's deferred-open adaptive loop) — the surface is built replay-ready in P4; closing the loop waits for offline A/B evidence.
- A continuous per-issue error magnitude and an anti-starvation integral term (ADR-0099 known-open surfaces #1, #2) — named, not decided here.
- Flipping the `scheduling_model` default to `issue_controller` — a separate factory-wide decision once P2 is proven.

## 10. Acceptance (for this spec / #10038)

1. This phase spec exists and specifies both scheduling models, the state machine over the landed driver layer, the phase plan P1–P5, the `scheduling_model` knob surface, and orthogonal composition with `queue_strategy`.
2. ADR-0099 is **Accepted** (was Proposed), with a resolvable, non-mutating `**Enforcement:** enforced` declaration — the ratchet (`tests/test_adr_conformance_coverage.py`) stays green.
3. The ADR-0002 crash-safety resolution is **explicit** (Section 5, constraints C1–C4): `issue_controller` is an execution-model change only and ADR-0002 survives intact.
4. No runtime behaviour changes on merge (design-only PR); regression pins in `tests/regressions/regression_issue_10038.py` guard the invariants above.
