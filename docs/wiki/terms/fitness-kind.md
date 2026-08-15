---
id: "01M03GZ2F1MSZ1MZK55AFS7JEJ"
name: "FitnessKind"
kind: "value_object"
bounded_context: "caretaker"
code_anchor: "src/loop_fitness.py:FitnessKind"
aliases: ["fitness kind", "loop fitness kind", "scored vs housekeeping"]
related: [{"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K5"}, {"kind": "depends_on", "target": "01KZ0F1YAK45A6FBKM7MAJ7H5J"}, {"kind": "depends_on", "target": "01JZ9FK3C0M02HYR42BF22W0B2"}, {"kind": "depends_on", "target": "01KZ1RA3CGWE9H5XX59XH66DQF"}, {"kind": "depends_on", "target": "01KZ07BBDCF5RAZW7VG2VY4NW7"}]
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-08-15T20:14:13.985566+00:00"
updated_at: "2026-08-15T20:14:13.985567+00:00"
proposed_by: "TermProposerLoop"
proposed_at: "2026-08-15T20:14:13.985523+00:00"
proposal_signals: ["S2"]
proposal_imports_seen: 5
---

## Definition

Closed-set classification of whether a loop emits a normalized fitness score (SCORED) or only raw housekeeping counters (HOUSEKEEPING). Each loop's archetype determines its kind: proposer loops with measurable acceptance rates are SCORED, while caretaker loops without a normalized outcome metric are HOUSEKEEPING. Carried on every LoopFitness so the FitnessScorecardLoop knows whether to compute and present a normalized score or leave score null.

## Invariants

- Exactly two members: SCORED (normalized score) and HOUSEKEEPING (raw counters only) — a loop is one or the other, never both.
- HOUSEKEEPING loops leave LoopFitness.score null; SCORED loops populate score once sample_count meets the min-samples threshold, otherwise return null with INSUFFICIENT_DATA confidence.
