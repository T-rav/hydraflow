# Selectable classic and Fable-directed scheduling

**Status:** design proposal (2026-08-20). **Decision requested:** keep the
current scheduler as the default, build deterministic issue ownership, then add
an issue-scoped Fable director that invokes Opus and Sonnet workers through the
same HydraFlow workflow. **Related:** ADR-0002, ADR-0099, ADR-0111, ADR-0124,
and the IssueDriver v2 design.

## The product choice

The operator should be able to choose:

| Mode | Behavior |
|---|---|
| **Classic** | HydraFlow's independent triage, plan, implement, review, and HITL pools each start a fresh configured worker. |
| **Fable director** | One logical Fable session owns the continuity of one issue and invokes specialist Opus/Sonnet workers for the legal workflow steps. |

Fable mode should feel like this:

```text
Issue admitted
    |
Fable director (issue-scoped, long-context coordinator)
    |
    +-- invoke Sonnet planner / explorer workers
    +-- invoke Opus judgment or architecture worker
    +-- invoke Sonnet implementer workers
    +-- invoke independent Opus reviewer
    +-- request another worker or yield at CI/HITL
    |
HydraFlow validates artifacts, advances labels, gates merge, and checkpoints
```

That is genuinely Fable invoking Opus and Sonnet workers. The safety ruling is
that it invokes them through a narrow HydraFlow dispatch tool/broker. Fable
chooses the role and allowed model requirement; HydraFlow creates the actual child with
the correct worktree, prompt contract, provider/account route, virtual key,
budget, telemetry, and process ownership.

| Dimension | Classic | Fable director |
|---|---|---|
| Throughput | High independent stage parallelism | Lower initially; one directed issue slot per repo |
| Context continuity | Reconstructed from durable artifacts each stage | Strong within one issue, with artifact-backed reconstruction |
| Coordination cost | No parent-model spend | Additional Fable turns plus workers |
| Adaptive fan-out | Fixed phase logic | Fable can choose Sonnet/Opus worker mix within catalog/budgets |
| Recovery maturity | Existing behavior | Requires fenced IssueDriver and boundary checkpoints |
| Provider/account flexibility | Per-spawn today | Preserved only through brokered children |
| Best fit | High-volume predictable work | Complex issues where cross-stage judgment and adaptive delegation pay for the parent |

## Separate scheduling from execution

There are two independent backend choices:

| Scheduling model | Execution runtime | Support |
|---|---|---|
| `phase_requeue` | `stage_subprocess` | Existing Classic default |
| `issue_controller` | `stage_subprocess` | Deterministic foundation |
| `issue_controller` | `fable_director` | New Fable mode |
| `phase_requeue` | `fable_director` | Invalid; two competing owners |

The UI can present two simple presets—Classic and Fable director—while the
backend retains these orthogonal fields. The deterministic `issue_controller`
must land before Fable so one issue cannot be simultaneously owned by the old
phase pools and a parent session.

## Current architecture

```text
GitHub labels (durable stage truth)
        |
IssueFetcher -> IssueStore queues / _in_flight / _active
        |
        +-- Triage loop -> TriageRunner process
        +-- Plan loop -> PlannerRunner process
        +-- Ready loop -> AgentRunner process
        +-- Review loop -> ReviewRunner process
        +-- HITL loop -> HITLRunner process
                            |
                     worktree / PR / CI
```

Each phase independently polls, claims, runs, relabels, and releases work. Plan
and implementation use refilling pools; review has its own slot-filling pool;
HITL has a separate semaphore. Cross-stage continuity is stored in issue
comments, labels, plans, state, worktrees, PRs, CI, and convergence records—not
in one model conversation.

That is recoverable and easy to reason about, but it repeatedly rebuilds context
and has no single issue-level reasoner deciding when to fan out, use a stronger
worker, or carry a concern from plan through implementation.

## Non-negotiable invariants

Both modes preserve:

- GitHub labels as authoritative inter-stage state;
- local compare-and-set ownership and explicit in-flight/active claims;
- hard stage/global WIP, fan-out, time, token, and dollar caps;
- one fenced issue worktree with at most one active writer, plus a distinct
  child identity for every worker;
- project/repository/role routing policy resolved independently per child;
- a short-lived gateway key per child, never a real provider key in Fable;
- unchanged role prompts and output markers;
- code-owned retry, acceptance, quality, escalation, PR, CI, and merge gates;
- fresh independent review, not implementation self-review;
- a stop fence after which no director or child may spawn;
- recovery from canonical artifacts without requiring vendor session history.

## Deterministic foundation: IssueDriver

The IssueDriver v2 design exists but is not yet the production scheduling
runtime. Its spec also predates ADR-0107 and still describes Discover/Shape as
standalone phases. Reconcile that design, then build:

```text
SchedulingPolicy + Governor
        |
DriverManager -- one fenced IssueDriver per admitted issue
        |
        +-- canonical state and label reconciliation
        +-- stage caps, global WIP, budget, stop/preemption
        +-- Classic stage runner OR Fable director
        +-- checkpoint and durable boundary commit
```

The driver is the authority. Fable is one execution runtime attached to it.
This avoids handing a conversation ownership of the queue before the code has a
durable issue-level owner and recovery boundary.

## Fable director architecture

```text
IssueDriver(issue, driver_id, epoch)
        |
        +-- DirectorCapsule (bounded canonical context)
        |
        +-- FableDirectorPort
                 |
                 +-- dispatch_worker(role=planner, model=claude-sonnet)
                 +-- dispatch_worker(role=architect, model=claude-opus)
                 +-- dispatch_worker(role=implementer, model=claude-sonnet)
                 +-- dispatch_worker(role=reviewer, model=claude-opus)
                 |
                 +-- DispatchBrokerPort
                        +-- validates request and live stage
                        +-- resolves project/role/account/model policy
                        +-- launches existing role runner
                        +-- mints/revokes child virtual key
                        +-- returns typed artifact/result receipt
```

### Fable really chooses the workers

The parent may select from a code-owned worker catalog. A first catalog could
include:

| Worker role | Default model requirement | Purpose | Authority |
|---|---|---|---|
| explorer | literal Sonnet | Read-only codebase/research fan-out | Artifact only |
| planner | literal Sonnet | Draft or refine the implementation plan | Plan proposal |
| architect/judge | literal Opus | Resolve high-risk design or ambiguity | Advisory verdict |
| implementer | literal Sonnet | Execute one bounded implementation slice | Worktree changes |
| debugger | literal Opus/Sonnet or provider-neutral class by policy | Diagnose a failed gate | Fix proposal/change |
| test-adequacy | literal Opus | Challenge missing cases and boundaries | Advisory verdict |
| reviewer | literal Opus, fresh context | Independent review | Existing review verdict |

The catalog defines allowed phases, read/write scope, prompt builder, output
schema, default model requirement, eligible provider/account routes, maximum
concurrency, and budget. A model requirement is either a literal family
(`claude-opus` / `claude-sonnet`) or a provider-neutral capability class
(`high-reasoning` / `balanced`). Literal requirements must resolve to an actual
Opus or Sonnet model; a GLM model is never reported as Sonnet.
Fable may choose within the catalog; it cannot invent `Bash`, arbitrary models,
credentials, labels, or tools.

### One logical Fable session per issue

- Never reuse a Fable session across issues or repositories.
- Initially allow one active Fable-directed issue per repository.
- Each turn may be a new `claude -p`, optionally
  `--resume <vendor_session_id>`; the OS process is disposable.
- `vendor_session_id` is a cache hint, not HydraFlow's factory session id and
  not ownership.
- Every turn receives a canonical capsule sufficient to reconstruct from
  scratch if resume fails.
- Hibernate at CI, HITL, diagnostic, or external review waits; release compute
  and credentials rather than keeping a parent alive for hours.
- Rotate on age, context, turn count, model/settings hash changes, suspicious
  output, failed resume, or worktree drift.

### Narrow parent tools

The Fable process can:

1. inspect bounded canonical issue/phase state;
2. invoke an allowed Opus/Sonnet worker through `dispatch_worker`;
3. inspect typed worker receipts/artifacts;
4. recommend the next legal action or yield.

It cannot receive raw provider credentials or the gateway control token, mutate
labels directly, approve/merge, run unrestricted GitHub commands, or write
outside an explicitly granted worktree. Python decides whether a child result
satisfies the next state transition.

The director does not use HydraFlow's ordinary agent CLI profile. It runs in a
contract-only sandbox with an empty/non-project working directory, isolated
settings and home, scrubbed environment, constrained egress, and no Bash,
filesystem, GitHub, MCP, project hook, plugin, skill, or ambient OAuth/keychain
access. Its only credential is a short-lived parent-scoped virtual model key
that cannot mint child keys or call worker accounts. The process can read only
the bounded capsule and write only its schema-constrained command to stdout.
Sandbox construction fails closed; falling back to the current
`bypassPermissions` command builder is forbidden.

### Turn/receipt transport

The production brokered mode does not require an interactive MCP server or a
hidden in-session Task tool. Each disposable Fable turn uses a strict,
extra-fields-forbidden JSON contract:

1. HydraFlow starts `FableDirectorRunner` with a `DirectorCapsule` plus receipts
   from the previous turn.
2. Fable returns one `DirectorCommand`: a bounded batch of
   `dispatch_workers`, `yield`, or `finish`.
3. The Fable process exits. HydraFlow validates the command, executes accepted
   workers through `DispatchBrokerPort`, and records typed receipts.
4. The next Fable turn receives those receipts, optionally using
   `--resume <vendor_session_id>`; fresh reconstruction is always valid.

Framing uses the CLI's JSON output mode plus a Pydantic parser and an explicit
schema version. Cancellation owns and reaps the current Fable process group;
worker cancellation remains owned by the broker. There is no socket, bearer
capability, gateway control token, or arbitrary IPC surface inside the model
session. The parent virtual key is account/model/purpose bound and the gateway
rejects worker/data intents under it. A later native-child experiment must
separately define and test its MCP/Task transport and capability boundary.

### Worktree ownership

The issue owns one canonical worktree, matching current implementation/review
semantics. The driver grants a fenced single-writer lease to at most one
write-capable worker at a time. Sequential implementer/debugger workers continue
in that same worktree and validate the expected base/head/diff digest before
writing. Read-only explorers/judges receive a read-only snapshot or restricted
view and cannot acquire the writer lease.

Parallel write workers, child branches, and cherry-pick/integration are not v1.
They require a separate merge protocol and conflict evidence before the catalog
may advertise concurrent implementation fan-out.

## Brokered versus native subagents

Two transports can sit behind `dispatch_worker`:

### Brokered worker — production target

HydraFlow launches the existing `PlannerRunner`, `AgentRunner`, `ReviewRunner`,
or HITL runner as a child process. From Fable's point of view it invoked the
worker; from the kernel's point of view the child retains every current safety
and observability boundary.

This supports a Fable parent on one account/provider invoking a literal Opus
reviewer on Anthropic and a provider-neutral balanced implementer on z.ai,
because the broker resolves each child separately. If Fable requests a literal
Sonnet implementer, the broker must select an actual Sonnet route or reject the
request; it cannot silently substitute GLM.

### Native Claude Task child — later constrained experiment

Fable directly invokes a Claude Task/agent child. This can be cheaper and share
context more naturally, but native children inherit the parent's runtime
security envelope. They do not automatically get a separate gateway key,
provider/account route, worktree, complete telemetry, or independent process
ownership.

Native workers may be enabled later only for same-provider, low-risk/read-only
fan-out after a sandbox proves identity, transcript, cost, cancellation, and
filesystem boundaries. Independent review and any child needing a different
provider/account remain brokered. The UI should show which transport each child
actually used.

## Typed contracts

All control I/O is schema-versioned. Free-form reasoning can explain a decision
but never causes a side effect.

### `DriverLease`

```text
driver_id
epoch
repo_slug
issue_number
expected_stage
phase_attempt
expires_at
```

Every director and broker action validates driver id, epoch, expected live
label, and phase attempt. Recovery increments the epoch, fencing a stale parent
and late worker results.

For v1 require one active `RepoRuntime` owner and an OS/file repository lock.
This is not a distributed lock. Multiple factory hosts for one repository need
a shared CAS/lease service before Fable mode can be enabled.

### `DirectorCapsule`

- schema version, repository, issue, driver/epoch, phase and attempt;
- issue goal plus accepted plan/artifact references;
- live label, PR, CI, and last verified outcome;
- worktree base/head/diff digest;
- allowed catalog entries and remaining budgets;
- effective route-policy revision and route availability summaries;
- bounded prior receipts/findings;
- stop/drain state.

No ambient secrets, raw provider keys, or unbounded repository dump.

### `WorkerDispatchRequest`

```text
request_id
driver_id / epoch / phase_attempt
worker_role
model_requirement.kind = literal_family | capability | concrete_model
model_requirement.value = claude-sonnet | claude-opus | balanced
                          | high-reasoning | <approved concrete id>
task_contract
reason
expected_route_policy_revision
idempotency_key
```

This `{kind, value}` object is the canonical wire shape; colon-joined forms are
display shorthand only. The broker resolves the requirement to an allowed concrete model and
provider/account route. Literal families cannot cross-map to GLM. Fable does
not supply a raw credential or arbitrary model id.

### `WorkerReceipt`

- accepted/rejected/expired/superseded and deterministic reason code;
- child spawn id and parent-driver lineage;
- actual worker role, transport, tool, requested/served model, transit,
  upstream/account alias, and policy revision;
- artifact/result digest and output-contract verdict;
- timestamps, usage/cost, and terminal status.

### `DriverCheckpoint`

Persist the last committed phase, lease epoch, capsule digest, outstanding
request ids, receipts, optional vendor session id, and rotation/fallback reason.
Never reconstruct ownership or phase state from a transcript.

## Boundary transaction

For every phase:

1. validate worker output and canonical side effects;
2. persist the bounded artifact/result using an idempotency key;
3. compare the expected live GitHub stage and swap the label—the durable commit;
4. append the driver checkpoint/audit record;
5. only then allow Fable to invoke the next worker.

A crash before the label safely replays the idempotent step. A crash after the
label recovers from label truth even if the audit cache lags.

Before any child launch the broker also rejects stop/drain, stale epoch, stale
phase attempt, changed live label, unavailable account/route, exhausted
credit/budget, dependency or overlap conflict, and stage/WIP/fan-out overflow.
The final local check and ownership claim are atomic. Cleanup releases only the
exact ownership token it still owns.

## Keep review independent

The reviewer is an Opus worker invoked through the same catalog, but it receives
a fresh external process/session and canonical issue/diff evidence. It does not
share the implementer's conversation. Fable cannot select a weaker reviewer,
hide findings, approve, or merge. Existing reviewer verdict parsing and merge
gates remain authoritative.

## Routing-policy interaction

The proxy policy layer designed after this proposal resolves every child from
project/repository, role, provider/account health, model allowlist, priority,
and fallback rules. Fable can see the effective route and availability so it can
choose when and which tier to invoke, but cannot override the resolution.

Example: project X requires z.ai for provider-neutral balanced/high-reasoning
workers but an Anthropic account for a literal Opus independent reviewer. One
Fable director can request both classes; the broker independently mints each
correctly bound child key and records the policy revision. If project policy
locks every role to z.ai, a literal Opus request is incompatible and fails or
holds—it is never relabeled as a GLM “Opus” worker. Neither the Fable parent nor
any worker receives a real upstream key.

## Settings and operator UI

Persist restart-required backend fields:

```text
scheduling_model = phase_requeue | issue_controller
execution_runtime = stage_subprocess | fable_director
fable_worker_transport = brokered | hybrid_native
```

Present two top-level presets:

- **Classic** = phase requeue + stage subprocess;
- **Fable director** = issue controller + Fable director + brokered workers.

“Hybrid native” remains an advanced experimental toggle. Reject invalid
combinations during config load, and display desired versus currently effective
mode so a restart-required edit is not presented as live.

Bounded knobs:

- Fable model (default `claude-fable-5`);
- one active Fable issue per repo initially;
- permitted worker roles, literal Opus/Sonnet requirements, and separate
  provider-neutral capability mappings;
- maximum concurrent children, children per turn, and delegation depth;
- issue token, dollar, and wall-clock budget;
- parent context/turn/session-age caps;
- session resume enablement;
- boundary-only fallback to classic subprocess execution;
- phase canary allowlist, beginning with Plan.

The operator panel should show the active issue/driver/epoch, Fable turn and
health, worker tree, worker role/tier/transport, effective project route,
requested/served model, account alias, budgets, receipts, checkpoint age, and
fallback/rotation reason. It must never display prompts, virtual keys, control
tokens, or provider credentials.

## Delivery plan

### P0 — reconcile architecture and probe Claude capabilities

- Update the IssueDriver spec for ADR-0107 and current states.
- Write an ADR for Fable-directed issue execution; cite ADR-0099/0111/0124.
- Probe session-id capture/resume, session storage isolation, forwarded native
  child events, model/version mismatch, process-tree teardown, and key expiry.
- Define the lease, capsule, worker request, receipt, checkpoint, and lineage
  schemas plus the code-owned worker catalog.

### P1 — deterministic IssueDriver

- Add `scheduling_model`, default classic.
- Implement `SchedulingPolicy`, `DriverManager`, and fenced `IssueDriver` using
  existing fresh stage runners.
- Expose explicit single-item phase adapters; do not call batch polling entry
  points from the driver.
- Enforce labels, idempotency, recovery, WIP/stage caps, stop fencing, and
  boundary-only preemption.
- Reconcile or disable AutoAgent as a second owner in controller mode.
- Canary this layer before involving Fable.

### P2 — Fable and broker shadow mode

- Add fakeable `FableDirectorPort`, `DispatchBrokerPort`, and worker catalog.
- Let Fable choose hypothetical Sonnet/Opus workers from canonical capsules,
  while the deterministic controller still executes.
- Record agreement, invalid requests, context growth, resume failures, worker
  mix, cost, latency, and counterfactual outcome.
- Build the operator comparison/status view.

### P3 — active Plan canary

- Permit one Fable-directed issue in one repository.
- Let Fable invoke brokered Sonnet planner/explorer and Opus architecture/judge
  workers.
- Keep triage, implementation, review, HITL, and merge classic.
- Prove parent/child crash, stale lease, live label change, policy revision,
  account outage, credit pause, stop, resume loss, and fallback paths.

### P4 — implementation and correction loops

- Add brokered Sonnet implementer workers and policy-selected Opus/Sonnet
  debuggers.
- Preserve one fenced issue worktree and mint a distinct virtual key and child
  identity for every write-capable worker.
- Hibernate at CI/diagnostic/HITL waits and reconstruct at resume.
- Keep independent Opus review external.

### P5 — review and HITL widening

- Add fresh brokered Opus review and configured HITL workers while keeping
  verdict, escalation, CI, and merge authority in code.
- Widen one stage at a time based on evidence; retain boundary-only fallback.

### P6 — optional native children

Canary native Task children only for same-provider, low-risk/read-only fan-out.
Any worker requiring a different provider/account, an isolated write worktree,
or independent review remains brokered.

## Likely implementation surfaces

Decision/config:

- `docs/superpowers/specs/2026-07-20-issue-driver-v2-runtime-phase-spec-design.md`
- a new Fable-directed-execution ADR
- `src/config.py`, `src/settings_registry.py`
- new scheduling/execution runtime enums and worker-catalog modules

Driver/kernel:

- new `src/scheduling_policy.py`, `src/driver_manager.py`, `src/issue_driver.py`
- `src/orchestrator.py`, `src/service_registry.py`
- `src/models.py`, `src/state/_driver.py`, `src/state_restorer.py`
- `src/issue_store.py`, `src/phase_utils.py`
- single-item adapters in triage, plan, implement, review, and HITL

Director/broker:

- new `src/fable_director.py`, `src/director_broker.py`,
  `src/director_checkpoint.py`, and `src/worker_catalog.py`
- `src/ports.py`, `src/agent_cli.py`, `src/runner_utils.py`,
  `src/base_runner.py`
- tracing/telemetry/rollup support for explicit parent-child lineage
- optional gateway `parent_spawn_id` / `driver_id` lineage through mint/ledger

API/UI/tests:

- control status/config routes and models;
- generic settings plus effective director/worker-tree status;
- fake director and broker ports in MockWorld/sandbox;
- architecture port/fake parity and generated diagrams.

ADR-0124 is precedent, not the implementation seam. Its Fable goal supervisor
is a default-off monitor/nudge layer; repurposing it would collapse supervision
and pipeline ownership.

## Verification strategy

Unit and contract tests:

- configuration matrix and restart-required behavior;
- worker catalog role/tier/phase constraints;
- lease epoch, phase attempt, idempotency, and label/checkpoint reconciliation;
- malformed, duplicate, stale, forbidden, and over-budget worker requests;
- director sandbox construction, empty tool surface, isolated settings/home,
  egress restriction, environment scrubbing, and parent-key purpose binding;
- atomic ownership interleavings and late worker results;
- resume, rotation, reconstruction, and classic fallback;
- project route/account/model revision mismatch;
- global/stage WIP, fan-out, depth, time, token, and dollar caps.

Integration tests:

- Fable requests an Opus or Sonnet worker and the existing runner/output
  contract executes unchanged;
- the issue's fenced worktree admits only one writer while every child receives
  a separately minted/revoked gateway identity;
- Fable can request children routed to different policy-approved providers;
- reviewer context/model/provider remains independent;
- Fable timeout/crash falls back without duplicate dispatch;
- stop during a director turn, broker validation, child spawn, or child
  execution produces no late work and reaps all descendants;
- human/diagnostic/PR-unsticker label changes fence stale parents;
- no issue/session can see or dispatch another issue.

MockWorld and sandbox:

- Classic, deterministic controller, and Fable modes reach equivalent canonical
  outcomes for the same seed;
- route-back, HITL, CI wait, boundary crash, stale lease, provider/account
  outage, and policy change scenarios;
- adversarial requests for credentials, Bash, forbidden stages, excess fan-out,
  self-review, and silent model rewrite fail closed;
- assertions use fake-adapter state and durable receipts, not mock call counts;
- Docker scenario proves worktree/process isolation, gateway lineage, mixed
  Opus/Sonnet routing, and truthful operator status.

## Go/no-go measures

Do not widen Fable mode unless a real measured window shows:

- zero duplicate dispatches, ownership theft, or post-stop spawns;
- 100% of accepted workers have lineage, cost, and effective-route receipts;
- no increase in orphan process groups or unrecoverable worktrees;
- no worse terminal success or escaped-defect rate than the controller baseline;
- bounded parent cost, context growth, and p95 worker-decision latency;
- successful fresh reconstruction whenever resume is unavailable;
- measurable cycle-time, rework, context-cost, or convergence improvement.

“Fable sounds smarter” is not a release criterion.

## Final ruling

Offer Classic and Fable director as first-class operator choices. Under Fable
mode, one issue-scoped Fable session can invoke Opus and Sonnet workers through
the full HydraFlow workflow, but the invocation crosses a code-owned broker.
The conversation carries context; labels, leases, worktrees, routing policies,
artifacts, quality gates, receipts, and merge authority remain HydraFlow truth.
