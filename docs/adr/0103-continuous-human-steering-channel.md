# ADR-0103: Continuous Human-on-the-Loop Steering Channel

**Status:** Accepted
**Date:** 2026-07-05 (default-on)
**Enforcement:** enforced
**Enforced by:**
pytest:tests/test_human_steering.py
pytest:tests/test_human_steering_loop.py
pytest:tests/test_human_steering_actuator.py
pytest:tests/test_human_steering_state.py
pytest:tests/test_orchestrator_human_steering.py
pytest:tests/test_config_env.py

**Precedent:** Human supervisory control (Sheridan, *Telerobotics, Automation, and Human Supervisory Control*, MIT Press 1992) — a continuous human reference input to an otherwise autonomous process
**Divergence:** classical supervisory control assumes the supervisor can intervene continuously, including mid-operation, but here directives (steer/pause/resume/redo/abort) apply only at phase boundaries because there is no safe per-issue mid-phase interrupt (only a fleet-wide SIGKILL), and authorization is an explicit allowlist where an empty list honors nobody (receipt: ADR-0099, ADR-0092)

## Context

ADR-0099 §6 named four known-open control surfaces without deciding them. Surface #4 was:

> **Human-on-the-loop is discrete** — `pending_correction` + suspend/wake is single-shot, not a continuous reference channel.

Before this ADR, an operator's only way to influence a running issue was the HITL escalation path: the pipeline suspends, waits for a human comment, and wakes once. There was no way to nudge, pause, resume, replay a phase, or abort an issue that was not already escalated, and no way to do any of that more than once without a fresh escalation round-trip. The human reference input (bottom of the ADR-0099 control-loop diagram) fed the set-point only at HITL boundaries, not continuously.

## Decision

Close surface #4 with a **continuous `SteeringChannel`**: a live, per-issue path from operator GitHub comments into the running pipeline, built as a Sensor/Actuator pair rather than a single-shot suspend/wake.

### Directive grammar

A directive is a comment line beginning with `/` followed by a known verb, parsed by the pure function `human_steering.parse_directives` (no I/O):

| Verb | Kind | Effect |
|---|---|---|
| `/steer <text>` | Declarative | Sets `guidance`, folded into the next phase's prompt (any of the six phases) |
| `/pause` | Declarative | Sets `flow=paused` |
| `/resume` | Declarative | Sets `flow=running` |
| `/redo <phase>` | Imperative | Requests re-enqueue to `<phase>` |
| `/abort` | Imperative | Sets `flow=abort`, parks the issue |

Unknown verbs are ignored. Only the first line of a comment body is inspected for a verb; the rest of the body (for `/steer`) is free-text guidance.

### Sensor/actuator split

The channel is deliberately two halves that never share a process step:

- **Sensor — `HumanSteeringLoop`** (`src/human_steering_loop.py`). Each tick, for every active issue, fetches GitHub comments and calls `parse_directives` to derive a fresh `SteeringDirectives`, then persists the result as a `SteeringState` (`src/models.py`) via `state.set_human_steering`. Pure sensing: it never mutates issue phase, labels, or dispatch. The active-issue set is sourced from `store.get_active_issues()` (`src/service_registry.py`) — the same full-pipeline enumeration (queued/in-flight, triage through HITL) the actuator uses, not a narrower implement/review/HITL-only subset, so a directive posted while an issue is in discover/shape/plan is sensed too.
- **Actuator — the orchestrator's `_apply_human_steering`** (`src/orchestrator_hitl.py:OrchestratorHITLMixin._apply_human_steering`). Reads the persisted `SteeringState`, calls the pure decision function `human_steering.apply_steering` to compute a `SteeringDecision`, and enacts it verbatim: skip scheduling (paused), swap to the recoverable HITL label (abort), or re-enqueue to a phase (redo). Guidance is read separately, per builder, at each phase's prompt-build time (see "Fenced guidance reaches every phase" below).

This mirrors the ADR-0099 Sensor/Controller/Actuator roles directly: `HumanSteeringLoop` is the Sensor, `apply_steering` is the (pure, stateless) inner Controller, and the orchestrator's enactment is the Actuator. Keeping the pure decision logic (`parse_directives`, `apply_steering`) separate from both loops means the orchestrator and the sensor loop stay thin, and the directive grammar and precedence rules are unit-testable without any I/O.

### Phase-boundary application, not mid-phase interruption

Per the no-mid-phase-interruption constraint (only a fleet-wide `SIGKILL` exists — `base_runner.terminate_processes`), the actuator applies a decision only between phases: a running phase always completes first. `/pause` and `/abort` therefore take effect on the *next* phase transition, not instantly. This is a deliberate scope boundary, not an oversight: it avoids killing an in-flight subprocess mid-write, which the codebase has no safe way to do per-issue today.

### `created_at` idempotency

The comment contract exposes only `user.login`/`body`/`created_at` (`PRManager.list_issue_comments`) — no comment id. Declarative directives (`/steer`, `/pause`, `/resume`) are safe to recompute from the full comment history every tick (latest-wins), so they need no dedup mechanism. Imperative directives (`/redo`, `/abort`) must fire exactly once per comment, so they are gated by a per-issue `last_applied_ts` high-water-mark compared against each comment's `created_at`: a directive only fires if its timestamp is strictly newer than the mark, and firing advances the mark. Precedence within one poll is fixed: **abort > pause > redo > steer** (`apply_steering` checks flow states before considering `redo_phase`).

### Untrusted-text fencing (ADR-0092)

`/steer` and `/redo` free text originates from a GitHub comment — the same untrusted-input class ADR-0092 established fencing for. Guidance text is wrapped with `fence_untrusted("human-steering", human_guidance)` before it reaches any phase prompt, inside the standing `UNTRUSTED_DATA_PREAMBLE` regime: the agent is told to treat the fenced block as data describing what to prioritize, never as instructions that override tool or security policy. This closes the same class of prompt-injection risk ADR-0092 closed for issue titles/bodies/comments, applied to the new steering input surface.

`fenced_steering_guidance(...)` (`src/human_steering.py`) is the single choke point for this: it is the only call site of `fence_untrusted("human-steering", ...)`, so no phase builder can fold raw comment text into a prompt by forgetting to fence it.

### Fenced guidance reaches every phase

Guidance is folded into the prompt at every phase, not just IMPLEMENT, including both builders in phases that have two:

| Phase | Builder(s) reading `get_human_steering(...).guidance` |
|---|---|
| Discover | `src/discover_completeness.py`, `src/discover_runner.py` |
| Shape | `src/shape_coherence.py`, `src/shape_runner.py` |
| Plan | `src/planner.py` |
| Review | `src/reviewer.py`, `src/review_advisor.py` |
| Implement | `src/agent/_runner.py` |
| HITL | `src/hitl_runner.py` (cause-template prompt) |

Each builder calls `fenced_steering_guidance` independently — there is no shared prompt-assembly path across phases — so the fence invariant is asserted per builder in tests, not once globally.

### Authorization

Every directive is filtered through a single choke point: `human_steering.parse_directives` drops any comment whose `user.login` is not in `config.human_steering_authorized_users` before parsing a verb out of it. This is an explicit allowlist, not a denylist — **an empty allowlist honors nobody**. That is what makes default-on safe: until an operator is explicitly listed, the sensor runs (ticks, fetches comments) but never writes a non-default `SteeringState`, so the actuator never sees a directive to act on.

`human_steering_authorized_users` is a plain `list[str]` of GitHub logins, set via config (or an operator-maintained deployment override); it is not derived from repo-collaborator status. See "Deployment constraint" below.

### Deployment constraint

There is **no GitHub-collaborator-based authorization** — the allowlist is the only gate. This is a deliberate scope boundary, not an oversight:

- **Safe on trusted/private repos**, where the set of people who can comment is already close to the set of people who should be able to steer, and the allowlist is a small, deliberately-curated list of operator logins.
- **Not yet safe to enable on a public repo as-is.** Anyone can comment on a public issue; if an operator's login is compromised or spoofable in the surrounding tooling, or if the allowlist is accidentally over-broad, an outside comment could reach the actuator. Before enabling on a public repo, this needs (a) author-gating beyond the allowlist (e.g. requiring the directive-poster to also be the issue author or a verified collaborator) and (b) rate-limiting on directive processing, neither of which this ADR delivers.

## Current scope / follow-ups

This ADR closes surface #4 as a *mechanism*. The MVP-scope limitations from the initial landing (IMPLEMENT-only guidance, internal-stage-only `/redo` tokens, undifferentiated abort origin, and a narrower implement/review/HITL-only sensor active-set) have since been closed by follow-up work in this same feature branch — see "Fenced guidance reaches every phase" and the Sensor/Actuator split above, and the `/redo` dashboard-name translation and distinct `operator-abort` origin described in the Decision section's directive grammar and idempotency notes.

Remaining, deliberate scope boundaries:

1. **Phase-boundary application, not mid-phase interruption** (see above) — `/pause` and `/abort` take effect on the next phase transition, never mid-phase, because there is no safe per-issue mid-phase interrupt today (only fleet-wide `SIGKILL`).
2. **No GitHub-collaborator authorization** — see "Deployment constraint" above; a public repo needs author-gating and rate-limiting before this feature should be enabled on it.

The feature ships behind `human_steering_enabled` (default `True` as of 2026-07-05, env-controllable via `HYDRAFLOW_HUMAN_STEERING_ENABLED`) and the standard `enabled_cb` kill switch (ADR-0049). Default-on is safe because of the authorization allowlist above: an empty `human_steering_authorized_users` list means the sensor is live but inert (honors nobody) until an operator explicitly opts in a login.

## Consequences

- Surface #4 from ADR-0099 §6 is closed: human-on-the-loop is now a continuous channel (steer/pause/resume/redo/abort, re-evaluated every tick) rather than a single-shot suspend/wake.
- The Sensor/Actuator split means the directive grammar and precedence rules (`parse_directives`, `apply_steering`) are pure and fully unit-tested without needing a running orchestrator or live GitHub comments.
- Because application is phase-boundary-only, operators should expect a delay between posting `/pause` or `/abort` and it taking effect, bounded by the current phase's remaining runtime — this is a known, accepted latency, not a bug.
- Default-on shifts the safety argument from "off everywhere until an operator opts in" to "on everywhere but inert until an operator is allow-listed": the empty-allowlist-honors-nobody rule in `parse_directives` is now the load-bearing safety property, not the `human_steering_enabled` flag itself. Deployments that want the old fully-dark posture set `HYDRAFLOW_HUMAN_STEERING_ENABLED=false`.
- The remaining scope boundaries (no mid-phase interruption, no collaborator-based authorization) are deliberate, consistent with ADR-0099's framing of each known-open surface as "named, not decided" until an ADR closes it — this ADR closes the mechanism and the MVP ergonomic gaps, not the public-repo hardening story.

## Alternatives considered

- **Extend the discrete `pending_correction` suspend/wake mechanism instead of building a new channel.** Rejected: suspend/wake is single-shot by construction (one wake consumes the correction); making it re-entrant enough to support steer/pause/resume/redo/abort as independent, repeatable directives would have required rebuilding most of its internals anyway, with none of the benefit of a clean Sensor/Actuator split.
- **Apply steering directives immediately, including mid-phase.** Rejected: there is no safe per-issue mid-phase interrupt today (only fleet-wide `SIGKILL`); building one is high-blast-radius work out of scope for this ADR. Phase-boundary application is the safe, available seam.
- **Gate authorization on GitHub collaborator status instead of an explicit allowlist.** Rejected for this pass: collaborator status is a coarser, harder-to-audit proxy for "should be able to steer this issue" than an operator-curated list of logins, and conflating it with the allowlist would make the empty-list-honors-nobody safety property depend on repo permissions the steering feature doesn't otherwise touch. An explicit allowlist keeps the authorization surface small and independently auditable; collaborator-aware gating (needed for public-repo use) is future work, not folded in here.

## Related

- ADR-0099 (Orchestration as a Control System — names surface #4, this ADR closes it)
- ADR-0092 (Untrusted-text trust boundary — the fencing regime `/steer` guidance reuses)
- ADR-0049 (Kill-switch convention — `human_steering_enabled` + `enabled_cb`, default-on since 2026-07-05, env-controllable via `HYDRAFLOW_HUMAN_STEERING_ENABLED`)
- `src/human_steering.py:parse_directives`, `src/human_steering.py:apply_steering`, `src/human_steering.py:fenced_steering_guidance`, `src/human_steering_loop.py:HumanSteeringLoop`, `src/models.py:SteeringState`, `src/orchestrator_hitl.py:OrchestratorHITLMixin._apply_human_steering`, `src/config.py:HydraFlowConfig.human_steering_authorized_users`
