# ADR-0108: Deterministic-Simulation Fault Injection on the Sandbox Compose — Evaluation

**Status:** Proposed
**Date:** 2026-07-23
**Enforcement:** decision-of-record
**Recommendation:** **Defer** — conditional adopt-as-experiment (no spend authorized by this ADR)
**Related:** [ADR-0001](0001-five-concurrent-async-loops.md) (five concurrent async loops); [ADR-0002](0002-labels-as-state-machine.md) (labels as the pipeline state machine); [ADR-0003](0003-git-worktrees-for-isolation.md) (git worktrees for isolation); [ADR-0042](0042-two-tier-branch-release-promotion.md) (two-tier branch release promotion — the RC path this spike's headline property protects); [ADR-0099](0099-orchestration-as-a-control-system.md) (orchestration as a control system); the goal-seeking control-layer design spec (`docs/superpowers/specs/2026-07-23-bg-worker-control-theory-design.md`, §7) whose in-repo `hypothesis` work this complements.

> **Scope.** This is a **research + recommendation** ADR produced by the spike in
> issue #10361. It authorizes **no spend**, provisions **no Antithesis account**,
> and ran **no hypervisor**. The deliverables are (1) a determinism-gap audit of
> the sandbox compose, (2) a proof-of-value design sketch for one property, (3) a
> cost/access + CI-integration model, and (4) this adopt/defer/decline
> recommendation. Figures attributed to the vendor that could not be verified
> from primary docs are marked **(assumption)**.

## Context

Unit tests and property-based tests (`hypothesis`, landing in-repo per the
control-layer spec §7) search **inputs to pure functions**. They structurally
cannot exercise **concurrency + timing + fault schedules across the running,
integrated factory** — the bug class HydraFlow keeps hitting in production:
duplicate-issue parallel-build collisions, double-merge races, leaked process
groups under crash/cancel schedules, and RC fix cycles that close a PR that
would have merged.

A **deterministic-simulation testing (DST)** platform — [Antithesis](https://antithesis.com/)
is the reference commercial offering — targets exactly this. It runs the whole
system inside a **deterministic hypervisor** that virtualizes the guest kernel's
clock, entropy, thread scheduler, and network, then searches the space of
fault schedules and thread interleavings while checking `always` / `sometimes` /
`reachable` properties. Any violation is replayable **bit-for-bit** from the
seed that produced it.

The usual blocker for these platforms — *containerize the system and make the
run deterministic* — is **unusually close to solved here**. `docker-compose.sandbox.yml`
already boots the entire factory air-gapped (`networks: internal: true`), with
the LLM and GitHub behind in-memory Fakes (`src/mockworld/sandbox_main.py`,
`FakeGitHub` / `FakeLLM` / `FakeWorkspace` and the Ports). Antithesis's
entrypoint *is* a docker-compose file and its precondition *is* determinism, so
the gap between "what we have" and "what a DST run needs" is small — but it is
**not zero**, and quantifying it honestly is deliverable 1.

## Deliverable 1 — Determinism-gap audit

A true deterministic hypervisor makes the **guest** reproducible: it controls
the clock, `/dev/urandom` / `RDRAND`, and thread scheduling, so most in-process
nondeterminism is *absorbed by the platform*, not something HydraFlow must
remove. The determinism that a hypervisor **cannot** provide is for computation
that reaches **outside** the simulated VM — real DNS, real external sockets, a
real host clock, a real browser. The audit below is tiered accordingly.

### Tier A — genuine leaks past the deterministic boundary (close before a run is trustworthy)

| # | What leaks | Where (grounded in code) | Closability |
|---|-----------|--------------------------|-------------|
| A1 | **Raw subprocess spawns to the real network.** Several loops shell out to `gh` / `git ls-remote` / `claude -p` / `uv` / `docker pull`, **bypassing the Ports** so `FakeGitHub` never sees them. On the air-gapped network these produce *real* DNS-timeout / connection-refused behavior whose **timing** is a function of the host resolver and TCP stack, not the simulation. Today they are **disabled by config, not removed** — the sandbox only "works" because these code paths are switched off. | `src/mockworld/sandbox_main.py` — `SANDBOX_SEAMS` + `_apply_sandbox_config_overrides` document them: `staging_promotion_loop` (`gh pr list` / `gh run list`), `flake_tracker_loop` (`gh run download`), `merge_policy` (`gh pr view --json labels`), `approval_records` (`_list_recently_merged`), `contract_refresh_loop`, `auto_pr_preflight_gate` (`uv run …`), the repo-existence probe (`git ls-remote`, air-gapped by `_FakeRepoProber` in `air_gap_runner_sentinels`), and the transcript/research `claude -p` callers. | **Medium.** The seams already exist; each escape needs to be *routed through a Fake* (so the platform can inject faults on it) rather than config-killed (which merely shrinks the state space DST can explore). |
| A2 | **The compose crosses the host boundary in two places.** (a) A host-published port `127.0.0.1:5556:80` plus a `curl` healthcheck with `depends_on: condition: service_healthy` — host-side polling on the **real** host clock. (b) The `playwright` service drives a **real Chromium**; browser rendering/layout/font timing is a large, uncontrolled nondeterminism surface that a DST run has no reason to include. | `docker-compose.sandbox.yml` — the `ui` service's `ports:` mapping, the `hydraflow` `healthcheck:`, and the whole `playwright` service. | **Easy.** Add a `dst` compose profile that runs **only** the `hydraflow` SUT (the Fakes are already in-process) and drives it via the platform's Test Composer, dropping `ui` / `playwright` / the host port / the healthcheck. |

### Tier B — in-process nondeterminism the hypervisor absorbs (gaps only for a non-Antithesis / self-hosted harness, but they quantify "how close")

| # | What is nondeterministic | Where (grounded in code) | Closability |
|---|--------------------------|--------------------------|-------------|
| B3 | **No clock Port in production.** `FakeClock` and `subprocess_util.set_time_source` exist but are **test-only** — `sandbox_main` never installs them. Production reads wall-clock directly: `datetime.now(UTC)` across ~87 modules and `time.monotonic()` / `time.time()` across ~82 sites, with no injection seam. Additionally, the seed materializers back-date **relative** timestamps from `datetime.now(UTC)` at boot, coupling seed content to the boot instant. | `src/mockworld/fakes/fake_clock.py` (the unused seam) and `src/subprocess_util.py` (`set_time_source`); the boot-time back-dating in `src/mockworld/sandbox_main.py` (`materialize_expired_runs`, `materialize_epic_states`, `materialize_worker_heartbeats`, `materialize_worker_status_history`). | **Medium**, but **largely unnecessary under a true hypervisor** (the guest clock is virtualized and even fault-injectable). Required only for a cheaper self-hosted DST. |
| B4 | **Unseeded PRNGs.** GitHub rate-limit backoff jitter and the weighted-mix work-queue draw both use unseeded randomness in production. | `src/issue_fetcher.py` (`jitter = random.uniform(0.75, 1.25)`, global RNG); `src/issue_store.py` (`self._queue_rng = random.Random()`, unseeded in production by design). | **Trivial.** Seed from a platform-provided / env seed. |
| B5 | **`uuid4` identifiers.** Adjustment / event / retrospective IDs are `uuid4`-derived; `uuid4` reads `os.urandom`, so it is deterministic under the hypervisor and nondeterministic otherwise. These IDs surface in the events and assertions a replay would compare. | `src/health_monitor_loop.py` (`adj-{uuid4}`), `src/models.py` (`default_factory` uuid4 IDs), `src/phase_utils.py`, `src/retrospective_queue.py`. | **Trivial–medium.** Thread a seeded ID factory; unnecessary under a true hypervisor. |
| B6 | **Real daemon thread + async cadence.** The event-loop watchdog spawns a real `threading.Thread(daemon=True)` reading `time.monotonic()`; caretaker loops sleep on real time (60 s interval). Thread interleaving is exactly what a deterministic scheduler **explores** (a *feature* under Antithesis), but is a nondeterminism source for any lighter harness — and without hypervisor time-warp the 60 s cadence makes simulated time ≈ real wall-time (slow / expensive). | `src/event_loop_watchdog.py` (`threading.Thread(..., daemon=True)`); the `WorkerRegistryCallbacks(get_interval=…)` cadence wiring in `src/mockworld/sandbox_main.py`. | **N/A as a blocker** — note only. Under a true hypervisor this is the search surface, not a defect. |

**Bottom line of the audit.** The air-gap and Fakes get HydraFlow ~80% of the
way to a DST-ready image, which is genuinely rare. The residual leaks that a
hypervisor *cannot* fix are just **Tier A** (two items, both closable): the
raw-subprocess escapes and the multi-container / browser / host-port topology.
Everything in **Tier B** is absorbed by a true deterministic hypervisor and only
matters for a cheaper self-hosted alternative — but it usefully quantifies how
far from "any-DST-ready" (as opposed to "Antithesis-ready") the tree is.

## Deliverable 2 — Proof-of-value sketch: RC `RetryController` under injected CI faults

The single highest-value property (per issue #10361 and control-layer spec §5)
is the **RC merge-resilience invariant**: under injected CI flaps
(pending↔red↔green), GitHub 5xx, and rebase-races, the RC fix cycle must
**never close an RC that would have merged**, **never merge a genuinely-red RC**,
use **≤ 2 fix attempts**, and **always terminate**. `hypothesis` cannot reach
this — it is a property of the *running loop under an adversarial fault
schedule*, not of a pure function's inputs.

Design sketch (no account needed):

1. **Instrument** the RC fix cycle (`StagingPromotionLoop`, the `RetryController`
   from control-layer §5) with Antithesis SDK assertions at the decision points:
   - `always(not rc_closed_when_would_merge)` — the safety property.
   - `always(not rc_merged_when_red)` — the other safety property.
   - `always(fix_attempts <= 2)` — the bound.
   - `always(rc_cycle_terminates)` — liveness.
   - `sometimes(rc_reached_merged)` — a *viability* check: proves the workload
     actually drives a real merge some of the time, so the `always` assertions
     aren't vacuously green on a workload that never merges anything.
2. **Drive the workload** with the platform's Test Composer: cut an RC, then tick
   the promotion loop, while the platform is free to interleave.
3. **Inject faults** by having the platform flip `FakeGitHub` CI check state
   (pending↔red↔green) between ticks, return 5xx from the PR Port, and interleave
   a rebase-race (a competing merge advancing the base) — **prerequisite: Tier-A
   item A1**, i.e. route `staging_promotion_loop`'s two raw `gh` reads
   (`_list_merged_promotion_prs`, `_staging_ci_is_green`) through `FakeGitHub` so
   the platform has a fault surface instead of a config-killed no-op.
4. **Replay** any violation deterministically: Antithesis returns the seed that
   produced the failing interleaving; re-running the same seed reproduces the
   exact schedule bit-for-bit, turning a heisenbug into a fixture.

This is a design, not a run — but it is concrete enough to scope the pilot: one
loop instrumented, one workload, one fault set, five assertions, and one
Tier-A prerequisite (A1 for `staging_promotion_loop`). An optional throwaway
harness stub is intentionally **omitted** here to avoid adding un-wired `.py`
under CI; the pseudocode above is the deliverable.

## Deliverable 3 — Cost / access + CI-integration model

Grounded in Antithesis's public docs; unverifiable figures marked **(assumption)**.

- **Delivery model.** Commercial SaaS. The system is expressed as a standard
  **docker-compose (or k8s) manifest**; you push images to a registry Antithesis
  can pull, then **trigger runs via an HTTP POST** or the official
  [`antithesis-trigger-action`](https://github.com/antithesishq/antithesis-trigger-action)
  GitHub Action. Runs happen in a **hermetic environment with no internet
  access** — every dependency must be a containerized service or a mock. This is
  exactly HydraFlow's existing air-gap posture, which is why the fit is close.
- **Determinism model.** The supervisor virtualizes the guest, "simulat[ing]
  everything inside, including the system clock ticks," which lets it compress a
  large amount of logical application time into much less wall-clock time
  (time-warp) — directly relevant to HydraFlow's slow 60 s caretaker cadence (B6).
- **Pricing.** No public price list; contact-sales / enterprise posture, and
  historically invite-oriented **(assumption)**. Third-party signals: on-demand
  compute around **~$2.00 / CPU-core-hour** (AWS Marketplace listing)
  **(assumption on the exact rate)**; enterprise annual contracts commonly quoted
  in the **~$20k–$100k+/yr** range **(assumption — third-party estimate, not
  vendor-confirmed)**. The operative point for this ADR is that it is **paid,
  usage-metered on CPU-hours, and gated behind a sales conversation** — none of
  which this spend-free spike can exercise.
- **CI-integration shapes.** Two, both supported: **continuous** (trigger on
  every commit/merge, results reported back as Git commit-status contexts) and
  **gated / on-demand** (trigger via the Action on a label or schedule). For
  HydraFlow's two-tier model (ADR-0042), a full DST search is far too slow and
  costly to gate every PR; a **gated nightly or pre-RC-cut** trigger is the
  natural fit, complementing (never replacing) the per-PR `hypothesis` layer.

## Decision

**Defer.** Do **not** adopt Antithesis (or an equivalent commercial DST platform)
now, and authorize **no spend**. Record the evaluation and a concrete set of
entry conditions under which the defer flips to a **time-boxed, budgeted pilot**
("conditional adopt-as-experiment"). Decline is not warranted — the technical
fit is unusually strong and the bug class is real; unconditional adopt is not
warranted — there is no account, no authorized budget, and two Tier-A gaps
remain open.

**Entry conditions to flip Defer → time-boxed paid pilot (all four):**

- **C1 — close the Tier-A gaps.** Add a `dst` compose profile (SUT-only; no
  `ui` / `playwright` / host-port / healthcheck — A2) and route the
  raw-subprocess escapes through the Fakes so they become a fault surface
  instead of a config-kill (A1, at minimum for `staging_promotion_loop`).
- **C2 — land the zero-cost layer first.** Ship the in-repo `hypothesis`
  property tests from the control-layer spec (§7 / PR #10355). They cover the
  pure-unit stability search at no marginal cost and reduce what the paid DST
  must justify.
- **C3 — a concrete high-value target.** The RC `RetryController` invariant
  (deliverable 2) is instrumented and ready to search — a system-level bug class
  `hypothesis` structurally cannot reach.
- **C4 — access + a bounded budget.** Secure trial / OSS-program / evaluation
  access and an explicit, capped CPU-hour budget approved by the operator.

When C1–C4 hold, run a **single-property, time-boxed pilot** on the RC invariant
before any broader commitment, and supersede this ADR with an adopt/decline
decision informed by the pilot's findings.

## Consequences

**Positive:**

- The determinism-gap audit is now a durable artifact: the exact Tier-A leaks
  (A1 raw-subprocess escapes, A2 compose topology) and the Tier-B "how close"
  inventory are file-referenced, so a future pilot starts from a checklist, not
  a blank page.
- No money is committed against an unproven fit; the cheaper, complementary
  `hypothesis` layer (spec §7) is sequenced first.
- The audit surfaced concrete hardening wins that are worth doing **regardless**
  of Antithesis: routing the raw-subprocess escapes through Ports (A1) removes a
  recurring air-gap-wedge class (#9796 / #10140 / #10353), and seeding the PRNGs
  (B4) / threading a clock seam (B3) improves in-repo scenario reproducibility.

**Negative / Trade-offs:**

- The concurrency/timing/fault-schedule bug class stays covered only by
  after-the-fact incident response plus the pure-unit `hypothesis` layer until a
  pilot runs — the exact gap this spike names.
- Deferring risks the evaluation going stale: the compose, the seams, and the
  cost model all drift, so the pilot may need a re-audit if it is delayed far
  past this ADR.
- The Tier-A/B split relies on the vendor's determinism model behaving as
  documented (clock/entropy/scheduler virtualization). If a real pilot found the
  hypervisor does **not** absorb some Tier-B source, that item is promoted to
  Tier-A — a risk this paper evaluation cannot fully retire.

## Alternatives considered

- **Adopt now (buy + wire into CI).** Rejected: no account, no authorized spend,
  and Tier-A gaps open — an unconditional commitment ahead of the evidence a
  pilot would produce.
- **Decline outright.** Rejected: the containerize-and-determinize blocker is
  ~80% solved here (rare), the target bug class is real and recurring, and the
  entry conditions are cheap — declining would discard a strong-fit option for
  no benefit.
- **Build a self-hosted DST harness instead** (deterministic scheduler + mocked
  clock/RNG in-repo, no vendor). Noted but out of scope: it would require closing
  **all** of Tier B (B3–B6) that a true hypervisor otherwise absorbs, i.e. far
  more in-repo determinism work for a weaker search than the commercial
  supervisor provides. Revisit only if C4 (access) proves unobtainable.

## Related

- ADR-0001 (Five Concurrent Async Loops) — the concurrency whose interleavings a
  DST run would search.
- ADR-0002 (GitHub Labels as the Pipeline State Machine) — the label-race
  invariants (no double-build, no double-merge) are candidate properties.
- ADR-0003 (Git Worktrees for Issue Isolation) — the worktree double-checkout /
  leaked-process-group properties.
- ADR-0042 (Two-Tier Branch Release Promotion) — the RC promotion path the
  headline proof-of-value property protects.
- ADR-0099 (Orchestration as a Control System) — the control-layer frame this
  system-level fault injection complements.
- `docs/superpowers/specs/2026-07-23-bg-worker-control-theory-design.md` §7 — the
  in-repo `hypothesis` property tests this spike complements, not replaces.
- `src/mockworld/sandbox_main.py` — the air-gap seam registry (`SANDBOX_SEAMS`,
  `_apply_sandbox_config_overrides`, `air_gap_runner_sentinels`) that both
  enables the DST fit and documents the Tier-A A1 escapes.
- `docker-compose.sandbox.yml` — the DST entrypoint candidate; the Tier-A A2
  topology (host port, healthcheck, `playwright`) to profile out for a `dst` run.
- `src/mockworld/fakes/fake_clock.py` / `src/subprocess_util.py` — the unused
  clock seam behind Tier-B B3.
