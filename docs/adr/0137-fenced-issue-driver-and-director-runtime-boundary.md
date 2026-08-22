# ADR-0137: Fenced IssueDriver and director runtime boundary

**Status:** Accepted
**Date:** 2026-08-22
**Enforcement:** enforced
**Binds:** factory
**Supersedes:** none
**Superseded by:** none
**Amends:** ADR-0094 (Two-level convergence: Gate + ConvergenceLedger) — narrows its blocking-shepherd rejection to the convergence *outer loop*, leaving every other decision in ADR-0094 intact.
**Related:** [ADR-0001](0001-five-concurrent-async-loops.md) (the concurrency model a driver must not break), [ADR-0002](0002-labels-as-state-machine.md) (labels as the sole durable stage truth), [ADR-0099](0099-orchestration-as-a-control-system.md) (the servo/supervisory-controller vocabulary this realizes), [ADR-0107](0107-collapse-discover-shape-into-plan.md) (the live Triage → Plan → Implement → Review → HITL topology), [ADR-0110](0110-provider-harness-backend-split.md) and [ADR-0134](0134-per-repo-model-harness-selection.md) (per-repo provider routing the broker must resolve per child), [ADR-0124](0124-tier-2-goal-supervisor.md) (the default-off Fable goal supervisor this is deliberately *not* built on). Issues: #11533 (this phase), #11532 (the epic), #10038 / #10055 (the conflict), #11535 / #11537 (the phases this unblocks).

**Enforced by:**
pytest:tests/test_driver_contracts.py
pytest:tests/test_director_capability_probe.py
pytest:tests/regressions/test_issue_11533_stale_driver_states.py

**Precedent:** Fenced leases over a durable log — the epoch/fencing-token discipline for a single-writer owner whose liveness cannot be trusted (Chubby, Burrows 2006; Kafka's producer epoch; Lamport's "the lease holder may already be dead").
**Divergence:** classical fencing assumes the shared store enforces the token, but HydraFlow's durable store is the GitHub label set, which has no compare-and-swap and whose swap primitive is add-first-then-best-effort-remove (`src/pr_manager.py:PRManager.swap_pipeline_labels`), so the fence is enforced at the *admission* boundary instead and multi-label crash states are reconciled by the existing most-advanced-label-wins rule rather than prevented (receipt: #11533, and the adversarial panel on #10038).

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

ADR-0094 was deciding *how a two-level convergence fixpoint terminates*. In that context the blocking shepherd it rejected was a worker that **holds a slot while it walks an issue stage-to-stage**, which would have collapsed the ADR-0001 concurrency model into serialized per-issue execution and replaced the ledger with in-process state. That rejection stands: the convergence fixpoint is still distributed across the ADR-0001 loops, with `ConvergenceLedger` as shared truth and oscillation detection as the safety net. Nothing in ADR-0094's Decision section (D1 gate, D2 ledger, the storage/decision split, the lap budget) is touched.

What this ADR permits is a **different object with the same silhouette**: a driver that

- **never holds capacity while not working** (C4 — PARKED, HITL_WAIT, and label-write-failing drivers release their slot),
- **never becomes a second source of truth** (C1/C5 — the label is written at every boundary and re-read at every boundary), and
- **is admitted, fenced, and bounded by code**, not by a conversation (C6–C8).

A shepherd with those three properties is not the shepherd ADR-0094 rejected. It is an *execution-model* change — it changes when the next phase starts, not where truth lives — so the ADR-0001 concurrency model survives as a WIP-limited allocation of the same loops rather than a serialization of them.

The scope of the narrowing is exactly this sentence, added to ADR-0094's alternative: *"…in the context of the convergence outer loop. A fenced, WIP-capped, labels-authoritative driver is a distinct design and is governed by ADR-0137."*

### D2: The verdict is a conditional GO, and the condition is a runtime assertion

The rollout gate on #11533 is fail-closed: no-go unless the director sandbox, teardown, credential boundary, and recovery contract can be proven. The probe (`scripts/director_capability_probe.py`) attacked all four. Results, from the committed evidence in `tests/fixtures/director/director_capability_probe_evidence.json`:

| Proof | Lane | Verdict | What was actually observed |
|---|---|---|---|
| JSON framing | live | pass, constrained | Every line parses. **Two hazards**: one turn emitted 11 `system/init` frames under upstream retry, and `result.subtype` read `"success"` while `result.is_error` was `true`. |
| Session-id capture | live | pass | Vendor session id present on assistant and result frames, captured even on a failed turn. Distinct from HydraFlow's factory session id. |
| Resume loss | live | pass | `--resume <dead-id>` → exit 1, stderr diagnostic, a terminal `result/error_during_execution` frame with `is_error: true`, and **no assistant turn**. Fail-closed and always detectable. |
| Isolated settings/home | live | pass | `env -i` + disposable `HOME` + `CLAUDE_CONFIG_DIR` + empty cwd → zero MCP servers, zero plugins, memory path confined to the disposable config dir. A hostile `.claude/settings.json` and `CLAUDE.md` planted in the cwd were not loaded. |
| Environment scrubbing | hermetic | pass | Allow-list build drops provider keys, `GH_TOKEN`, the gateway control token, and `SSH_AUTH_SOCK`. |
| Process-tree teardown | hermetic | pass | A real two-level process tree spawned under `start_new_session`; `kill_process_group` left zero survivors. |
| Short-lived key expiry | hermetic | pass | A 60s virtual key resolved before TTL, was refused after, and the store retained only a SHA-256 digest. |
| No ambient tools/credentials | live | pass, constrained | **Credentials: clean** — no api key source, authentication failed outright, so the keychain/OAuth path does not cross the sandbox. **Tools: not clean by default** (below). |

Three findings are load-bearing and are what make this a *conditional* go.

**F1 — Isolation does not empty the tool surface.** A fully isolated turn still advertised 22 tools including `Bash`, `Write`, `Edit`, `WebFetch`, and `Task`. `--setting-sources project|user|omitted` made no difference.

**F2 — An allow-list does not narrow it, and the advertised list is incomplete.** `--allowedTools Read` left all 22 enabled: the flag is a *permission* filter, not a surface filter. Denying every one of the 22 advertised names still left `Glob` and `Grep` — tools the init frame never advertised. An empty surface is reachable (`--disallowedTools` over 22 + `Glob` + `Grep` → 0 tools), but a name-based deny-list is **fail-open across CLI upgrades**: a newly shipped tool is enabled by default and absent from the list.

**F3 — `apiKeySource` is not a trustworthy provenance signal.** It reported `none` both when no credential existed *and* when `ANTHROPIC_AUTH_TOKEN` was injected and demonstrably used. Nothing may gate on it.

**Therefore: GO, conditional on S4.** The sandbox is provable but not by construction — only by *verification*. The design is safe if and only if the runtime asserts the boundary it was handed rather than trusting the flags it passed. That is constraint S4, and `RejectionReason.SANDBOX_UNVERIFIED` exists so the failure has a first-class code rather than an exception path.

Had the tool surface been unreachable, or had an ambient credential crossed the sandbox, or had resume loss been silent, this ADR would have recorded a no-go. It records a go because the evidence supports one — with the constraint the evidence itself forced.

### D3: Driver constraints C1–C8

C1–C4 are carried forward from the #10055 spec. C5–C8 are new and exist because the adversarial panel falsified the spec as written.

- **C1 (label-at-every-boundary).** The driver writes the pipeline label via `src/pr_manager.py:PRManager.swap_pipeline_labels` at every stage-crossing transition, **before** spawning the next phase's sub-process. In-memory `driver_state` is a cache of the label, never a substitute.
- **C2 (resume-from-labels).** On boot, drivers are reconstructed from GitHub labels, then hydrated from `ConvergenceLedger`. No in-memory-only state gates recovery.
- **C3 (preempt at phase boundaries only).** Mid-sub-process preemption stays a non-goal. See B3 for the wait bound that makes this safe.
- **C4 (stage-aware WIP caps).** A global `max_in_flight` plus the existing per-stage caps, which the allocator respects rather than replaces.
- **C5 (reconcile-from-label).** New. See B1.
- **C6 (release non-working capacity).** New. See B2.
- **C7 (fenced admission).** New. Every dispatch passes `src/driver_contracts.py:admit_dispatch`, a pure function whose first matching rejection wins, so admission is deterministic and replayable.
- **C8 (boundary transaction ordering).** New. For every phase, in this order: validate worker output → persist the artifact under an idempotency key → compare the expected live label and swap it (**the durable commit**) → append the checkpoint/audit record → only then admit the next dispatch. A crash before the label safely replays the idempotent step; a crash after it recovers from label truth even if the audit cache lags. This ordering is what stops a ledger write that raced ahead of the label from corrupting replay with a phantom transition.

### D4: Director sandbox constraints S1–S6

- **S1 (contract-only process).** Empty non-project working directory, disposable `HOME` and `CLAUDE_CONFIG_DIR`, allow-list environment (`DIRECTOR_ENV_ALLOWLIST`). Sandbox construction fails closed; falling back to the `bypassPermissions` command builder is forbidden.
- **S2 (one credential).** The director's only credential is a short-lived parent-scoped virtual gateway key that cannot mint child keys or reach worker accounts. Real provider keys and the gateway control token never enter its environment. Proven by the environment-scrubbing and key-expiry proofs.
- **S3 (exhaustive deny-list).** The spawn passes `DIRECTOR_DENIED_TOOLS`, which must include names the CLI does not advertise (`Glob`, `Grep` today).
- **S4 (observed-empty assertion — the load-bearing one).** The runtime MUST parse the turn's last `system/init` frame and assert the `tools` array is **empty**. A non-empty surface is a hard failure returning `RejectionReason.SANDBOX_UNVERIFIED`; the director turn is discarded and no dispatch is admitted. This converts F2's fail-open deny-list into a fail-closed gate and is the condition on which D2's go depends.
- **S5 (framing discipline).** The parser tolerates repeated `system/init` frames (last-init-wins) and keys success on `is_error`, never on `subtype`. Both rules exist because F1's hazards were observed, not imagined.
- **S6 (disposable process tree).** Every director turn is spawned with `start_new_session=True` and cancelled via `kill_process_group`; worker cancellation stays owned by the broker.

### D5: The contracts are fixed here

`src/driver_contracts.py` fixes all ten contracts #11533 names — `WorkerRole`, `ModelRequirement`, `DriverLease` / `WriterLease`, `DirectorCapsule`, `DirectorCommand`, `WorkerDispatchRequest`, `WorkerReceipt`, `DriverCheckpoint`, `WorkerLineage`, and `WORKER_CATALOG` — as frozen, `extra="forbid"`, schema-versioned Pydantic models plus one pure admission function. #11535 and #11537 consume them unchanged.

Two invariants are enforced in the type system rather than in prose:

- **A literal family never resolves to another provider's model.** `ModelRequirement.satisfied_by` refuses a served model carrying a non-Anthropic marker, and `WorkerReceipt` rejects an accepted receipt whose served model does not satisfy the request. "GLM reported as Sonnet" is a validation error, not a silent relabel.
- **Review cannot be hidden or self-performed.** The reviewer catalog entry is marked independent of the implementer and may never hold worktree write scope; `admit_dispatch` returns `SELF_REVIEW_FORBIDDEN` for a reviewer spawned inside the implementer's lineage.

## The seven adversarial findings

**B1 — label read-back / cache-coherence discipline (C5).** The premise that an issue carries one unambiguous pipeline label is false: `swap_pipeline_labels` is add-first-then-best-effort-remove, so a crash mid-swap leaves two. C5 mandates three things. (a) *Boot reconciliation reuses the existing rule* — `src/issue_store.py:IssueStore._compute_stage_map` resolves a multi-label issue by `_STAGE_PRIORITY` most-advanced-wins. Because the swap always adds the *forward* label first, the tie-break biases correctly forward, so a mid-swap crash resolves to the newer stage. This logic already exists and is cited rather than reimplemented. (b) *The driver re-reads the pipeline label at every phase boundary*, and an externally changed label preempts its own state — otherwise the next C1 write clobbers an operator's manual drag, which ADR-0002 documents as the HITL escape hatch. `admit_dispatch` returns `LIVE_LABEL_CHANGED` for exactly this. (c) *DIAGNOSE ambiguity is resolved by rule*: DIAGNOSE shares `hydraflow-review` and writes no `SuspendRecord`, so a crash mid-DIAGNOSE is indistinguishable from a fresh REVIEW by label alone. The rule is **resume at the nominal state and re-detect the route-back fresh**, which is safe because route-back detection is a pure function of the PR's CI state and diff — re-running it is idempotent.

**B2 — capacity accounting for non-working slots (C6).** PARKED, HITL_WAIT, and label-write-failing drivers **release** their in-flight slot. The panel's adjudication is adopted verbatim: releasing does not undercut the model's benefit, because the benefit is *inter-phase latency within one issue's lifecycle*, a different quantity from *admission latency for a parked issue*. One slow human therefore cannot starve factory capacity. A semaphore-blocked driver **does** count against admission (it is working, merely queued). Label-write failure gets a bounded retry — 5 attempts, exponential backoff, 10-minute maximum slot hold — after which the driver escalates to HITL and releases. Re-admission uses the driver's original enqueue time as its priority key, so a released driver cannot be starved by newer arrivals.

**B3 — SchedulingPolicy/SchedulingView interface and the P0 wait bound.** `SchedulingView` is a frozen per-issue sensor record: issue number, priority, blast radius, driver state, wait time since admission request, current stage, and slot occupancy. `SchedulingPolicy.select(view) -> ranked candidates` is a pure control law over that frozen view — no I/O, replay-testable, the same shape as `src/queue_strategy.py`. **The P0 wait bound is stated, not left open**: worst case is one phase-boundary interval of the longest-running in-flight phase, because C3 makes every boundary a yield point and C6 releases non-working slots. With the implement phase's existing subprocess timeout as the ceiling, that bound is *one implement timeout*, and it is a hard number the canary must measure rather than a "per policy" hand-wave. Mid-sub-process preemption remains a non-goal; the panel explicitly warned against over-correcting into it.

**B4 — engage the prior rejection, and land the paperwork first.** This ADR is that engagement (D1), and it lands **before** any runtime code: #11533 is the gate on #11535 and #11537, and this phase ships no scheduling change. The panel's sequencing demand — supersession lands with or before the first runtime merge — is satisfied by construction rather than by promise.

**B5 — a quantitative proven bar, with the anti-pattern named.** The named anti-pattern is the `queue_strategy` same-day flip: build #10045 merged 05:19Z, guard #10053 at 14:33Z, default flip #10061 at 18:13Z, all on 2026-07-20. That must not recur. The bar to advance beyond shadow mode, all of which must hold over a measured window of **at least 20 completed issues and at least 7 days**:

- zero duplicate dispatches, zero ownership-theft events, zero post-stop spawns;
- 100% of accepted workers carry lineage, cost, and effective-route receipts;
- zero label-desync incidents (an issue whose label and committed checkpoint disagree after a settled window);
- no increase in orphan process groups versus the classic baseline;
- terminal success rate and escaped-defect rate no worse than the `issue_controller` baseline, not merely no worse than nothing;
- p95 worker-decision latency and parent cost bounded and reported;
- successful fresh reconstruction on every resume failure.

The flip PR must cite this evidence explicitly. A default flip in the same calendar day as the build PR is forbidden regardless of what the numbers say.

**B6 — split the phases and name a real crash-safety test.** The epic already splits the work (#11535 deterministic driver → #11537 shadow broker → #11541 plan canary → #11542 implementation → #11543 review/HITL). The behavioural test this ADR requires of #11535 is a **kill-mid-transition** test proving C8's ordering: kill the process between the artifact persist and the label swap, and between the label swap and the checkpoint append, and assert in both cases that recovery reaches the correct stage and that no ledger entry records a transition the label never committed. String-matching a spec, as `regression_issue_10038.py` does, cannot test this and is not a substitute.

**B7 — alternatives considered.** Two cheaper designs, evaluated rather than assumed away:

- *(a) Fix `enqueue_transition`'s back-of-queue insertion.* The eager path already exists; a promoted issue merely lands behind older same-stage work. This is a queue-ordering bug and fixing it removes most of the "up to `data_poll_interval` per hop" latency the #10038 lead cites. It is **complementary, not a substitute**: it does not produce a single traceable per-issue timeline and cannot express in-flight WIP. It should be fixed on its own merits regardless of this ADR.
- *(b) A stateless WIP-admission cap at Triage*, recomputed from label counts on boot with no in-memory ownership. This delivers finish-what-you-start without touching ADR-0002 at all, and is genuinely cheaper. It does not deliver per-issue continuity or adaptive delegation, which are the director's entire premise.

The controller's unique deliverables are therefore exactly two: a single traceable per-issue timeline, and in-flight WIP as a first-class quantity. **The "context re-derivation paid six times" cost is withdrawn from the justification** — `issue_controller` still swaps sub-processes per phase, so it does not address that cost, and leaving it in inflated the ROI.

## Consequences

- The #11532 epic is unblocked at its gate: #11535 and #11537 may proceed against fixed contracts.
- Every later phase inherits a fail-closed sandbox contract whose weakest link (F2) is named and gated (S4) rather than discovered in production.
- The contracts module is pure and importing it changes nothing, so the blast radius of this ADR's code is zero until a consumer exists.
- The design now costs more than the #10055 spec implied: S4's assertion, C5's re-read, C6's release-and-readmit, and C8's ordering are all real work that #11535/#11537 must carry.
- `apiKeySource` is unusable as a signal anywhere in the factory, not just here.

## Alternatives considered

- **Record a no-go.** Legitimate and explicitly permitted by #11533. Rejected on the evidence: the credential boundary held cleanly, teardown left zero survivors, resume loss is fail-closed and detectable, and the tool surface is reachably empty. The one fail-open finding (F2) has a cheap, verifiable mitigation. A no-go would have been manufacturing a negative.
- **Reverse ADR-0094 outright.** Rejected. Its gate/ledger decision is sound and untouched by this work; only the alternatives passage needed scoping. Narrowing is the smaller, more honest change.
- **Edit ADR-0094 in place.** Rejected — the repo rule requires a new ADR, and in-place editing would erase the record of why the rejection was correct in its original scope.
- **Trust the sandbox flags without S4's assertion.** Rejected. F2 proves the deny-list is fail-open across CLI upgrades; a design that trusts it would silently regain `Bash` on the next release.
- **Native vendor child-task API instead of a brokered worker.** Deferred, unchanged from the proposal. Native children inherit the parent's security envelope and get no separate gateway key, route, worktree, or process ownership.

## When to supersede this ADR

Supersede when the brokered canary produces evidence that falsifies a constraint — in particular if the S4 assertion proves unmaintainable against CLI churn, if the B3 wait bound is measured worse than one implement timeout, or if the B5 bar is met and the design graduates from canary to default.

## Source-file citations

- `src/driver_contracts.py`: `WorkerRole`, `ModelRequirement`, `DriverLease`, `WriterLease`, `DirectorCapsule`, `DirectorCommand`, `WorkerDispatchRequest`, `WorkerReceipt`, `DriverCheckpoint`, `WorkerLineage`, `WorkerCatalogEntry`, `WORKER_CATALOG`, `RejectionReason`, `admit_dispatch`, `DriverPhase`.
- `src/models.py`: `DriverState`, `SuspendRecord`, `ConvergenceLedger`.
- `src/state/_driver.py`: `DriverStateMixin`.
- `src/issue_store.py`: `_STAGE_PRIORITY`, `IssueStore._compute_stage_map`.
- `src/pr_manager.py`: `PRManager.swap_pipeline_labels`.
- `src/hydraflow_gateway/keys.py`: `VirtualKeyStore`.
- `src/process_group.py`: `kill_process_group`.
- `scripts/director_capability_probe.py` — the probe; `tests/fixtures/director/director_capability_probe_evidence.json` — its sanitized evidence.
