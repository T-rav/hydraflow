---
id: "01KZ0F1YAK45A6FBKM7MAJ7H5C"
name: "Verdict"
kind: "value_object"
bounded_context: "shared-kernel"
code_anchor: "src/convergence_gate.py:JudgeVerdict"
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

A closed-set adjudication emitted by a decision mechanism. The bare word is scoped to the **control/kernel register**: a gate's pass/fail outcome (`convergence_gate.py:JudgeVerdict`, `convergence_gate.py:GateDecision`, `models.py:ReviewVerdict`) — the terminal decision the pipeline routes on. Two other registers qualify the word rather than own it: a **formal-methods verdict** (ADR-0122) is a model-checker's result and, on failure, a *counterexample* trace witnessing a violated property (#10833); a **legal-sense verdict** is an adjudication under the ADR corpus — a human-signed ruling on a proposal. Qualify with the register ("gate verdict", "model-checker verdict", "adjudication") whenever the three could be confused; unqualified "verdict" means the gate outcome.

## Invariants

- Unqualified 'verdict' denotes a gate's pass/fail outcome; the formal (counterexample) and legal (adjudication) senses must be qualified.
