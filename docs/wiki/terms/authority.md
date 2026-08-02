---
id: "01KZ0F1YAK45A6FBKM7MAJ7H5F"
name: "Authority"
kind: "policy"
bounded_context: "shared-kernel"
code_anchor: "src/models.py:HitlEscalation"
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

Two distinct notions the word must not conflate (ADR-0122). In the **control register**, authority is *actuation permission* — what a loop may do to the plant this cycle, bounded by the Governor (saturation limits, kill switch, credit holds); a Controller cannot override it. In the **legal/constitutional register**, authority is *jurisdiction* — who holds the decision: who may change what, by what procedure, reviewed by whom, and the escalation boundary where a decision leaves the factory's authority and passes to a human (`models.py:HitlEscalation`, human-signed envelopes). Qualify as "actuation authority" (control) or "decision authority / jurisdiction" (legal); the bare word defaults to the legal sense (jurisdiction).

## Invariants

- Actuation authority (control) is bounded by the Governor and cannot be self-granted by a Controller.
- Decision authority (legal) transfers to a human only across an explicit escalation boundary.
