---
id: "01KZ0F1YAK45A6FBKM7MAJ7H5G"
name: "Gate"
kind: "service"
bounded_context: "shared-kernel"
code_anchor: "src/convergence_gate.py:Gate"
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

Two things the word collapses (ADR-0122). A **gate (mechanism)** is the runtime component that evaluates a condition and returns a verdict on a transition (`convergence_gate.py:Gate` and its `evaluate`, the convergence gate, precondition gates) — the control/kernel register. A **gate (entrenched rule)** is the standing, hard-to-change rule the mechanism enforces — *gate immutability* in the legal/constitutional register (who may alter the gate, under what allowlist). Bare "gate" means the mechanism; use "gate policy" or "entrenched gate rule" for the rule it enforces. The split matters because changing a gate's *code* is a control act, while changing what a gate is *allowed to permit* is a constitutional one.

## Invariants

- Bare 'gate' is the mechanism; the standing rule it enforces is a 'gate policy' (legal register).
- Changing gate code is a control act; changing what a gate may permit is a constitutional act under an allowlist.
