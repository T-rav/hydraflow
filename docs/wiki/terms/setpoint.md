---
id: "01KZ0F1YAK45A6FBKM7MAJ7H5D"
name: "Setpoint"
kind: "value_object"
bounded_context: "shared-kernel"
code_anchor: "src/signal_control/controllers.py:PidController"
aliases: []
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-08-01T00:00:00+00:00"
updated_at: "2026-08-01T00:00:00+00:00"
---

## Definition

The reference value a regulator drives its process variable toward — the target term in `error = PV - setpoint` that a control loop holds (`signal_control/controllers.py:PidController`, the setpoint regulators of ADR-0120). The bare word is scoped to the **control register** (ADR-0122). Adjacent registers use different words and must not borrow "setpoint": a **written requirement** (an acceptance criterion) is a *specification*, and an **ADR decision** is a *ruling* — neither is a setpoint, because a setpoint is a live, human-signed target a regulator reads each cycle whereas a requirement or ruling is prose. Where a requirement is *operationalized* into a regulator's target (e.g. the 70% coverage floor), that number is the setpoint and the ADR is its authority — name the two separately.

## Invariants

- 'Setpoint' is control-register only: a live, human-signed target a regulator reads each cycle; a requirement or ADR ruling is not a setpoint.
- When a requirement is operationalized into a target, the number is the setpoint and the ADR is its authority — name them separately.
