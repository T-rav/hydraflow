---
id: "01KZ0F1YAK45A6FBKM7MAJ7H5H"
name: "Independence"
kind: "policy"
bounded_context: "shared-kernel"
code_anchor: "src/judge_independence.py:IndependenceDisposition"
aliases: []
related: [{"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K2"}]
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-08-01T00:00:00+00:00"
updated_at: "2026-08-14T05:32:18.123535+00:00"
---

## Definition

Non-correlation of judgment, in two registers that must not be conflated (ADR-0122). In the **evidence/formal register**, independence is *model-family diversity* — a verdict from a model family outside the implementing agent's roster, so author and reviewer are not "siblings" (#10371/#10832, `judge_independence.py:IndependenceDisposition`); it buys decorrelated error, not org-chart separation. In the **legal register**, independence is *institutional* — a reviewer structurally separate from the authoring authority (separation of powers). Qualify as "model-family independence" or "institutional independence"; the bare word in HydraFlow code defaults to model-family independence.

## Invariants

- In HydraFlow code, unqualified 'independence' means model-family independence (decorrelated error), not institutional independence.
