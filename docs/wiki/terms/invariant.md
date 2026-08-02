---
id: "01KZ0F1YAK45A6FBKM7MAJ7H5E"
name: "Invariant"
kind: "invariant"
bounded_context: "shared-kernel"
code_anchor: "src/arch/integrity.py:IntegrityInvariant"
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

A property asserted to hold — but the three assurance disciplines mean three different *strengths* of claim, so the bare word must be qualified (ADR-0122). A **formal invariant** is a *proven* property, established for every interleaving by the kernel proof (#10833). A **control invariant** is a *monitored* series — a signal a regulator holds within bounds and is *observed* (never proven) to stay there. A **legal invariant** is a *rule asserted in prose* — a constraint declared in an ADR or an architecture check (`arch/integrity.py:IntegrityInvariant`) and enforced by convention or CI, not by proof. Because unqualified "invariant" reads as *proven* and thereby overclaims, always name the register: "proven invariant", "monitored invariant", or "asserted invariant".

## Invariants

- 'Invariant' unqualified overclaims (it reads as proven); name the register — proven (formal), monitored (control), or asserted (legal).
