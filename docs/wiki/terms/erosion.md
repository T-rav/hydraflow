---
id: "01KZ0F1YAK45A6FBKM7MAJ7H5J"
name: "Erosion"
kind: "value_object"
bounded_context: "shared-kernel"
code_anchor: "src/erosion_metrics_loop.py:ErosionMetricsLoop"
aliases: []
related: [{"kind": "depends_on", "target": "01JZ9FK3C0M01HYR42BF11W0A1"}, {"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K7"}, {"kind": "depends_on", "target": "01KY4QF8BE4Y5782543MPQNDQ0"}, {"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K2"}, {"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K5"}, {"kind": "depends_on", "target": "01JZ9FK3C0M03HYR42BF33W0C3"}, {"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K4"}, {"kind": "depends_on", "target": "01KWDRENTS7VACCW9PDA7Y488H"}, {"kind": "implements", "target": "01KQV37D10M06PGF32CF77W6K5"}]
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-08-01T00:00:00+00:00"
updated_at: "2026-08-14T05:32:18.123535+00:00"
---

## Definition

Slow drift of a measured quantity away from where it should be — a **control-register** signal (`erosion_metrics_loop.py:ErosionMetricsLoop`, the erosion trends). Two sides must be named separately (ADR-0122). **Plant-side erosion** is decay in the code itself: rising duplication, scatter, god-module concentration — the process variable degrading. **Reference-side erosion** is *setpoint erosion* (#10829): the *target* drifting — a floor quietly lowered, a bound relaxed — so the regulator holds an eroded reference and reports health while the standard slips. Bare "erosion" means plant-side; always write "setpoint erosion" for the reference-side case, because the two have opposite fixes (tighten the plant vs restore the setpoint).

## Invariants

- Bare 'erosion' is plant-side (code); reference-side decay must be written 'setpoint erosion' (#10829).
- Plant-side and setpoint erosion have opposite remedies — tighten the plant vs restore the setpoint.
