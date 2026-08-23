# ADR-0137: Fenced IssueDriver and director runtime boundary

**Status:** Accepted
**Date:** 2026-08-22
**Enforcement:** enforced
**Binds:** factory
**Supersedes:** none
**Superseded by:** none
**Amends:** ADR-0094 (Two-level convergence: Gate + ConvergenceLedger) — narrows its blocking-shepherd rejection to the convergence *outer loop*, leaving every other decision in ADR-0094 intact.
**Related:** [ADR-0001](0001-five-concurrent-async-loops.md) (the concurrency model a driver must not break), [ADR-0002](0002-labels-as-state-machine.md) (labels as the sole durable stage truth), [ADR-0099](0099-orchestration-as-a-control-system.md) (the servo/supervisory-controller vocabulary this realizes), [ADR-0107](0107-collapse-discover-shape-into-plan.md) (the live Triage → Plan → Implement → Review → HITL topology), [ADR-0110](0110-provider-harness-backend-split.md) and [ADR-0134](0134-per-repo-model-harness-selection.md) (per-repo provider routing the broker must resolve per child), [ADR-0124](0124-tier-2-goal-supervisor.md) (the default-off Fable goal supervisor this is deliberately *not* built on). Issues: #11533 (this phase), #11532 (the epic), #10038 / #10055 (the conflict), #11535 / #11537 / #11541 / #11542 (the phases this unblocks).

**Enforced by:**
pytest:tests/test_driver_contracts.py
pytest:tests/test_director_capability_probe.py
pytest:tests/regressions/test_issue_11533_stale_driver_states.py
pytest:tests/test_issue_driver.py
pytest:tests/test_issue_driver_policy.py
pytest:tests/test_driver_manager.py
pytest:tests/test_scheduling_default_off.py
pytest:tests/regressions/test_issue_11535_kill_mid_transition.py
pytest:tests/test_director_sandbox.py
pytest:tests/test_director_broker.py
pytest:tests/test_fable_director.py
pytest:tests/test_director_shadow_default_off.py
pytest:tests/test_director_turn_runner_env.py
pytest:tests/test_dashboard_routes_scheduling.py
pytest:tests/architecture/test_director_no_authority.py
pytest:tests/regressions/test_issue_11537_shadow_safety.py
pytest:tests/regressions/test_issue_11537_shadow_idle_spin.py
pytest:tests/test_plan_broker.py
pytest:tests/test_plan_worker_runner.py
pytest:tests/test_plan_canary_default_off.py
pytest:tests/regressions/test_issue_11541_outside_the_slice.py
pytest:tests/scenarios/test_fable_plan_canary_scenario.py
pytest:tests/test_implement_broker.py
pytest:tests/test_implement_worker_runner.py
pytest:tests/test_implement_canary_default_off.py
pytest:tests/regressions/test_issue_11542_outside_the_slice.py
pytest:tests/scenarios/test_fable_implement_canary_scenario.py

**Precedent:** Fenced leases over a durable log — the epoch/fencing-token discipline for a single-writer owner whose liveness cannot be trusted (Chubby, Burrows 2006; Kafka's producer epoch; Lamport's "the lease holder may already be dead").
**Divergence:** classical fencing assumes the shared store enforces the token, but HydraFlow's durable store is the GitHub label set, which has no compare-and-swap and whose swap primitive is add-first-then-best-effort-remove (`src/pr_manager.py:PRManager.swap_pipeline_labels`), so the fence is enforced at the *admission* boundary instead and multi-label crash states are reconciled against a transition intent recorded before the swap rather than prevented — priority-based reconciliation alone silently reverts backward transitions (receipt: #11533, and the adversarial panel on #10038).

## Context

Two Accepted documents disagree, and the disagreement has blocked every child of epic #11532.

**ADR-0094 rejected this design.** Its Alternatives section says, verbatim:

> **Blocking shepherd for the outer loop** (one worker walks an issue stage-to-stage in a single fixpoint). Rejected in favor of requeue + ledger to preserve the ADR-0001 concurrency model.

**#10055 shipped a spec for exactly that design.** `docs/superpowers/specs/2026-07-20-issue-driver-v2-runtime-phase-spec-design.md` specifies an `IssueDriver` that owns one issue from `TRIAGE` to `MERGED`, swapping sub-processes per phase. It cites ADR-0094 for `HybridGate` reuse and never engages the rejection.

An adversarial three-reviewer panel on #10038 found seven blocking defects (B1–B7 below) and returned *rework-before-implementing*. The repo rule is explicit: contradicting an Accepted ADR requires a new ADR, not a code change. Nothing may be built until that ADR exists — which is what this one is.

Two further facts made the conflict worse than a paperwork problem:

1. **The spec is stale.** It documents a 13-state `DriverState` including `DISCOVER` and `SHAPE`. ADR-0107 removed both as pipeline phases in July 2026; `src/models.py:DriverState` has carried an 11-state literal without them ever since. A plan written against that spec would rebuild retired stages.
2. **The crash-safety premise was asserted, not demonstrated.** The spec's headline claim — "ADR-0002 survives intact" — rests on `swap_pipeline_labels` being atomic. It is not: it adds the new label first, then removes stale ones best-effort, so a crash mid-swap leaves an issue carrying two pipeline labels.

Separately, `docs/proposals/fable-subagent-scheduling.md` proposes attaching a Fable *director* to that driver as one execution runtime. That proposal asserts a contract-only sandbox — isolated home and settings, scrubbed environment, no ambient tools or credentials, disposable process tree, short-lived key. None of it had been measured.

This ADR resolves the conflict, fixes the contracts, and records the boundary evidence. **It changes no pipeline behaviour**: it adds one pure contract module, one operator-run probe, tests, and documentation.

## Decision

### D1: Narrow ADR-0094's rejection to the convergence outer loop

ADR-0094's rejection is **narrowed, not reversed**, and it remains correct in its own scope.

The narrowing must be argued on the axes ADR-0094 actually used, not on axes of this author's choosing. Its rejection gives exactly two reasons: *"Rejected in favor of requeue + ledger **(i) to preserve the ADR-0001 concurrency model**; the fixpoint is distributed across the existing loops, **(ii) with the ledger as the shared truth** and oscillation detection as the safety net."* Each is addressed on its own terms.

**(i) The ADR-0001 concurrency model.** ADR-0094's concern is that one worker holding an issue across stages serializes the pipeline. The fenced driver holds a slot only while a phase is actually executing: C6 releases it for PARKED, HITL_WAIT, and label-write retry, which is where the long waits live. What remains held is the *working* portion — and that is a WIP limit, not a serialization, only if `max_in_flight` is set so that total concurrent work is no lower than today's per-stage caps allow. **That is a binding constraint on #11535, not an assumption**: `max_in_flight` MUST be ≥ the sum of today's per-stage caps for the stages a driver can occupy, or the change is a throughput regression dressed as a WIP limit, and the canary must measure concurrent-work occupancy against the classic baseline to prove it.

**(ii) The ledger as shared truth.** This is the reason the first draft of this ADR failed to engage, and it is the more important one. ADR-0094's truth concern is not the stage label — it is `ConvergenceLedger` (`laps`, `stage_state`, `open_concerns`, `lap_signatures`, `converged`). C1/C5 make labels authoritative for *stage*; they say nothing about *convergence*. So this ADR states it explicitly:

> **`ConvergenceLedger` remains the sole owner of convergence state under `issue_controller`.** A driver MUST NOT hold lap counts, open concerns, finding signatures, or convergence verdicts in process memory across a phase boundary. It reads them from the ledger and writes them back through `ConvergenceStateMixin` exactly as the phase loops do today. `HybridGate` is invoked per boundary with state re-read from the ledger, never carried in the driver's own memory — so the gate behaves identically whether called from a long-lived driver or from a fresh `phase_requeue` hop, which is the invocation-contract question VP-7 raised on #10038 and this ADR now answers. The lap budget (`max_convergence_laps`), `recompute_converged`, and `detect_outer_oscillation` continue to operate on ledger state and are unaffected by who is driving.

**A driver does own the outer lap, and that is the honest statement.** `REVIEW → DIAGNOSE → READY → REVIEW` is an ADR-0094 outer lap, and a driver spanning it owns it. The narrowing is therefore *not* "the driver doesn't touch the outer loop." It is: **the driver may sequence the outer lap, but may not own its state.** Sequencing moves from requeue to process-swap; truth stays in the ledger and the labels. That is the whole of the change, and it is why ADR-0094's D1/D2, the storage/decision split, and the lap budget are all untouched.

Consequence for #11535: a driver crash mid-lap must neither lose nor double-count a lap. The lap increment is a ledger write governed by C8's ordering, and the kill-mid-transition test required by B6 covers it.

The text added to ADR-0094's alternative is, verbatim:

> **Narrowed by [ADR-0137](0137-fenced-issue-driver-and-director-runtime-boundary.md):** this rejection is scoped to the convergence *outer loop*. A fenced, WIP-capped, labels-authoritative `IssueDriver` — one that releases capacity when not working, re-reads the label at every boundary, and is admitted and bounded by code — is a distinct design governed by ADR-0137. Every other decision in this ADR is unaffected.

### D2: The verdict is a conditional GO, and the condition is a runtime assertion

The rollout gate on #11533 is fail-closed: no-go unless the director sandbox, teardown, credential boundary, and recovery contract can be proven. The probe (`scripts/director_capability_probe.py`) attacked all four. Results, from the committed evidence in `tests/fixtures/director/director_capability_probe_evidence.json`:

Every row below is a value in the committed fixture, not a recollection of an exploratory session. Where a claim could not be reproduced by the committed probe it has been dropped from this ADR.

| Proof | Lane | Verdict | Observed |
|---|---|---|---|
| JSON framing | live | pass, constrained | Every line parses (`frames_parsed: 3`, `unparseable_lines: 0`). **Hazard:** `subtype_reported_success: true` alongside `is_error_reported: true` — `subtype` disagrees with `is_error` on the same frame. |
| Session-id capture | live | pass | Vendor session id present and captured even on a failed turn; recorded as a shape (`uuid-v4-shape`), never verbatim. Distinct from HydraFlow's factory session id. |
| Resume loss | live | pass | `--resume <dead-id>` → exit 1, stderr diagnostic, a terminal `result/error_during_execution` frame with `is_error: true`, and **no assistant turn**. Fail-closed and always detectable. |
| Isolated settings/home | live | pass | Allow-list env + disposable `HOME`/`CLAUDE_CONFIG_DIR` + empty cwd → `mcp_servers_loaded: 0`, `plugins_loaded: 0`, the only memory path inside the disposable config dir, no operator home path leaked. A hostile `.claude/settings.json` and `CLAUDE.md` planted in the working directory produced no project memory path (`hostile_project_memory_loaded: false`). |
| Environment scrubbing | hermetic | pass | 4 secret-shaped variables offered, 0 survive; nothing outside the allow-list survives; `HOME` overwritten. |
| Process-tree teardown | hermetic | pass | A real two-level process tree spawned under `start_new_session`; `kill_process_group` left `descendants_surviving_after_teardown: 0` out of 2. |
| Short-lived key expiry | hermetic | pass | 60s key `resolved_before_ttl: true`, `refused_after_ttl: true`, `plaintext_token_retained: false`, and `record_sampled_before_expiry: true` — the last matters because `resolve` deletes an expired record, so a check made afterwards would pass vacuously against an empty store. |
| No ambient tools/credentials | live | pass, constrained | **Credentials:** clean with no credential present; never *observed* to authenticate in the runtime configuration — a weaker observation, qualified below. **Tools:** not clean by default (F1/F2/F4 below). |

Four findings are load-bearing and are what make this a *conditional* go.

**F1 — Isolation does not empty the tool surface.** A fully isolated turn still advertised **22** tools including `Bash`, `Write`, `Edit`, `WebFetch`, and `Task` (`tools_with_isolation_only: 22`).

**F2 — An allow-list does not narrow it, and the advertised list is incomplete.** `--allowedTools Read` left all 22 enabled (`tools_with_allowlist_of_one: 22`, `allowlist_narrows_surface: false`): the flag is a *permission* filter, not a surface filter. Denying **every name the init frame advertised** still left 2 tools enabled (`tools_after_denying_every_advertised_name: 2`; the two are `Glob` and `Grep`, identified from the probe run rather than from the fixture, which records only the count). An empty surface is reachable (`tools_with_exhaustive_denylist: 0`), but a name-based deny-list is **fail-open across CLI upgrades**: a newly shipped tool is enabled by default and absent from the list.

**F3 — `apiKeySource` is not a trustworthy provenance signal.** It reported `none` with no credential present *and* `none` with a virtual gateway key injected (`api_key_source_reported: none`, `credential_turn_api_key_source: none`). It does not distinguish credential states, so nothing may gate on it.

**F4 — The tool array is not the only capability channel.** At `tools_with_exhaustive_denylist: 0` the same init frame still advertised 5 agents, 15 skills, and 42 slash commands (`residual_capability_entries_outside_tools: 62`). These are CLI built-ins that survive isolation by construction. They are unreachable once `Task` and `Skill` are denied, but they are capability surface that an assertion on `tools` alone does not see.

**The credential boundary was tested in both configurations,** because testing only the credential-free one would have proven merely that a process with no credential cannot authenticate. With no credential the turn fails (`cli_exit_code: 1`, `apiKeySource: none`). With **only the virtual gateway key** present, pointed at a dead local endpoint, the turn is never observed to authenticate (`credential_turn_authenticated: false`).

**That second observation is weaker than it looks, and is reported as weak.** The credential turn does not terminate on its own — the probe kills it at its budget (`credential_turn_killed_at_probe_budget: true`, `credential_turn_completed: false`). So what is established is *"never observed to authenticate against the host keychain"*, not *"cleanly refused"*. `credential_turn_authenticated` is computed to require an actual terminal result frame precisely so a timeout cannot satisfy it by default — the earlier formulation did, and that vacuity was caught in review. The honest reading: no ambient credential was observed to cross the sandbox in either configuration, and the runtime-configuration case rests on a turn that hung rather than one that completed. #11537 should re-run this proof against a live gateway that answers, which will convert it from a negative observation into a positive one.

**Therefore: GO, conditional on S4.** The sandbox is provable but not by construction — only by *verification*. The design is safe if and only if the runtime asserts the boundary it was handed rather than trusting the flags it passed. That is constraint S4, and `RejectionReason.SANDBOX_UNVERIFIED` exists so the failure has a first-class code rather than an exception path.

**The residual risk this go accepts, stated plainly.** S4 is *post-hoc*: it inspects the init frame of a turn that has already run. Under `-p` the prompt is delivered at spawn, so pre-hoc enforcement is not available. If a CLI upgrade silently re-enables a tool, the model holds that tool for the duration of one turn; S4 blocks the resulting *dispatch*, not the turn. The accepted exposure is therefore **one director turn**, bounded by the version fence in S4 which re-arms the gate whenever the CLI version changes. This is a named accepted risk, not a proof of safety.

Had the tool surface been unreachable, or had an ambient credential crossed the sandbox in the runtime configuration, or had resume loss been silent, this ADR would have recorded a no-go. It records a go because the evidence supports one — with the constraints the evidence itself forced.

### D3: Driver constraints C1–C9

C1–C4 are carried forward from the #10055 spec. C5–C9 are new and exist because the adversarial panel falsified the spec as written.

- **C1 (label-at-every-boundary).** The driver writes the pipeline label via `src/pr_manager.py:PRManager.swap_pipeline_labels` at every stage-crossing transition, **before** spawning the next phase's sub-process. In-memory `driver_state` is a cache of the label, never a substitute.
- **C2 (resume-from-labels).** On boot, drivers are reconstructed from GitHub labels, then hydrated from `ConvergenceLedger`. No in-memory-only state gates recovery.
- **C3 (preempt at phase boundaries only).** Mid-sub-process preemption stays a non-goal. See B3 for the wait bound that makes this safe.
- **C4 (stage-aware WIP caps).** A global `max_in_flight` plus the existing per-stage caps, which the allocator respects rather than replaces.
- **C5 (reconcile-from-recorded-intent).** New. A transition intent is persisted before every label swap and reconciliation resolves against it, because priority-based reconciliation silently reverts backward transitions. See B1.
- **C6 (release non-working capacity).** New. See B2.
- **C7 (fenced admission).** New. Every dispatch passes `src/driver_contracts.py:admit_dispatch`, a pure function whose first matching rejection wins, so admission is deterministic and replayable.
- **C8 (boundary transaction ordering).** New. For every stage-crossing phase, in this order: validate worker output → persist the artifact under an idempotency key → **record the `pending_stage_transition` intent** → compare the expected live label and swap it (**the durable commit**) → append the checkpoint/audit record and clear the intent → only then admit the next dispatch. A crash before the label safely replays the idempotent step; a crash after it recovers from label truth even if the audit cache lags; a crash *inside* the swap is resolved by C5(a) from the recorded intent. This ordering is what stops a ledger write that raced ahead of the label from corrupting replay with a phantom transition.
- **C9 (sub-state transitions commit in the ledger).** New. `DIAGNOSE`, `HITL_APPLY`, and `PARKED` are sub-states of an already-labelled stage, so they write **no label** and C8's durable commit does not exist for them. Their durable commit is a `pending_sub_state_transition` record — a **separate slot** from the stage record, because C5 rule 1 clears the stage record whenever exactly one pipeline label is present, which is the normal condition for a sub-state transition and would otherwise delete the commit. Without this, a crash between `take_pending_correction` and the applied correction loses the correction with no commit record — the blind spot C8 alone cannot cover.

### D4: Director sandbox constraints S1–S6

- **S1 (contract-only process).** Empty non-project working directory, disposable `HOME` and `CLAUDE_CONFIG_DIR`, and an **allow-list** environment (`DIRECTOR_ENV_ALLOWLIST`) — note this is an allow-list filter over the parent environment, not a literal `env -i`: `PATH`, `LANG`, `LC_ALL`, and `TMPDIR` are inherited by design. The runtime MUST pass `--setting-sources` explicitly; the probe uses `project` with an empty cwd, which loads nothing. Sandbox construction fails closed; falling back to the `bypassPermissions` command builder is forbidden.
- **S2 (one credential).** The director's only credential is a short-lived parent-scoped virtual gateway key that cannot mint child keys or reach worker accounts. Real provider keys and the gateway control token never enter its environment. Proven by the environment-scrubbing proof, the key-expiry proof, and — for the runtime configuration specifically — the credential turn described under D2.
- **S3 (exhaustive deny-list).** The spawn passes `DIRECTOR_DENIED_TOOLS`, which must include names the CLI does not advertise (`Glob`, `Grep` today). This list is a *starting* posture, never the proof; S4 is the proof.
- **S4 (observed-boundary assertion — the load-bearing one).** After every director turn the runtime MUST parse the last `system/init` frame and assert **all** of:
  1. the `tools` key is **present** and its array is **empty**. An absent or renamed key reads as *unverified*, never as "empty" — otherwise the assertion fails open on exactly the CLI-upgrade scenario it exists to catch;
  2. `mcp_servers` and `plugins` are empty;
  3. the observed `agents`, `skills`, and `slash_commands` channels (F4) are either empty or unchanged from the counts in the committed evidence — a change means the capability surface moved and must be re-probed;
  4. the reported CLI version matches `agent_cli_version` in the committed evidence. **A version mismatch invalidates the evidence and re-arms this gate**: the operator must re-run the probe before the director may dispatch again.

  Any failure returns `RejectionReason.SANDBOX_UNVERIFIED`; the turn's output is discarded and no dispatch is admitted. This is the condition on which D2's go depends, and its residual one-turn exposure window is named in D2.
- **S5 (framing discipline).** The parser keys success on `is_error`, never on `subtype` — the two disagreed on the same frame in the committed evidence. It also tolerates repeated `system/init` frames (last-init-wins); the committed run observed one init frame, so this rule is defensive rather than evidenced, and is cheap enough to keep on that basis.
- **S6 (disposable process tree).** Every director turn is spawned with `start_new_session=True` and cancelled via `kill_process_group`; worker cancellation stays owned by the broker. A turn that exceeds its budget is killed and treated as a failed turn, not retried in place.

### D5: The contracts are fixed here

`src/driver_contracts.py` fixes all ten contracts #11533 names — `WorkerRole`, `ModelRequirement`, `DriverLease` / `WriterLease`, `DirectorCapsule`, `DirectorCommand`, `WorkerDispatchRequest`, `WorkerReceipt`, `DriverCheckpoint`, `WorkerLineage`, and `WORKER_CATALOG` — as frozen, `extra="forbid"`, schema-versioned Pydantic models plus one pure admission function. #11535 and #11537 consume them unchanged.

Four invariants are enforced in the type system rather than in prose:

- **A literal family never resolves to another provider's model.** `ModelRequirement.satisfied_by` uses an **allow-list of Anthropic provenance** (first-party `claude-…` plus the Bedrock `anthropic.` / `us.anthropic.` forms), not a deny-list of known third parties — a deny-list is fail-open the moment a new backend ships, which is the same failure shape as F2 and must not be reproduced in the contract module. `WorkerReceipt` applies the check to **every** receipt that names a served model, not only accepted ones: an expired or superseded worker still ran and its receipt is still evidence. "GLM reported as Sonnet" is a validation error, not a silent relabel.
- **A director cannot name a concrete model.** `WorkerDispatchRequest` rejects `CONCRETE_MODEL` outright; resolving a tier to an id is the broker's job, and leaving it open was a one-field bypass of the invariant above.
- **Review cannot be hidden or self-performed.** The reviewer catalog entry is marked independent of the implementer and may never hold worktree write scope; `admit_dispatch` returns `SELF_REVIEW_FORBIDDEN` when the request's `requesting_spawn_id` is one of the implementer's spawns. The comparison is on the *spawn* id, not `request_id` — a `request_id` is minted fresh by the director and could never collide with a spawn id, so keying the fence on it would have left it permanently unreachable.
- **Ownership is fenced on identity, not only on epoch.** A request or writer lease belonging to **another driver** is refused with `DRIVER_IDENTITY_MISMATCH`; epoch alone fences the *same* driver across recovery and does not fence a misrouted request from a different one. A *stale epoch* is reported distinctly — `STALE_EPOCH` for the request, `LEASE_EXPIRED` for a writer lease not yet re-minted — because a lagging fence is not ownership theft and must not inflate the theft count B5's bar depends on. Writer-lease checks apply only to roles holding `issue_worktree` write scope, so a read-only role is never blocked by a lease it would never take.

`sandbox_verified` is a **required** argument of `admit_dispatch` with no default, so a caller that forgets to thread S4's result fails to construct the call rather than dispatching fail-open.

Two scope notes. `MAX_DISPATCH_BATCH = 4` permits a bounded batch in the *contract* while #11533 lists "no worker fan-out" as a non-goal: the contract fixes the shape now so later phases need not renegotiate it, and no runtime exists to act on it. And `DRIVER_CONTRACTS_SCHEMA_VERSION` stays `1` despite the contracts changing during this PR's own review — the version gates *consumers*, and there are none until #11535.

## The seven adversarial findings

**B1 — label read-back / cache-coherence discipline (C5).** The premise that an issue carries one unambiguous pipeline label is false: `swap_pipeline_labels` is add-first-then-best-effort-remove, so a crash mid-swap leaves two.

**(a) Reconciliation must be direction-aware — most-advanced-wins alone is wrong.** The obvious repair is to lean on the rule that already exists, `_STAGE_PRIORITY` most-advanced-label-wins in `src/issue_store.py:IssueStore._compute_stage_map`. That is correct **only for forward transitions**, and this pipeline's crash-interesting transitions are backward. With `_STAGE_PRIORITY = {FIND: 0, PLAN: 3, READY: 4, REVIEW: 5, HITL: 6}`:

| Backward swap | Labels present after a mid-swap crash | Most-advanced-wins picks | Result |
|---|---|---|---|
| `DIAGNOSE → READY` (route-back) | `hydraflow-review` + `hydraflow-ready` | `hydraflow-review` (5 > 4) | **the route-back is silently undone** |
| `HITL_APPLY → READY` (resume) | `hydraflow-hitl` + `hydraflow-ready` | `hydraflow-hitl` (6 > 4) | **the HITL resume is silently reverted**, pinning the issue until an operator drags it |

`swap_pipeline_labels` is direction-agnostic; the "always adds the forward label first" intuition holds on the nominal path only. Adopting most-advanced-wins unqualified would have replaced one false premise about that primitive (atomicity) with another (monotonicity) — the same defect class the panel found, inside the finding meant to fix it.

**C5(a), corrected — reconcile against recorded intent, not against priority.** Before any label swap the driver persists a `pending_stage_transition` record (`from_label`, `to_label`, `epoch`, `phase_attempt`) to the `ConvergenceLedger`. Boot reconciliation is then:

A record is **usable** only if its `epoch` is the epoch being recovered (recovery honours the record written by the incarnation it is replacing, and no older one) and its `phase_attempt` matches the ledger's. Anything else is stale and ignored.

1. **Exactly one pipeline label** → that label is the truth; clear any pending *stage* record. A pending **sub-state** record (C9 — `DIAGNOSE`, `HITL_APPLY`, `PARKED`) is **not** cleared here: those transitions legitimately run with one pipeline label and the record *is* their commit, so clearing it would lose the very correction C9 exists to protect. Stage records and sub-state records occupy separate slots for exactly this reason.
2. **Two or more labels, a usable pending record whose `to_label` is among them, and every other present label is the record's `from_label`** → the swap had begun. **The recorded `to_label` wins regardless of direction**; the driver completes the swap by removing the `from_label`, then clears the record.
3. **Two or more labels where a label outside `{from_label, to_label}` is present** → this is external drift, not an interrupted swap: an operator dragged a label during the window, which ADR-0002 documents as the HITL escape hatch. The driver **must not** complete its swap and remove it. It abandons the transition, adopts the externally-set label, and escalates — the same preemption rule as C5(b).
4. **Two or more labels and no usable pending record** (crash before the record was written, or drift from outside the driver) → fall back to `_STAGE_PRIORITY` most-advanced-wins, which is the existing behaviour and remains correct for the forward case. Note this fallback is unreachable via a driver crash — the record is written before the label add, so a crash before it leaves exactly one label — it exists for drift the driver did not cause.

The record is written **before** the label add, so any crash in the non-atomic window falls into case 2. Three properties close the remaining windows:

- **A crash between the record and the add** leaves one label, so case 1 applies: the transition never committed, the old label is truth, and the record is discarded. The intent is not replayed.
- **A label add that fails rather than crashes** likewise leaves one label, so the same case 1 discards the record; the driver then retries under C6's bounded retry. No stale intent survives a failed write.
- **The record is consumed by the first reconciliation that observes it and cleared unconditionally**, so it can never be more than one incarnation stale — which is what makes it safe to honour a record written under the previous epoch, the epoch that recovery has just fenced.

`IssueStore`'s behaviour for non-driver issues is unchanged, so this adds a rule for drivers rather than altering shared routing.

**(b) Re-read at every boundary.** The driver re-reads the pipeline label at every phase boundary and an externally changed label **preempts** its own state — otherwise the next C1 write silently clobbers an operator's manual drag, which ADR-0002 documents as the HITL escape hatch. `admit_dispatch` returns `LIVE_LABEL_CHANGED` for exactly this case. Note that `admit_dispatch` takes a single already-resolved `live_stage_label`: reconciliation per (a) happens upstream of admission, and the driver — not the contract module — owns it.

**(c) DIAGNOSE ambiguity.** DIAGNOSE shares `hydraflow-review` and writes no `SuspendRecord`, so a crash mid-DIAGNOSE is indistinguishable from a fresh REVIEW by label alone. The rule is **resume at the nominal state and re-detect the route-back fresh**, and the idempotency argument has to be made carefully, because the naive version of it is wrong on two counts:

- *Route-back detection is a pure function, but the phase is not.* An interrupted DIAGNOSE may already have pushed a commit and retriggered CI, mutating the very inputs the detector reads. Re-running a pure function over mutated inputs is not idempotent in effect. What makes re-detection safe is not purity but **convergence on current reality**: the detector reads the PR's *present* CI state and diff, so it re-decides rather than replaying a stale decision. If the interrupted attempt fixed the problem, re-detection sees green and advances; if it did not, it sees red and routes back again. Neither outcome depends on knowing which side of the crash window the push landed on.
- *The route-back counter is not idempotent.* `increment_route_backs` feeds ADR-0094's lap budget and oscillation detection, so a crash around it either double-counts or loses a lap. **The increment is therefore ordered inside C8's ledger write under the same `pending_stage_transition` record**, applied exactly once per recorded transition; the record's `phase_attempt` makes a replayed increment detectable and refused.

DIAGNOSE therefore needs no separate marker file: the `pending_stage_transition` record from (a) already carries the intent, and C9 extends it to the sub-state transitions that write no label at all.

**B2 — capacity accounting for non-working slots (C6).** PARKED, HITL_WAIT, and label-write-failing drivers **release** their in-flight slot. The panel's adjudication is adopted verbatim: releasing does not undercut the model's benefit, because the benefit is *inter-phase latency within one issue's lifecycle*, a different quantity from *admission latency for a parked issue*. One slow human therefore cannot starve factory capacity. A semaphore-blocked driver **does** count against admission (it is working, merely queued). Label-write failure gets a bounded retry — 5 attempts, exponential backoff, 10-minute maximum slot hold — after which the driver escalates to HITL and releases. Re-admission uses the driver's original enqueue time as its priority key, so a released driver cannot be starved by newer arrivals — **within its priority band only**, per the precedence B3 fixes; otherwise this rule would outrank an arriving P0 and contradict B3's wait bound.

**B3 — SchedulingPolicy/SchedulingView interface and the P0 wait bound.** `SchedulingView` is a frozen per-issue sensor record: issue number, priority, blast radius, driver state, wait time since admission request, current stage, and slot occupancy. `SchedulingPolicy.select(view) -> ranked candidates` is a pure control law over that frozen view — no I/O, replay-testable, the same shape as `src/queue_strategy.py`. **The P0 wait bound is stated with its precedence and its number.** Three ordering rules now exist and they must be ranked, or the bound is not derivable: B2's anti-starvation rule keys re-admission on original enqueue time, §7 draws candidate order from the `queue_strategy` engine, and a P0 is by construction the *newest* arrival. **Precedence, highest first: (1) priority band, (2) original enqueue time within a band, (3) the `queue_strategy` ordering within that.** Anti-starvation therefore operates *within* a band and never lets a released P3 outrank an arriving P0 — without this ranking B2's rule and B3's bound directly contradict each other.

With that ranking, the worst-case P0 wait is `one phase-boundary interval of the longest-running in-flight phase + the C6 maximum slot hold`. Both terms are concrete: `agent_timeout` defaults to **3600 s** and C6's label-write hold is **600 s**, so the stated worst case is **70 minutes**, not a symbol. That number is deliberately bad, and naming it is the point — if 70 minutes is unacceptable for P0 responsiveness then the fix is a lower `agent_timeout` for driver-held phases or genuine boundary preemption, decided on evidence rather than discovered in production. The canary must report the measured distribution against this ceiling. Mid-sub-process preemption remains a non-goal; the panel explicitly warned against over-correcting into it.

**B4 — engage the prior rejection, and land the paperwork first.** This ADR is that engagement (D1), and it lands **before** any runtime code: #11533 is the gate on #11535 and #11537, and this phase ships no scheduling change. The panel's sequencing demand — supersession lands with or before the first runtime merge — is satisfied by construction rather than by promise.

**B5 — a quantitative proven bar, with the anti-pattern named.** The named anti-pattern is the `queue_strategy` same-day flip: build #10045 merged 05:19Z, guard #10053 at 14:33Z, default flip #10061 at 18:13Z, all on 2026-07-20. That must not recur. The bar to advance beyond shadow mode, all of which must hold over a measured window of **at least 20 completed issues and at least 7 days**:

- zero duplicate dispatches, zero ownership-theft events, zero post-stop spawns;
- 100% of accepted workers carry lineage, cost, and effective-route receipts;
- zero label-desync incidents (an issue whose label and committed checkpoint disagree after a settled window);
- no increase in orphan process groups versus the classic baseline;
- terminal success rate and escaped-defect rate no worse than the **`phase_requeue` (classic) baseline** measured over a comparable window — the thing being gated is `issue_controller`, so comparing it to itself would be vacuous;
- p95 worker-decision latency and parent cost bounded and reported, and the measured worst-case P0 wait reported against B3's 70-minute ceiling;
- successful fresh reconstruction on every resume failure.

**The window is weak evidence for the rare-race criteria and that is acknowledged.** Twenty issues over seven days has little power against "zero label-desync incidents" or "no orphan-process-group increase", whose base rate tracks crash frequency rather than issue volume. Those two criteria are therefore additionally gated by **fault injection** — the kill-mid-transition test of B6 run against both C8 gaps and both C5(a) backward edges — rather than by clean-window observation alone.

The flip PR must cite this evidence explicitly. A default flip in the same calendar day as the build PR is forbidden regardless of what the numbers say.

**B6 — split the phases and name a real crash-safety test.** The epic splits the work by pipeline stage (#11535 deterministic driver → #11537 shadow broker → #11541 plan canary → #11542 implementation → #11543 review/HITL), but the panel asked for a split along the **risk axis**, which is a different cut and is not implied by the stage cut. #11535 MUST therefore be delivered in three internally-sequenced slices: **(P2a)** `DriverManager` + the knob, delegating to the existing `phase_requeue` path — behaviour-neutral and replay-testable; **(P2b)** the `IssueDriver` subprocess swap behind the flag, landing with the kill-mid-transition test below; **(P2c)** the real `SchedulingPolicy.select` plus C3/C4 backpressure. `select` and the backpressure work are named in no epic child today, and P2c is where they land. The behavioural test this ADR requires of #11535 is a **kill-mid-transition** test proving C8's ordering: kill the process between the artifact persist and the label swap, and between the label swap and the checkpoint append, and assert in both cases that recovery reaches the correct stage and that no ledger entry records a transition the label never committed. It MUST additionally cover the two **backward** edges C5(a) exists for — a route-back `REVIEW → READY` and a HITL resume `HITL → READY` killed mid-swap — because those are the cases priority-based reconciliation silently reverts, and a test that only exercises forward transitions would have passed against the wrong rule. String-matching a spec, as `regression_issue_10038.py` does, cannot test this and is not a substitute.

**B7 — alternatives considered.** Two cheaper designs, evaluated rather than assumed away:

- *(a) Fix `enqueue_transition`'s back-of-queue insertion.* The eager path already exists; a promoted issue merely lands behind older same-stage work. This is a queue-ordering bug and fixing it removes most of the "up to `data_poll_interval` per hop" latency the #10038 lead cites. It is **complementary, not a substitute**: it does not produce a single traceable per-issue timeline and cannot express in-flight WIP. It should be fixed on its own merits regardless of this ADR.
- *(b) A stateless WIP-admission cap at Triage*, recomputed from label counts on boot with no in-memory ownership. This delivers finish-what-you-start without touching ADR-0002 at all, and is genuinely cheaper. It does not deliver per-issue continuity or adaptive delegation, which are the director's entire premise.

The controller's unique deliverables are therefore exactly two: a single traceable per-issue timeline, and in-flight WIP as a first-class quantity. **The "context re-derivation paid six times" cost is withdrawn from the justification** — `issue_controller` still swaps sub-processes per phase, so it does not address that cost, and leaving it in inflated the ROI.

## Consequences

- The #11532 epic is unblocked at its gate: #11535 and #11537 may proceed against fixed contracts.
- Every later phase inherits a sandbox contract whose weakest link (F2) is named and gated (S4) rather than discovered in production — gated, not eliminated: S4 is post-hoc and accepts a one-turn exposure window.
- The contracts module is pure and importing it changes nothing, so the blast radius of this ADR's code is zero until a consumer exists.
- The design now costs materially more than the #10055 spec implied. S4's four-part assertion and version fence, C5's intent record on **every** swap, C6's release-and-readmit, C8's six-step ordering, and C9's sub-state commit are all real work #11535/#11537 must carry. In particular C5 adds a ledger write to the hot path of every phase boundary, which is a throughput cost the canary must measure.
- Two new fields are required on the driver state layer before #11535 can enforce C5 and C9 — `pending_stage_transition` and `pending_sub_state_transition`, in **separate slots** — the only state this ADR mandates that does not exist yet.
- `apiKeySource` is unusable as a provenance signal anywhere in the factory, not just here.
- A CLI upgrade is now a gating event for Fable mode: S4's version fence disarms the director until the probe is re-run.

## Alternatives considered

- **Record a no-go.** Legitimate and explicitly permitted by #11533, and this was close. Rejected on the evidence: the credential boundary held in *both* configurations including the runtime one, teardown left zero survivors, resume loss is fail-closed and detectable, and the tool surface is reachably empty with the key present on the frame. The fail-open findings (F2, and F4's uncovered channels) have cheap, verifiable mitigations in S4. What tips it to a go rather than a no-go is that every gap found is *detectable at runtime by the director itself*; had any been undetectable, the honest answer would have been no-go.
- **Reverse ADR-0094 outright.** Rejected. Its gate/ledger decision is sound and untouched by this work; only the alternatives passage needed scoping. Narrowing is the smaller, more honest change.
- **Edit ADR-0094 in place.** Rejected — the repo rule requires a new ADR, and in-place editing would erase the record of why the rejection was correct in its original scope.
- **Trust the sandbox flags without S4's assertion.** Rejected. F2 proves the deny-list is fail-open across CLI upgrades; a design that trusts it would silently regain `Bash` on the next release.
- **Native vendor child-task API instead of a brokered worker.** Deferred, unchanged from the proposal. Native children inherit the parent's security envelope and get no separate gateway key, route, worktree, or process ownership.

## When to supersede this ADR

Supersede when the brokered canary produces evidence that falsifies a constraint — in particular if the S4 assertion proves unmaintainable against CLI churn, if the B3 wait bound is measured worse than one implement timeout, or if the B5 bar is met and the design graduates from canary to default.

## Implementation status

The **driver half** landed with #11535: `scheduling_model` / `execution_runtime`
config dials (Classic default), the `SchedulingPolicy` control law, `DriverManager`,
the fenced `IssueDriver` with C8's boundary ordering, single-item phase adapters over
the existing stage workers, and the single-owner interlock that keeps AutoAgent from
becoming a second owner. C1–C9 are implemented, including C5(a)'s
reconcile-against-recorded-intent and the two separate intent slots; the
kill-mid-transition test B6 demands is
`tests/regressions/test_issue_11535_kill_mid_transition.py`, and it covers both
C8 gaps **and** both backward edges.

C9's slot is written on the one sub-state transition this phase actually makes:
entering `HITL_APPLY` to take up an operator's correction, which moves no label
and would otherwise leave no durable trace. `DIAGNOSE` and `PARKED` are reached
through the reviewer's own routing rather than through a driver-declared
sub-state, so they carry no record yet; the slot and its accessors are in place
for the phases that add them.

One boundary is worth naming precisely, because it is where the driver's
guarantee stops. The intent record covers every transition the driver *drives*:
it is written before the phase runs, so it covers both the driver's own swap and
the swap the stage worker makes inside it. A transition a stage worker decides on
**mid-run** and commits without the driver having declared it — a reviewer
choosing to route back — carries no intent record, so a crash inside that
particular swap still falls to C5(a) rule 4. That window is pre-existing Classic
behaviour, unchanged and not widened by this phase; closing it means the stage
workers recording their own intent, which is P2b/P2c work.

The **director half** landed with #11537, in **shadow mode**: S1–S6, the
capsule/command/receipt contracts and `admit_dispatch` now have a runtime
consumer, and `execution_runtime=fable_director` is selectable rather than
refused at config load. What it selects is an *observer*, not an actuator.

Under `issue_controller + fable_director` the deterministic `IssueDriver` still
executes every phase and remains authoritative. At each boundary it completes,
`FableDirector` reconstructs the issue's capsule from live state, runs one
isolated turn, applies S4's assertion to that turn's own `system/init` frame,
validates the reply against `DirectorCommand`, passes it to
`ShadowDispatchBroker`, and records the comparison. Nothing in the pipeline
reads any of it.

Three properties make "shadow" a demonstrated safety property rather than an
intention:

- **The seam returns nothing.** `DriverManager.DriverBoundaryObserver` is handed
  a boundary that already happened and yields no value the allocator can act on.
  `tests/regressions/test_issue_11537_shadow_safety.py` proves differentially
  that the same tick with and without an observer produces byte-identical live
  effects — labels, journal bytes, store claims, tick report — **including when
  the observer raises**. A shadow component must not be able to fail what it
  observes; the one exception is `CreditExhaustedError`, which is factory-wide.
- **The broker has no dispatch method.** "No production worker is dispatched by
  Fable" is the absence of the code rather than a flag, pinned by
  `tests/architecture/test_director_no_authority.py`. Arming dispatch is
  #11541's decision and `SchedulingPreset.director_dispatch_armed` is its
  separate flip — separate so that selecting the observer can never be mistaken
  for trusting the actuator. (#11541 kept that separation and moved the flip
  off the preset onto `config.fable_plan_canary_repo`, because a preset is
  fleet-wide and a canary must be bounded to one repository. See the Plan
  canary section below.)
- **No convergence state is written.** The same architecture guard asserts the
  decision path never calls a ledger mutator. `ConvergenceLedger` remains the
  sole owner of convergence state, per the ADR-0094 narrowing (ii); the shadow
  log is telemetry beside it, never a second copy of it.

**S4 is implemented as an assertion over the observed frame, not as trust in the
flags passed.** `director_sandbox.assert_observed_surface` requires the `tools`
key to be *present* and empty (absent or renamed reads as unverified), requires
`mcp_servers` and `plugins` to be present and empty for the same reason, requires
the `agents`/`skills`/`slash_commands` channels to be empty or unchanged from the
committed evidence, and re-arms the gate on a CLI version mismatch. Its result
is applied **before** the turn's command is parsed: a turn whose surface cannot
be proven empty has its output discarded rather than parsed and then refused.
The residual one-turn exposure window named in D2 is unchanged.

**S4's version fence fires at boot as well as per turn.** The per-turn assertion
is still the load-bearing one, but it runs *after* a turn has been paid for and
discarded, so a CLI upgrade would otherwise mean every boundary buys a turn that
is thrown away until the spend ceiling stops it. Preflight already holds both the
observed version and the evidence's, so it compares them and refuses — which is
what "a version mismatch re-arms this gate" has to mean in practice.

**One clause is implemented stricter than S4 as written, deliberately.** S4(3)
says the residual channels must be "empty or unchanged", which permits a renamed
channel key to read as *empty* and therefore verify — the same fail-open shape
S4(1) exists to close, surviving on a different leg of the same assertion. The
runtime treats an absent or non-collection channel key as **moved**, never as
empty. A future revision of this ADR should adopt that wording; until it does,
the code is the tighter of the two and the divergence is recorded here rather
than left as an undocumented surprise.

**The observation is taken at real boundaries only, and its cost is bounded.**
A driver parked on a barrier reaches `IDLE` on every poll, so observing every
advance would spawn a director turn every `poll_interval` indefinitely — and
because `IDLE` maps to "yield", where yielding is trivially right, those no-op
ticks would then dominate the agreement rate, which is the headline number B5's
bar reads. Contaminating that rate would corrupt the evidence the next phase's
go/no-go rests on. So only outcomes representing a boundary the driver actually
attempted are observed; `IDLE` is recorded as `not_a_boundary` and never scores.
Two further bounds exist because nothing else in the design bounds turn *count*:
`director_shadow_usd_ceiling` is an aggregate spend ceiling that stops turns
being started, and `director_shadow_enabled` is a **live** kill switch, because
the dials that select the director are restart-required and a director turn
costs money. Both are read per boundary rather than captured at construction,
so the live badge the settings registry gives them is true.

**A decline is counted, never written.** An idle tick, a stop, the kill switch
and the spend ceiling all reach the observer on paths the allocator takes for
every driver on every tick, so a durable row for any of them puts an `fsync` on
a hot path. The first implementation wrote one, justified by an assumption that
the tick sleeps a poll interval between rounds — which was false:
`DriverTickReport.did_work` counted an `IDLE` advance as work, and the polling
loop skips its sleep when a tick did work, so a single parked driver spun the
allocator at loop speed. That is fixed at the cause — an `IDLE` advance is not
work — and the observer keeps the defence in depth.

**A barrier is not a failed attempt.** Excluding `IDLE` covers a PARKED driver
but not one waiting on a *human*: the HITL phase's no-correction path returned
`ok=False`, which the driver read as a failed attempt, so the loop still never
slept for the state that waits longest and the phase-attempt counter — which
keys the boundary idempotency key — climbed once per tick for as long as the
operator took to answer. `PhaseOutcome.no_progress` now distinguishes the two:
a barrier reports `IDLE`, burns no attempt, and is still ticked every cycle so
it notices the answer. `ReviewPhaseAdapter` had documented exactly this intent
since #11535 ("rather than burning a phase attempt on a propagation delay")
without a field to express it; its PR-not-yet-visible path is corrected too. The rule is now simply:
**a row on disk means a turn was attempted**, which is also what makes
`observations` a denominator the agreement rate can honestly divide by.

Because the counters are per-run and the log's tail is bounded, the cumulative
**spend** is persisted in its own file beside the log. Deriving it from the tail
let a bounded window evict every costed row, silently re-arming the whole budget
on each restart — a ceiling that resets is not a ceiling.

**Evidence is minted honestly.** A refusal produces a real `WorkerReceipt`
(`REJECTED`, deterministic reason code, no served model). An *admitted* request
produces no receipt at all — it produces a `ShadowDispatch`, which records what
would have been dispatched and claims nothing else. An `ACCEPTED` receipt would
require inventing a lineage and a served model for a worker that never ran, in a
contract whose purpose is to make a mis-reported model a validation error.

Two honest gaps this phase does **not** close:

- **S2 is implemented; its *proof* against a live gateway is not.** The turn
  runner mints one short-lived parent-scoped virtual key per turn through the
  same `runner_utils.resolve_harness_env("gateway", …)` path every other spawn
  uses, and revokes it in a `finally` — so the director inherits the existing
  fail-closed mint (a `GatewayMintError` rather than a fall-through to an ambient
  provider key) rather than a bespoke one. Minting is proven at **preflight**:
  a director that cannot obtain its one permitted credential refuses to run,
  because the alternative is a shadow log full of authentication failures that
  read like a flaky model rather than an unconfigured gateway. What remains for
  #11541 is D2's actual request — re-running the probe against a gateway that
  *answers*, converting "never observed to authenticate" from a negative
  observation into a positive one. That needs a live gateway, not more code.
- **`WriterLease` digests are not measured.** A shadow turn inspects no worktree,
  so the lease carries the literal value `"unobserved"` rather than a fabricated
  sha, and is never held on entry. The broker *does* fold it forward within a
  batch, so the single-writer property holds over what would have been
  dispatched. Real digests and real lease enforcement remain #11542's.

### The Plan canary (#11541)

The **third phase** armed dispatch, for one repository and one phase. Under
`issue_controller + fable_director` with `config.fable_plan_canary_repo` naming
this exact repository, a `PLAN` boundary's admitted dispatches become real
child processes; every other repository, every other phase and every host with
the dial empty runs the shadow path #11537 shipped, byte for byte.

**The bound is one predicate.** `plan_broker.plan_canary_covers` demands all
three of: the dial names one canonical `owner/repo` (ADR-0139 D2's lossy-slug
refusal reused in both directions), this repository is exactly it, and the
phase is `PLAN`. "Implement, review and HITL remain Classic" is therefore a
property of that function rather than of every caller remembering to check.
`tests/regressions/test_issue_11541_outside_the_slice.py` proves it
differentially — the same director over the same boundary, actuator fully
wired, records byte-identical evidence to a director with no actuator at all —
for an empty dial and for another repository. The later-phase arms assert the
weaker but sufficient property that the boundary is never *offered* to the
canary (no spawn, no receipt, not even a refusal), using a role the catalog
does allow at the phase under test: mutation testing showed that a `planner` at
IMPLEMENT is refused by the capsule's role allow-list anyway, so a planner-only
arm could not tell the bound from the catalog. `HITL` is deliberately absent —
`WORKER_CATALOG` catalogues no role for it, so no request could distinguish the
two there. Three non-vacuity tests sit beside all of it.

**The rollback is one field**, and the same field arms it. `fable_plan_canary_repo`
is live (`settings_registry`), empty by default, and deliberately **not** an env
override for ADR-0141 D5's reason: an env row applies whenever a field is at
its default and the disarmed value *is* the default, so an env var would mean
clearing the dial disarmed nothing. Its absence is pinned with the reason.
Rolling back returns the repository to shadow mode rather than to Classic, so
the evidence keeps accruing while nothing is dispatched.

**Both directions of that dial are live, and the first draft got one of them
wrong.** Construction of the actuator was made conditional on the dial —
which reads as a stronger default-off proof and is in fact a bug: the dial is
empty by default, so a factory booted disarmed had no dispatcher to arm, and
naming a canary repository would have done nothing until a restart while the
settings screen reported it live. The actuator is now built whenever a director
is selected and gated *only* by the live predicate. Default-off is proven where
it is actually true: under Classic and under the deterministic controller there
is no director and therefore no actuator at all, and under a director with the
dial empty nothing is ever dispatched — proven differentially rather than by an
absent object.

**Arming lives on the config, not on the preset.**
`SchedulingPreset.director_dispatch_armed` stays `False` on every preset and no
code reads it as permission, because a preset is fleet-wide: one that armed
dispatch would arm every repository the factory touches, which is the opposite
of a bounded slice. Selecting the director (restart-required) and naming the
canary repository (live) remain two separate operator decisions, which is the
distinction #11537 built that field to preserve.

**The tier choice is explainable after the fact.**
`plan_broker.resolve_plan_model` may depend on exactly two things — the
requirement the director asked for and the role's catalogued entry — and
returns a
`PlanRouteDecision` carrying a content-addressed `decision_id`, the rule that
fired, the source the tier came from, the catalog revision, the route-policy
revision and the input echoed back. That is deliberately the same contract
`routing_policy.explain` holds itself to; a looser one produces a canary whose
choices cannot be explained afterwards. `PLAN_TIER_CATALOG` is code-owned like
`WORKER_CATALOG`, and a test pins that every id in it has Anthropic provenance
and satisfies its own family, so an edit putting `glm-5.3` under `claude-opus`
fails at test time rather than at a receipt.

**A literal family resolves literally or refuses, and the division of labour
is stated rather than guessed.** A brokered child is pinned to the gateway and
the gateway derives the account from the model, so **no legacy dial can put one
on GLM** — `repo_provider` and the role dials are applied by
`repo_backend.apply_repo_provider` at the two *agentic* seams and never at the
one-shot seam a brokered child takes. The lock that can is a
`provider_lock=zai-harness` routing policy, and it refuses at
`route_enforcement.enforce_canary_route` — before `resolve_harness_env`, so
with no credential in existence and zero upstream bytes.

How that refusal reaches the receipt is worth stating exactly, because it is
narrower than it first looks. The resolver reports
`literal-family-unsatisfiable` only when the lock excluded a lane that *was*
otherwise eligible — which needs a non-Anthropic account in the pool to raise
`ANTHROPIC_LANE_REQUIRED`. That reason is classified as inadmissible and
reaches the receipt as `MODEL_REQUIREMENT_UNSATISFIABLE`, because retrying an
inadmissible route never succeeds and the thing to edit is the policy. An
all-Anthropic pool whose every member the lock excludes reports
`no-eligible-account` instead, which the resolver does not split into "no
credential" and "the lock took them all" — so it is classified as the retryable
`ROUTE_UNAVAILABLE`, the conservative reading, and the operator finds the lock
at the gateway where both are visible.

**The classification is on the reason, never the outcome**, and getting that
backwards is a real hazard rather than a hypothetical one: `on_unavailable`
defaults to `HOLD`, so the ordinary lock refusal *arrives as a hold*, and a
runtime that treated a hold as retryable would silently turn the flagship
refusal back into a retry loop. The reason is a durable fact about the request;
the outcome is a per-policy dial over what to do when a lane is unavailable.

What the broker itself checks is the question it can answer: that
`PLAN_TIER_CATALOG`'s answer satisfies the **family** it was resolved from —
the family, not the incoming requirement, because `ModelRequirement.satisfied_by`
returns `True` unconditionally for a capability and asking the requirement
would have left the capability arm with no fence at all.

After the spawn, the served model is read back off the seam
(`run_lightweight_agent`'s new `spawn_out`) and re-checked. It is read from the
CLI's own result envelope when the CLI names a model, and the receipt records
whether that happened: an unobserved id falls back to the requested one and is
marked `model_observed: false`, because a weaker claim that looks like a
stronger one is worse evidence than a weak claim that says so.

**One issue per repository.** `plan_broker.PlanCanaryLatch` holds the issue's
first acceptance criterion as a fence. It is in-memory and per-run: a durable
latch would outlive the process that took it and idle the canary after a crash,
while a per-run one is empty after a restart, which is also the true state. A
TTL covers a hold abandoned *within* a run, and the director releases the slot
on the tick its issue leaves `PLAN`.

**The canary adds workers, not authority.** The observation seam still returns
nothing, so a brokered worker's output cannot move a label. The deterministic
`PLAN` phase still runs, still validates, and still commits; the brokered
children produce artifacts and receipts beside it. That is the honest scope of
a canary at this rung — B5's bar is about dispatch safety and receipt coverage,
not about a brokered plan replacing a validated one — and it is what keeps
"GitHub labels, IssueDriver epoch, plan validation, constitution and cohort
gates remain authoritative" literally true. Letting a brokered artifact *become*
the plan is #11542's decision, and it needs the writer lease #11542 also owns.

**The shadow log's schema version moved to 2.** `ShadowObservation` gained
`dispatched`, and a row is serialised over the whole model dump — so the new
field appears, as `[]`, on every row a shadow-mode host writes too. The model is
`extra="forbid"`, so older code reading a newer log drops those rows; the
version bump is what makes that diagnosable rather than mysterious. "Byte
identical outside the slice" is therefore a claim about the **pipeline's**
effects — labels, journal, store claims, tick report — and not about the
telemetry file's schema.

**Three refusal codes were added to the contract module**, additively:
`ROUTE_UNAVAILABLE` (no route or credential could be obtained for an otherwise
legal request), `WORKER_TIMEOUT` (a wall-clock budget ran out — the child outlived its own, or the batch's shared one was already spent and the request was refused rather than started)
and `CANARY_SLOT_HELD` (another issue holds this repository's one slot). None
of the three can occur while nothing is dispatched, which is why none existed
before; folding them into `FANOUT_OVERFLOW` or `BUDGET_EXHAUSTED` would make
the evidence B5's bar is read from unreadable.
`DRIVER_CONTRACTS_SCHEMA_VERSION` stays `1` — the members are additive and no
field changed.

**The dispatch is awaited inside the allocator tick, and that cost is named
rather than hidden.** `fable_plan_worker_timeout_seconds` bounds the whole
*batch* rather than each child, and its default (240s) and ceiling (900s) are
deliberately low, because this figure is exactly how long one armed PLAN
boundary can delay every other driver in the fleet — a per-child budget would
multiply it by `MAX_DISPATCH_BATCH`. It is of the same order as
`director_turn_timeout_seconds`, which the shadow director already spends on
that tick. This adds to B3's worst-case P0 wait and the canary must report it
alongside the 70-minute ceiling. Moving dispatch off the tick is #11542's, and
is a precondition for the batch growing.

**The pre-spawn fence is re-read with no `await` between the check and the
claim.** The broker admitted against a snapshot; a stop, an epoch bump, a
dragged label, a moved policy revision or a cleared dial can all arrive between
that admission and the spawn — including *between two children of one batch*,
because the second starts after the first finishes. The idempotency key is
claimed before the process starts, so a replay can never produce a second child
for one key. The label arm reads the driver's own post-boundary view rather
than issuing a fresh GitHub read: C1 makes that view a cache of the label the
driver re-read at this boundary, and giving an observer its own port would hand
authority to the component that must not have any.

**Arming both canaries has one policy-side prerequisite, stated here rather
than discovered — and it is narrower than it first looks.** A brokered child
mints with `principal_id` = its worker role, which
`routing_policy.canonical_worker_role` resolves. So with the ADR-0141
enforcement canary *also* armed for the same repository, any policy that
**matches** a brokered child must be able to serve it: a matching policy whose
account pool cannot reach an Anthropic lane refuses every brokered child.

A policy that does *not* match one is harmless, which is the half worth being
exact about: an unmatched role yields `ROLE_NOT_IN_SET`, no policy wins, and
`explain` falls through to `_legacy_decision`, which returns **selected** /
`no-policy-applies` with the effective model the spawn already had — the
`PLAN_TIER_CATALOG` id — so the child runs, on a bound v2 key, unchanged. An
empty snapshot behaves the same way.

Two dimensions decide whether a policy matches at all, and the safety-relevant
reading is the opposite of the intuitive one. A policy that names **no** roles
matches every brokered child (an empty `match.roles` means *all* roles); a
policy that **does** name roles matches one only if it names `planner`,
`architect` or `explorer` — so an `implementer`-only policy is inert here
rather than hostile. `match.principal_ids` is a separate dimension and can
exclude a brokered child even with `roles` empty.

The prerequisite is **policy-side, not gateway-side**: the snapshot lives under
the repository's own data root and the check is `enforce_canary_route` on the
HydraFlow side (ADR-0141 §D1). The gateway's own `route_mint` never looks at a
worker role, and `ONE_SHOT` is already in its mintable face set. The two dials
are otherwise independent by design: one governs credential binding, the other
governs dispatch.

**S2's credential proof is converted, and D2's request is answered.** The
director's per-turn key now mints through the same bound v2 path as every other
governed spawn (ADR-0141 §D1, closed by this phase), so the canary
repository can run the enforcement canary and the Fable director together —
they were mutually exclusive while the director minted unbound. A bound turn
spawns with `--model <effective_model>` because the gateway's data plane
refuses a body naming any other model; an unbound turn's argv is unchanged.

Two things this phase deliberately did **not** do: no default flip (B5's bar is
unmet and its window has not been measured), and no sandbox e2e — the actuator
adds no docker path and no UI page, is covered by two independent air-gap seams
(`SANDBOX_SEAMS["plan_worker_runner"] = "config_disable"` plus a cleared dial in
`_apply_sandbox_config_overrides`) and by the MockWorld scenario, and the honest
e2e is the canary itself, which needs a live factory rather than a scenario.

### The Implement canary (#11542)

The **fourth phase** widened dispatch from Plan to Implement, and made the
writer lease real. Under `issue_controller + fable_director` with
`config.fable_implement_canary_repo` naming this exact repository, an
`IMPLEMENT` boundary's admitted dispatches become real child processes holding
a real fence; every other repository, every other phase, and every host with
the dial empty runs exactly the code the phase before it shipped.

**A second dial, not a widened one.** `fable_implement_canary_repo` is separate
from `fable_plan_canary_repo`, and the separation is the epic's own rollout rule
("widen one role boundary at a time") expressed as configuration rather than as
intent. One dial covering both phases would mean an operator running the Plan
canary today woke up dispatching *writers* tomorrow.
`tests/regressions/test_issue_11542_outside_the_slice.py` proves the two are
independent in both directions, through the real composition root, and
#11541's own regression is untouched and still passes verbatim.

**The fence is what the phase is named after.** A write-capable worker is
briefed against one worktree state — branch, base SHA, HEAD, diff digest —
measured *before* it starts and re-measured *after* it returns.
`implement_broker.check_worker_fence` judges the two, first-match-wins, in an
order that is itself a decision: ownership first (another driver is theft, not
staleness), then the epoch and phase-attempt tokens #11535 already owns, reused
rather than re-derived, then the live label, then the four worktree tokens
coarsest-first. A breach produces a `SUPERSEDED` receipt with a deterministic
code and the artifact is **discarded** — it does not reach `prior_receipts` and
the next director turn never sees it. That is the difference between a late
worker being *rejected* and being *ignored*.

`UNMEASURED` is checked before any comparison, for S4's reason at a second
boundary: an absent reading reads as *unverified*, never as *unchanged*.
Without that clause two unmeasured sides compare equal and a fence that
measured nothing would verify everything — the fail-open shape F2 condemns.

**Two refusal codes exist because the criterion names two failures.**
`WORKTREE_DIGEST_STALE` and `BRANCH_MISMATCH` are separate members: a moved
digest is work happening, and a moved branch is the worktree having been reused
for another issue, which is the failure that makes a diff apply cleanly to the
wrong place. `WORKTREE_UNMEASURED` and `HIBERNATING` join them, additively;
`DRIVER_CONTRACTS_SCHEMA_VERSION` stays `1`.

**Exactly one writer, and read-only evidence fans out.**
`implement_broker.WriterLeaseRegistry` admits one holder per *issue* — the
granularity of a worktree — and `needs_writer_lease` reads the answer off
`WORKER_CATALOG.write_scope` rather than a second list of role names. The lease
is taken before the spawn and released in a `finally`, so a timeout, a
cancellation, a raised bug, a stale digest and a stop all end authority on the
way out rather than leaving a lease held by a process that is already dead.
Children run serially, which is both what "run sequentially in one issue
worktree" means and what stops the second write-capable child of a batch
deadlocking against the first.

**Hibernation suspends authority and measurement, not observation.**
`hibernation_reason` names the three waits C6 already releases *capacity* for —
`PARKED` (CI and barriers), `DIAGNOSE`, `HITL_WAIT` — and the director revokes
the issue's writer lease on the tick it enters one, refuses any admitted batch
with `HIBERNATING`, and takes **no worktree measurement at all**. That last
clause is not tidiness: a driver waiting on a human is ticked for as long as
the human takes, so measuring it would put three `git` reads on a path the
allocator reaches every poll interval — the same hot-path defect #11537 had to
fix at its cause once already. The director's *turn* still runs and is still
recorded, because the observation is the evidence this rung exists to gather.

There is nothing to reconstruct on the way back, and that is the honest reading
of "reconstruct from deterministic checkpoints" in a runtime that never resumes
a session: the next live boundary rebuilds the capsule from live state and
re-measures the worktree from scratch, and a lease minted before the wait is
refused by the fence if anything moved.

**The canary still adds workers, not authority.** The deterministic
`ImplementPhase` runs, gates, commits and does not push, exactly as before —
`src/implement_phase.py` is untouched by this phase. A brokered implementer or
debugger produces a bounded correction proposal beside it, as an artifact and a
receipt. `tests/architecture/test_director_no_authority.py` pins that
`implement_worker_runner` reaches no label mutation, no merge, no convergence
write, no commit or push primitive, and no raw spawn primitive other than
`run_lightweight_agent`. Letting a brokered diff *become* the commit needs the
independent review #11543 owns.

**Independent review's fence became reachable here.** `admit_dispatch` has
carried a `SELF_REVIEW_FORBIDDEN` arm since #11533, and until this phase it
could never fire: nothing populated `implementer_spawn_ids`, because no
brokered implementer had ever run. The director now records the child spawn ids
of *accepted* implementer receipts and feeds them to the broker, so a reviewer
requested from an implementer's lineage is refused. A refused or superseded
implementer contributes no lineage, so the fence cannot refuse a reviewer over
a worker that never contributed anything.

**Where the measurement happens, and why not on a Port.** The four tokens are
read through the **injected** `SubprocessRunner.run_simple`, the same posture
`director_turn_runner` holds, with the parse and the digest pure in
`implement_broker` — the pure-engine/one-subprocess-seam split
`workspace_gc_loop` already uses for its landed proof. `WorkspacePort` carries
no git-read queries today, and adding four to it would have changed a shared
protocol, three implementations and three conformance lists for one consumer.
The seam is honest either way: the sandbox injects `FakeSubprocessRunner`, so
an air-gapped scenario measures nothing real. If a second consumer appears, the
queries belong on the Port and this note is the reason they are not there yet.

**Brokered workers mint inside the authorization boundary, and it is asserted.**
A child's gateway key is minted inside `run_lightweight_agent`, which resolves a
governed route with `principal_id=source`; the actuator passes the worker's
catalogued role as `source`, and `routing_policy.canonical_worker_role` matches
a `WorkerRole` value exactly — so a brokered writer mints a route-**bound** v2
key attributable to its own worker account wherever the enforcement canary is
armed. That chain has one link a future edit could break silently, so
`tests/test_implement_broker.py` pins that every role this canary can dispatch
is a canonical principal, with a non-vacuity case beside it. ADR-0141 §D1's
named gap on `service_registry._mint_director_key` was closed by #11541 and is
unchanged here.

**No retry, and therefore no lost lineage.** ADR-0142 left a HydraFlow-side
fallback driver unbuilt because *"a worker retry today gets a fresh
`dispatch_id`, so lineage is gone before it could be cited."* This phase does
not open that hole: a fenced worker that times out, fails, or comes back to a
moved slice produces **one** terminal receipt and the boundary ends. The retry
is the driver's own phase attempt, which the next lease fences with a token it
carries — so nothing here needs to cite a lineage it no longer has. Building
that driver stays #11544's, with the citation protocol ADR-0142 already
enforces at the gateway.

**Rollback is one field, and it is the same shape as #11541's.**
`fable_implement_canary_repo` is live, empty by default, and deliberately not
an environment override for ADR-0141 D5's reason. Clearing it stops the next
dispatch with no restart; the round trip is run, and rolling it back leaves the
Plan canary armed if it was.

Two things this phase deliberately did **not** do: no default flip (B5's bar is
unmet), and no sandbox e2e — the actuator adds no docker path and no UI page,
is covered by three independent air-gap pins
(`SANDBOX_SEAMS["implement_worker_runner"] = "config_disable"`, the pinned
`execution_runtime`, and a cleared `fable_implement_canary_repo` in
`_apply_sandbox_config_overrides`) and by the MockWorld scenario. The honest
e2e is the canary itself, which needs a live factory.

## Source-file citations

- `src/driver_contracts.py`: `WorkerRole`, `ModelRequirement`, `DriverLease`, `WriterLease`, `DirectorCapsule`, `DirectorCommand`, `WorkerDispatchRequest`, `WorkerReceipt`, `DriverCheckpoint`, `WorkerLineage`, `WorkerCatalogEntry`, `WORKER_CATALOG`, `RejectionReason`, `admit_dispatch`, `DriverPhase`.
- `src/scheduling_model.py`: `SchedulingModel`, `ExecutionRuntime`, `SchedulingPreset`, `resolve_preset`, `uses_issue_driver` — the two dials and the fail-loud combination guard (#11535).
- `src/issue_driver_policy.py`: `SchedulingView`, `SlotOccupancy`, `select_admissions`, `rank_candidates`, `admit_phase_result`, `reconcile_stage_label`, `StageIntent`, `StageReconciliation`, `ReconcileOutcome`, `counts_against_wip`, `is_preemptible`, `boundary_idempotency_key` — the pure control law behind B3, C3, C4, C5(a) and C6.
- `src/issue_driver.py`: `IssueDriver`, `PhaseOutcome`, `AdvanceOutcome` — C1/C5/C7 fencing and C8's boundary transaction.
- `src/driver_manager.py`: `DriverManager`, `PipelineLabelAdapter`, `DriverTransitions` — the capacity allocator and the C5(a) reconcile-against-recorded-intent read.
- `src/driver_journal.py`: `DriverJournal` — the durable boundary record C8 step 4 appends to.
- `src/driver_ownership.py`: `DriverOwnershipRegistry` — the single-owner interlock.
- `src/driver_phase_adapters.py`: `PlanPhaseAdapter`, `ImplementPhaseAdapter`, `ReviewPhaseAdapter`, `HITLPhaseAdapter` — single-item adapters preserving the existing stage-worker contracts.
- `src/models.py`: `DriverState`, `SuspendRecord`, `ConvergenceLedger`, `PendingStageTransition`, `PendingSubStateTransition` — the two intent slots C5(a)/C9 require, deliberately separate.
- `src/state/_driver.py`: `DriverStateMixin` — including `record_stage_transition` / `clear_stage_transition` and `record_sub_state_transition` / `clear_sub_state_transition`.
- `src/config.py`: `HydraFlowConfig.uses_fable_director`, `HydraFlowConfig.director_shadow_enabled` (the live kill switch), `HydraFlowConfig.director_shadow_usd_ceiling` (the aggregate spend bound), `HydraFlowConfig.effective_driver_max_in_flight`, `HydraFlowConfig.driver_stage_cap_total` — the binding `max_in_flight` ≥ stage-cap-total floor from the ADR-0094 narrowing (i).
- `src/issue_store.py`: `_STAGE_PRIORITY`, `IssueStore._compute_stage_map`.
- `src/pr_manager.py`: `PRManager.swap_pipeline_labels`.
- `src/hydraflow_gateway/keys.py`: `VirtualKeyStore`.
- `src/process_group.py`: `kill_process_group`.
- `src/director_sandbox.py`: `DIRECTOR_ENV_ALLOWLIST`, `DIRECTOR_DENIED_TOOLS`, `build_scrubbed_env`, `director_sandbox`, `turn_failed`, `last_init_frame`, `assert_observed_surface`, `SurfaceVerdict`, `ProbeEvidence` — S1/S3/S4/S5 (#11537).
- `src/director_turn_runner.py`: `DirectorTurnRunner`, `DirectorTurnResult`, `render_capsule_prompt`, `extract_command_json` — the director's spawn, delegated to `SubprocessRunner.run_simple` for S6's reap; S1's allow-list over the parent environment and S2's per-turn minted key live here.
- `src/director_broker.py`: `ShadowDispatchBroker`, `ShadowDispatch`, `BrokerVerdict` — C7 applied to director-requested dispatches, with no dispatch path.
- `src/fable_director.py`: `FableDirector`, `OBSERVABLE_OUTCOMES` — the shadow observer, its capsule reconstruction, its fail-closed boundary, and the real-boundaries-only rule that keeps the agreement rate uncontaminated.
- `src/director_shadow_log.py`: `ShadowObservationLog`, `ShadowObservation`, `ShadowAgreement`, `TurnFailure`, `classify_agreement` — the comparison record B5's bar is measured from.
- `src/dashboard_routes/_scheduling_routes.py`: `GET /api/scheduling/status` — desired vs effective scheduling mode and the hypothetical worker tree.
- `src/plan_broker.py`: `PLAN_TIER_CATALOG`, `CAPABILITY_TIERS`, `PLAN_TIER_CATALOG_REVISION`, `DIRECTOR_TURN_FAMILY`, `PlanRouteDecision`, `PlanRouteOutcome`, `PlanRouteRule`, `PlanRouteSource`, `PlanRouteReason`, `resolve_plan_model`, `plan_canary_repo`, `plan_canary_armed`, `plan_canary_covers`, `plan_roles_for_plan_phase`, `PlanCanaryLatch` — the canary's pure decision layer (#11541).
- `src/plan_worker_runner.py`: `PlanWorkerRunner`, `build_plan_worker_prompt`, `_spawn_plan_worker` — the one place a brokered child is started, seam-declared in `SANDBOX_SEAMS`.
- `src/route_enforcement.py`: `enforce_director_route`, `DIRECTOR_PRINCIPAL` — ADR-0141 §D1's named gap, closed.
- `src/gateway_mint_client.py`: `bound_model_for` — which model a route-bound lease commits its spawn to.
- `src/config.py`: `HydraFlowConfig.fable_plan_canary_repo` (the one-action switch), `fable_plan_worker_timeout_seconds`, `fable_plan_canary_armed`.
- `src/implement_broker.py`: `CANARY_PHASE`, `FenceBreach`, `FENCE_REJECTIONS`, `WorktreeState`, `worktree_probes`, `worktree_state_from_reads`, `worktree_diff_digest`, `check_worker_fence`, `WriterLeaseRegistry`, `needs_writer_lease`, `Hibernation`, `hibernation_reason`, `implement_canary_repo`, `implement_canary_armed`, `implement_canary_covers`, `implement_roles_for_implement_phase`, `resolve_implement_model`, `writer_lease_for` — the Implement canary's pure decision layer (#11542).
- `src/implement_worker_runner.py`: `ImplementWorkerRunner`, `WorktreeMeasurement`, `build_implement_worker_prompt`, `hibernation_refusal`, `_spawn_implement_worker` — the one place a fenced writer is started, seam-declared in `SANDBOX_SEAMS`.
- `src/plan_broker.py`: `resolve_worker_model` — the phase-parameterised resolver both canaries share, so one tier table answers both.
- `src/config.py`: `HydraFlowConfig.fable_implement_canary_repo` (the second one-action switch), `fable_implement_worker_timeout_seconds`, `fable_implement_canary_armed`.
- `scripts/director_capability_probe.py` — the probe; `tests/fixtures/director/director_capability_probe_evidence.json` — its sanitized evidence.
