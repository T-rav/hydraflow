# ADR-0103: Continuous Human-on-the-Loop Steering Channel

**Status:** Accepted
**Date:** 2026-07-03
**Enforcement:** enforced
**Enforced by:**
pytest:tests/test_human_steering.py
pytest:tests/test_human_steering_loop.py
pytest:tests/test_human_steering_actuator.py
pytest:tests/test_orchestrator_human_steering.py

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
| `/steer <text>` | Declarative | Sets `guidance`, folded into the next IMPLEMENT prompt |
| `/pause` | Declarative | Sets `flow=paused` |
| `/resume` | Declarative | Sets `flow=running` |
| `/redo <phase>` | Imperative | Requests re-enqueue to `<phase>` |
| `/abort` | Imperative | Sets `flow=abort`, parks the issue |

Unknown verbs are ignored. Only the first line of a comment body is inspected for a verb; the rest of the body (for `/steer`) is free-text guidance.

### Sensor/actuator split

The channel is deliberately two halves that never share a process step:

- **Sensor — `HumanSteeringLoop`** (`src/human_steering_loop.py`). Each tick, for every active issue, fetches GitHub comments and calls `parse_directives` to derive a fresh `SteeringDirectives`, then persists the result as a `SteeringState` (`src/models.py`) via `state.set_human_steering`. Pure sensing: it never mutates issue phase, labels, or dispatch.
- **Actuator — the orchestrator's `_apply_human_steering`** (`src/orchestrator.py`). Reads the persisted `SteeringState`, calls the pure decision function `human_steering.apply_steering` to compute a `SteeringDecision`, and enacts it verbatim: skip scheduling (paused), swap to the recoverable HITL label (abort), or re-enqueue to a phase (redo). Guidance is read separately, at IMPLEMENT-prompt-build time (see Current scope below).

This mirrors the ADR-0099 Sensor/Controller/Actuator roles directly: `HumanSteeringLoop` is the Sensor, `apply_steering` is the (pure, stateless) inner Controller, and the orchestrator's enactment is the Actuator. Keeping the pure decision logic (`parse_directives`, `apply_steering`) separate from both loops means the orchestrator and the sensor loop stay thin, and the directive grammar and precedence rules are unit-testable without any I/O.

### Phase-boundary application, not mid-phase interruption

Per the no-mid-phase-interruption constraint (only a fleet-wide `SIGKILL` exists — `base_runner.terminate_processes`), the actuator applies a decision only between phases: a running phase always completes first. `/pause` and `/abort` therefore take effect on the *next* phase transition, not instantly. This is a deliberate scope boundary, not an oversight: it avoids killing an in-flight subprocess mid-write, which the codebase has no safe way to do per-issue today.

### `created_at` idempotency

The comment contract exposes only `user.login`/`body`/`created_at` (`PRManager.list_issue_comments`) — no comment id. Declarative directives (`/steer`, `/pause`, `/resume`) are safe to recompute from the full comment history every tick (latest-wins), so they need no dedup mechanism. Imperative directives (`/redo`, `/abort`) must fire exactly once per comment, so they are gated by a per-issue `last_applied_ts` high-water-mark compared against each comment's `created_at`: a directive only fires if its timestamp is strictly newer than the mark, and firing advances the mark. Precedence within one poll is fixed: **abort > pause > redo > steer** (`apply_steering` checks flow states before considering `redo_phase`).

### Untrusted-text fencing (ADR-0092)

`/steer` and `/redo` free text originates from a GitHub comment — the same untrusted-input class ADR-0092 established fencing for. Guidance text is wrapped with `fence_untrusted("human-steering", human_guidance)` before it reaches the implementer prompt (`src/agent.py`), inside the standing `UNTRUSTED_DATA_PREAMBLE` regime: the agent is told to treat the fenced block as data describing what to prioritize, never as instructions that override tool or security policy. This closes the same class of prompt-injection risk ADR-0092 closed for issue titles/bodies/comments, applied to the new steering input surface.

## Current scope / follow-ups

This ADR closes surface #4 as a *mechanism*, landed behind a kill switch, with these documented expansion points rather than full closure on every dimension:

1. **Fenced guidance is wired for the IMPLEMENT phase only.** `get_human_steering(...).guidance` is read exclusively in `src/implement_phase.py` and folded into the implementer prompt in `src/agent.py`. Plan, review, and HITL prompt-building do not yet read steering guidance. Extending fenced guidance injection to those phases is a follow-up, not part of this ADR's delivered scope.
2. **`/redo <phase>` currently accepts INTERNAL stage names**, not dashboard-facing names — the phase token is matched directly against `IssueStoreStage` values (`find`, `discover`, `shape`, `plan`, `ready`, `review`, `hitl`), which are internal pipeline vocabulary. An operator-facing translation layer (dashboard label → internal stage) is a follow-up.
3. **`/abort` parks to the existing recoverable `hitl_label`**, the same terminal label any other HITL escalation uses. There is no distinct operator-abort origin or cause recorded — an aborted issue is indistinguishable, at the label level, from an issue that escalated for any other reason. A dedicated abort origin/cause on the escalation record is a follow-up.

The feature ships behind `human_steering_enabled` (default `False`) and the standard `enabled_cb` kill switch (ADR-0049); it is off by default in every existing deployment until an operator opts in.

## Consequences

- Surface #4 from ADR-0099 §6 is closed: human-on-the-loop is now a continuous channel (steer/pause/resume/redo/abort, re-evaluated every tick) rather than a single-shot suspend/wake.
- The Sensor/Actuator split means the directive grammar and precedence rules (`parse_directives`, `apply_steering`) are pure and fully unit-tested without needing a running orchestrator or live GitHub comments.
- Because application is phase-boundary-only, operators should expect a delay between posting `/pause` or `/abort` and it taking effect, bounded by the current phase's remaining runtime — this is a known, accepted latency, not a bug.
- The MVP scope (IMPLEMENT-only guidance, internal-stage `/redo` tokens, undifferentiated abort origin) is deliberate: it ships the reference-channel mechanism now and defers the remaining polish to follow-up work, consistent with ADR-0099's framing of each known-open surface as "named, not decided" until an ADR closes it — this ADR closes the mechanism, not every ergonomic gap.

## Alternatives considered

- **Extend the discrete `pending_correction` suspend/wake mechanism instead of building a new channel.** Rejected: suspend/wake is single-shot by construction (one wake consumes the correction); making it re-entrant enough to support steer/pause/resume/redo/abort as independent, repeatable directives would have required rebuilding most of its internals anyway, with none of the benefit of a clean Sensor/Actuator split.
- **Apply steering directives immediately, including mid-phase.** Rejected: there is no safe per-issue mid-phase interrupt today (only fleet-wide `SIGKILL`); building one is high-blast-radius work out of scope for this ADR. Phase-boundary application is the safe, available seam.
- **Ship dashboard-facing `/redo` phase names in this pass.** Rejected: internal `IssueStoreStage` names are direct, already-tested, and sufficient to prove the mechanism; a translation layer adds a second vocabulary to keep in sync with no functional benefit yet, so it is deferred rather than gold-plated.

## Related

- ADR-0099 (Orchestration as a Control System — names surface #4, this ADR closes it)
- ADR-0092 (Untrusted-text trust boundary — the fencing regime `/steer` guidance reuses)
- ADR-0049 (Kill-switch convention — `human_steering_enabled` + `enabled_cb`)
- `src/human_steering.py:parse_directives`, `src/human_steering.py:apply_steering`, `src/human_steering_loop.py:HumanSteeringLoop`, `src/models.py:SteeringState`, `src/orchestrator.py:_apply_human_steering`
