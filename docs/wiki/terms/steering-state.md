---
id: "01KWN0R5WY93KMBF8CWG9MPFHB"
name: "SteeringState"
kind: "control_role"
bounded_context: "shared-kernel"
code_anchor: "src/models.py:SteeringState"
aliases: []
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-07-03T22:14:23.000000+00:00"
updated_at: "2026-07-03T22:14:23.000000+00:00"
---

## Definition

The persisted Error/reference-state register for one issue's `SteeringChannel` (ADR-0099 §6 surface #4, closed by ADR-0103): a `guidance` string, a `flow` (`running` | `paused` | `abort`), a pending `redo_phase`, a `redo_count`, and a `last_applied_ts` high-water-mark gating imperative directives. `HumanSteeringLoop` (Sensor) writes it each tick from parsed comments; the orchestrator's `apply_steering` (Controller) reads it to compute a `SteeringDecision` that the orchestrator (Actuator) enacts at the next phase boundary. Keyed `str(issue_number)` in `StateData.human_steering`, matching the per-issue-map convention.

## Invariants

- Precedence within one poll is fixed: abort beats pause beats redo beats steer — `apply_steering` checks `flow == abort` first, then `paused`, before considering `redo_phase`.
- `redo_phase` is only honored while `redo_count < human_steering_max_redos` and the phase name is a known internal stage; otherwise it is silently dropped rather than retried, so a stale or bogus `/redo` cannot stall an issue forever.
