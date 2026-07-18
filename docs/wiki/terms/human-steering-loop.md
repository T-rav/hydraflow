---
id: "01KWN0R5WY93KMBF8CWG9MPFHA"
name: "HumanSteeringLoop"
kind: "control_role"
bounded_context: "shared-kernel"
code_anchor: "src/human_steering_loop.py:HumanSteeringLoop"
aliases: []
related: [{"kind": "depends_on", "target": "01JZ9FK3C0M01HYR42BF11W0A1"}, {"kind": "depends_on", "target": "01KWN0R5WY93KMBF8CWG9MPFHB"}, {"kind": "depends_on", "target": "01KWDRENTS7VACCW9PDA7Y488H"}, {"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K5"}, {"kind": "depends_on", "target": "01JZ9FK3C0M03HYR42BF33W0C3"}, {"kind": "implements", "target": "01KQV37D10M06PGF32CF77W6K5"}]
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-07-03T22:14:23.000000+00:00"
updated_at: "2026-07-18T18:03:47.549355+00:00"
---

## Definition

The Sensor half of the `SteeringChannel` (ADR-0099 §6 surface #4, closed by ADR-0103): a `BaseBackgroundLoop` that, each tick, fetches GitHub comments for every active issue and calls the pure parser `human_steering.parse_directives` to derive the latest `SteeringState`, then persists it via `state.set_human_steering`. Purely a sensor: it never mutates issue phase, labels, or the pipeline directly — the orchestrator's actuator half reads the persisted state and enacts it at the next phase boundary. Gated by `human_steering_enabled` (default `True` since 2026-07-05, env-controllable via `HYDRAFLOW_HUMAN_STEERING_ENABLED`) and a kill-switch (`enabled_cb`), per ADR-0049. Default-on is safe because `parse_directives` honors nobody when `human_steering_authorized_users` is empty.

## Invariants

- `_do_work` never applies a decision to the plant; it only fetches comments, parses, and writes `SteeringState` — enactment is the orchestrator's job, keeping the sensor/actuator split total.
- On a comment-fetch failure for one issue, the loop logs and continues to the next issue rather than aborting the whole tick, so one flaky issue cannot starve steering for the rest of the fleet.
