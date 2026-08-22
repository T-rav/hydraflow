# IssueDriver v2 Runtime — Phase Spec (Scheduling Model as a Selectable Strategy)

**Date:** 2026-07-20 (topology realigned and constraints C5–C9 added 2026-08-22 by #11533)
**Status:** Design (accepted anchors: ADR-0099, ADR-0137)
**Issue:** #10038 (companion to #10037 / #10045 — work-queue discipline as a selectable strategy); realigned by #11533

> **Realignment note (2026-08-22, #11533).** As first written this spec described a
> 13-state `DriverState` including `DISCOVER` and `SHAPE`. [ADR-0107](../../adr/0107-collapse-discover-shape-into-plan.md)
> retired both as pipeline phases in July 2026 and `src/models.py:DriverState` has
> carried an 11-state literal without them ever since, so the spec was describing
> stages that no longer exist. Section 4 below now matches the live topology.
> Separately, the adversarial panel on #10038 falsified this document's headline
> crash-safety claim; constraints **C5–C9** and Sections 5.5–5.8 are the response,
> and [ADR-0137](../../adr/0137-fenced-issue-driver-and-director-runtime-boundary.md)
> is the ADR that narrows ADR-0094's prior rejection so this design may be built at all.
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

- `src/models.py:DriverState` — the **11-state** literal: `TRIAGE`, `PLAN`, `READY`, `REVIEW`, `HITL_WAIT`, `HITL_APPLY`, `DIAGNOSE`, `PARKED`, `MERGED`, `CLOSED`, `ESCALATED`. There is no `DISCOVER` and no `SHAPE`: ADR-0107 collapsed both into planner-invoked helpers behind the planner's own decision gate, so discovery research and direction shaping are synchronous in-process calls producing `research_context`, never stage handoffs. `src/discover_runner.py` and `src/shape_runner.py` survive as those helpers — their existence is not a stage.
- `src/models.py:ConvergenceLedger` — carries `driver_state`, `suspend`, `pending_correction`, `hitl_origin`, `hitl_cause`, `route_backs`, `issue_attempts`, `policy_log`.
- `src/models.py:SuspendRecord` — `reason` / `suspended_at` / `wake_signal` (`comment` | `correction` | `label`) / `resume_state`: the defined resume path (Section 5.2).
- `src/models.py:PolicyEvent` — one recorded `from_state`→`to_state` decision, appended to `policy_log` for audit/replay (feeds P4).
- `src/state/_driver.py:DriverStateMixin` — the read-modify-write-then-`save()` accessors (`get_driver_state`, `set_driver_state`, `suspend_driver`, `clear_suspend`, `set/take_pending_correction`) the driver runtime calls on every transition.

**Transition map (nominal path):** `TRIAGE → PLAN → READY → REVIEW → MERGED`, which is the live Triage → Plan → Implement → Review → HITL topology (`READY` is the implement stage; `hydraflow-ready` is its label). Off-nominal edges: `REVIEW → DIAGNOSE` (CI red / route-back) → back to `READY`; any state `→ HITL_WAIT` (escalation) → `HITL_APPLY` (operator correction applied) → resume at `resume_state`; `→ PARKED` (suspended on a barrier: `ci_wait`, `epic_gap_barrier`); `→ ESCALATED` / `CLOSED` (terminal). Each edge is a `PolicyEvent` and — the crux — a GitHub label write (Section 5).

The stage labels each nominal state maps to are `hydraflow-find` (TRIAGE), `hydraflow-plan` (PLAN), `hydraflow-ready` (READY), `hydraflow-review` (REVIEW), `hydraflow-hitl` (HITL_WAIT / HITL_APPLY). `DISCOVER` and `SHAPE` appear nowhere in this map, and re-introducing them to `DriverState`, to this map, or to the driver-phase enum is pinned against by `tests/regressions/test_issue_11533_stale_driver_states.py`.

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

### 5.5 Reconcile-from-recorded-intent (Constraint C5) — the falsified premise, repaired

**C1 alone does not deliver "a single unambiguous current label."** `src/pr_manager.py:PRManager.swap_pipeline_labels` adds the new label first and then removes stale ones best-effort, so a crash mid-swap leaves an issue carrying **two** pipeline labels. The spec as first written asserted the guarantee the primitive does not provide.

**Constraint C5 (reconcile-from-recorded-intent).** Three rules, all mandatory:

1. **Reconciliation is direction-aware.** Priority-based most-advanced-label-wins (`src/issue_store.py:IssueStore._compute_stage_map`, `_STAGE_PRIORITY`) is correct **only for forward transitions**. `swap_pipeline_labels` is direction-agnostic, and this pipeline's crash-interesting edges are backward: a `DIAGNOSE → READY` route-back crashing mid-swap leaves `hydraflow-review` (5) beside `hydraflow-ready` (4) and most-advanced-wins **silently undoes the route-back**; a `HITL_APPLY → READY` resume leaves `hydraflow-hitl` (6) beside `hydraflow-ready` (4) and **silently reverts the resume**. So the driver persists a `pending_stage_transition` record (`from_label`, `to_label`, `epoch`, `phase_attempt`) to the `ConvergenceLedger` **before** every swap, and reconciles like this:
   A record is **usable** only when its `epoch` is the one being recovered and its `phase_attempt` matches the ledger's; anything older is stale and ignored. Then:
   - **one pipeline label** → that label is the truth; clear any pending *stage* record. A pending **sub-state** record (C9) is not cleared here — those transitions run with one pipeline label and the record is their commit. Stage and sub-state records occupy separate slots;
   - **two or more labels, a usable record whose `to_label` is present, and every other present label is its `from_label`** → the recorded `to_label` wins **regardless of direction**; remove the `from_label` and clear the record;
   - **two or more labels including one outside `{from_label, to_label}`** → external drift, not an interrupted swap. The driver **must not** remove it: it abandons the transition, adopts the externally-set label, and escalates (same preemption rule as rule 2 below);
   - **two or more labels and no usable record** → fall back to `_STAGE_PRIORITY` most-advanced-wins. This path is unreachable via a driver crash (the record precedes the label add) and exists only for drift the driver did not cause.

   Because the record is written before the label add, every crash inside the non-atomic window falls into case 2. A crash *between* the record and the add — or an add that fails rather than crashes — leaves one label, so case 1 discards the intent and the driver retries under C6; no stale intent survives. The record is consumed and cleared by the first reconciliation that observes it, so it can never be more than one incarnation stale, which is what makes it safe to honour a record written under the epoch recovery has just fenced. `IssueStore`'s behaviour for non-driver issues is unchanged.
2. **The label is re-read at every phase boundary,** and an externally changed label **preempts** the driver's own state. ADR-0002 documents "drag a label" as the HITL escape hatch; without this rule the next C1 write silently clobbers the operator's edit. `src/driver_contracts.py:admit_dispatch` returns `LIVE_LABEL_CHANGED` for this case.
3. **DIAGNOSE ambiguity is resolved by rule.** DIAGNOSE shares `hydraflow-review` and is not a suspend transition, so no `SuspendRecord` is written and a crash mid-DIAGNOSE is indistinguishable from a fresh REVIEW by label alone. The rule: **resume at the nominal state and re-detect the route-back fresh.** Two things make that safe, and neither is "the detector is pure":
   - An interrupted DIAGNOSE may already have pushed a commit and retriggered CI, **mutating the detector's own inputs**. Re-running a pure function over mutated inputs is not idempotent in effect. What makes re-detection safe is that it **converges on current reality** — it reads the PR's present CI state and diff and re-decides, so a fix that landed before the crash is seen as green and one that did not is seen as red.
   - `increment_route_backs` feeds ADR-0094's lap budget, so a crash around it double-counts or loses a lap. The increment is ordered **inside C8's ledger write under the same `pending_stage_transition` record** and applied exactly once per recorded transition; the record's `phase_attempt` makes a replayed increment detectable and refused.

### 5.6 Capacity release for non-working drivers (Constraint C6)

**Constraint C6.** A driver in `PARKED` or `HITL_WAIT`, or one failing its C1 label write, **releases** its `max_in_flight` slot. Holding it would let one slow human starve total factory capacity — a failure mode `phase_requeue` structurally cannot have. Releasing does not undercut the model: its benefit is inter-phase latency *within one issue's lifecycle*, which is a different quantity from admission latency for a parked issue.

- A driver blocked on a congested phase semaphore **does** count against admission — it is working, merely queued.
- Label-write failure gets a bounded retry: 5 attempts with exponential backoff and a **10-minute maximum slot hold**, then escalate to HITL and release. Without this bound a retrying driver holds its slot indefinitely — a livelock class unique to `issue_controller`.
- Re-admission keys on the driver's original enqueue time, so a released driver is never starved by newer arrivals — **within its priority band only**, per the precedence in Section 5.7; otherwise this rule would outrank an arriving P0 and contradict the wait bound.

### 5.7 SchedulingPolicy / SchedulingView, and the P0 wait bound (Constraint C3, completed)

`SchedulingView` is a **frozen** per-issue sensor record — no I/O, replay-testable, the same pure-engine shape as `src/queue_strategy.py`:

| Field | Meaning |
|---|---|
| `issue_number` | identity |
| `priority` | P0–P3 band |
| `blast_radius` | low / medium / high (reused from ADR-0051, not re-derived) |
| `driver_state` | current `DriverState` |
| `waiting_since` | when admission was first requested (the anti-starvation key) |
| `stage` | current pipeline stage |
| `slot_occupancy` | global and per-stage occupancy at view time |

`SchedulingPolicy.select(view) -> ranked candidates` is the control law over that view. Candidate ordering is drawn from the existing `queue_strategy` engine rather than reimplemented.

**Worst-case P0 wait is bounded, with a precedence and a number.** Three ordering rules exist and must be ranked or the bound is not derivable: C6's anti-starvation rule keys re-admission on original enqueue time, Section 7 draws candidate order from the `queue_strategy` engine, and a P0 is by construction the *newest* arrival. **Precedence, highest first: (1) priority band, (2) original enqueue time within a band, (3) `queue_strategy` ordering within that** — so anti-starvation operates *within* a band and never lets a released P3 outrank an arriving P0.

With that ranking, a P0 arriving with all slots full waits at most `one phase-boundary interval of the longest-running in-flight phase + C6's maximum slot hold`. Both terms are concrete: `agent_timeout` defaults to **3600 s** and C6's label-write hold is **600 s**, so the stated worst case is **70 minutes**. That number is deliberately bad and naming it is the point — if it is unacceptable the fix is a lower `agent_timeout` for driver-held phases or genuine boundary preemption, decided on evidence rather than discovered in production. The canary must report the measured distribution against this ceiling. Mid-sub-process preemption stays a non-goal (Section 5.3); the bound is what makes that non-goal acceptable.

### 5.7b Fenced admission (Constraint C7)

**Constraint C7.** Every worker dispatch passes `src/driver_contracts.py:admit_dispatch` before anything is launched. It is a pure function over a fixed snapshot returning a deterministic `RejectionReason` or `None`, evaluated in a fixed order — global stop fences, then driver identity and epoch fencing, then lease expiry and live-label coherence, then catalog legality, then capacity and budget. The first matching reason wins, so the same inputs always produce the same reason and shadow-mode comparisons are meaningful across runs.

Two properties matter for recovery. Driver identity is fenced: a request or writer lease belonging to **another driver** is refused with `DRIVER_IDENTITY_MISMATCH`, while a *stale epoch* is reported distinctly — `STALE_EPOCH` for the request, `LEASE_EXPIRED` for a writer lease that has not been re-minted — because a lagging fence is not ownership theft and must not inflate the theft count in Section 8a's bar. Writer-lease checks apply only to roles holding `issue_worktree` write scope, so a read-only explorer is never blocked by a lease it would never take. And `sandbox_verified` and `allowed_roles` are **required** arguments with no defaults, so a caller that forgets to thread ADR-0137's S4 result or the capsule allow-list fails loudly rather than dispatching fail-open.

### 5.8 Boundary transaction ordering (Constraints C8 and C9)

**Constraint C8.** For every phase, in exactly this order:

1. validate the worker's output and canonical side effects;
2. persist the bounded artifact/result under an **idempotency key**;
3. record the `pending_stage_transition` intent (C5);
4. compare the expected live stage and **swap the label — this is the durable commit**;
5. append the driver checkpoint/audit record and clear the intent;
6. only then admit the next dispatch.

**Constraint C9 (sub-state transitions commit in the ledger).** `DIAGNOSE`, `HITL_APPLY`, and `PARKED` are sub-states of an already-labelled stage (Section 4), so they write **no label** and step 4 does not exist for them. Their durable commit is a `pending_sub_state_transition` record — a **separate slot** from the stage record, written with the sub-state as `to_label` and cleared on completion. The separation is load-bearing: C5 rule 1 clears the *stage* record whenever exactly one pipeline label is present, which is the normal condition for a sub-state transition, so a shared slot would delete the very commit this constraint creates. Without C9 a crash between `take_pending_correction` and the applied correction loses the correction with no commit record — a blind spot C8 alone cannot cover.

A crash before step 4 safely replays the idempotent step 2 — the transition never committed, and C5 rule 1 discards the intent. A crash *inside* step 4 is resolved by C5 rule 2 from the recorded intent. A crash after step 4 recovers from label truth even if the audit cache lags. This ordering is what prevents a `ConvergenceLedger` `driver_state`/`policy_log` write that raced ahead of the label write from corrupting P4's replay with a phantom transition. **The behavioural test P2b must ship** is a kill-mid-transition test that kills the process between steps 3 and 4 (intent recorded, label not yet swapped) and again between steps 4 and 5 (label swapped, checkpoint not yet appended), asserting correct recovery in both cases. It MUST cover the two **backward** edges C5 exists for — a route-back `REVIEW → READY` and a HITL resume `HITL → READY` — since a test exercising only forward transitions would pass against the wrong reconciliation rule. A test that string-matches spec phrases cannot test this.

**Net:** with C1–C9, `issue_controller` preserves every virtue of `phase_requeue` (crash-safety, throttling, preemptability at boundaries) while collapsing inter-phase latency and expressing WIP. That outcome — ADR-0002 intact — is the **design target and acceptance bar**, not a hoped-for side effect.

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
| **P2a** | `DriverManager` + the `scheduling_model` knob (Section 6), delegating to the existing `phase_requeue` path — behaviour-neutral, replay-testable | Capacity allocator | Follows this spec |
| **P2b** | `IssueDriver` subprocess swap behind the flag; C1–C2, C5, C7–C9 enforced; ships with the kill-mid-transition test (Section 5.8) | Servo | After P2a |
| **P2c** | Real `SchedulingPolicy.select(SchedulingView)` + C3/C4/C6 backpressure and preemption | Supervisory controller | After P2b |
| **P3** | `Governor` — saturation limits + interlocks (kill switches per ADR-0049, credit holds) formalized beneath the allocator | Governor | P2+ |
| **P4** | `PolicyScorecard` + `ReplayDriverManager` — offline scoring of control laws over recorded `policy_log`s (system identification); auto-tuner deliberately deferred | System identification | P3+ |
| **P5** | Anchor cutover — re-point ADR-0099's representative glossary anchors to the v2 symbols (Plant→`IssueDriver`, Sensor→`SchedulingView`, Controller→`SchedulingPolicy`/`HybridGate`, Governor→`Governor`); the ADR-0001 supersession ADR set | (all) | Last |

**v1 boundary for #10038:** this document (the spec) + ADR-0099 advanced from Proposed to Accepted (its conceptual model is now backed by a concrete phase spec) + the ADR-0002 resolution made explicit (Section 5). P2–P5 are separate build tickets that cite this spec.

## 8a. The quantitative "proven" bar (and the anti-pattern it guards against)

"`phase_requeue` remains the default until `issue_controller` is proven" is meaningless without a bar. The companion axis ran this experiment with no restraint: `queue_strategy` went build (#10045, merged 05:19Z) → guard (#10053, 14:33Z) → **default flip** (#10061, 18:13Z) in one calendar day, justified only as "that left the feature inert." **That timeline is the named anti-pattern.**

To advance beyond shadow mode, all of the following must hold over a measured window of **at least 20 completed issues and at least 7 days**:

- zero duplicate dispatches, zero ownership-theft events, zero post-stop spawns;
- 100% of accepted workers carry lineage, cost, and effective-route receipts;
- zero label-desync incidents (label and committed checkpoint disagreeing after a settled window);
- no increase in orphan process groups versus the classic baseline;
- terminal success rate and escaped-defect rate no worse than the **`phase_requeue` (classic) baseline** over a comparable window — the thing being gated is `issue_controller`, so comparing it to itself would be vacuous;
- p95 worker-decision latency and parent cost bounded and reported;
- successful fresh reconstruction on every resume failure;
- the measured worst-case P0 wait (Section 5.7) reported against its stated bound.

The eventual flip PR **must cite this evidence explicitly**. A default flip in the same calendar day as the build PR is forbidden regardless of the numbers.

## 8b. Alternatives considered

Neither cheaper design was evaluated in the original spec, which left "is a controller the right abstraction" unexamined.

- **(a) Fix `enqueue_transition`'s back-of-queue insertion.** The eager path already exists; a promoted issue merely lands behind every older same-stage issue. Fixing that ordering removes most of the "up to `data_poll_interval` per hop" latency this spec's Section 1 leads with — the residual is a queue-ordering bug, not a full-poll-interval problem. **Complementary, not a substitute**: it produces no single traceable per-issue timeline and cannot express in-flight WIP. It should be fixed on its own merits regardless of this spec.
- **(b) A stateless WIP-admission cap at Triage**, recomputed from label counts on boot with no in-memory ownership. Delivers finish-what-you-start without touching ADR-0002 at all, and is genuinely cheaper. Delivers neither per-issue continuity nor adaptive delegation.

**The controller's unique deliverables are exactly two:** a single traceable per-issue timeline, and in-flight WIP as a first-class quantity. Those justify the servo/allocator stack over (a) and (b); nothing else in the original justification does.

**Withdrawn from the justification:** the "context re-derivation paid six times per issue" cost claimed in Section 1. `issue_controller` still swaps sub-processes per phase, so it does **not** address that cost. Leaving it in inflated the ROI.

## 9. Non-goals / deferred

- Mid-sub-process preemption (Section 5.3) — never in v2.
- The autonomous policy auto-tuner (ADR-0099's deferred-open adaptive loop) — the surface is built replay-ready in P4; closing the loop waits for offline A/B evidence.
- A continuous per-issue error magnitude and an anti-starvation integral term (ADR-0099 known-open surfaces #1, #2) — named, not decided here.
- Flipping the `scheduling_model` default to `issue_controller` — a separate factory-wide decision once P2 is proven.

## 10. Acceptance (for this spec / #10038)

1. This phase spec exists and specifies both scheduling models, the state machine over the landed driver layer, the phase plan P1–P5, the `scheduling_model` knob surface, and orthogonal composition with `queue_strategy`.
2. ADR-0099 is **Accepted** (was Proposed), with a resolvable, non-mutating `**Enforcement:** enforced` declaration — the ratchet (`tests/test_adr_conformance_coverage.py`) stays green.
3. The ADR-0002 crash-safety resolution is **explicit** (Section 5, constraints C1–C9): `issue_controller` is an execution-model change only and ADR-0002 survives intact. C5–C9 are load-bearing, not optional hardening — C1–C4 alone rest on a false atomicity premise, and priority-only reconciliation rests on a false monotonicity premise (Section 5.5).
4. The transition map (Section 4) matches the live 11-state `DriverState` and carries no `DISCOVER`/`SHAPE`, pinned by `tests/regressions/test_issue_11533_stale_driver_states.py`.
5. ADR-0137 is Accepted, narrowing ADR-0094's blocking-shepherd rejection, before any P2 runtime code merges.
6. No runtime behaviour changes on merge (design-only PR). `tests/regressions/regression_issue_10038.py` pins the document-level invariants only — it string-matches spec prose and **cannot** test crash-safety behaviour; the behavioural guard is P2b's kill-mid-transition test (Section 5.8).
