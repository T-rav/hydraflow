---
id: "01KRBL0F20M01PGF32CF88W9C2"
name: "EdgeProposerLoop"
kind: "loop"
bounded_context: "caretaker"
code_anchor: "src/edge_proposer_loop.py:EdgeProposerLoop"
aliases: ["edge proposer loop", "UL edge proposer loop", "term edge loop"]
related: [{"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K5"}, {"kind": "depends_on", "target": "01KQZR9QW4RJ5Q7TB2220V3JZN"}, {"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K2"}, {"kind": "implements", "target": "01KQV37D10M06PGF32CF77W6K5"}]
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-05-19T20:00:00.000000+00:00"
updated_at: "2026-06-12T04:17:13.434460+00:00"
---

## Definition

Caretaker loop that densifies the ubiquitous-language term context map by proposing `depends_on` and `implements` edges between existing terms via static import graph analysis (ADR-0058, ADR-0060, ADR-0062). Each tick walks the import graph produced by `build_import_graph`, infers structural relationships between terms, and opens auto-merge bot PRs labeled `hydraflow-ul-edges` with updated term files. Unlike `EntryEvidenceLoop`, edge inference is static-analysis-driven, not LLM-driven. The `hydraflow-ul-edges` label causes `review_phase` to skip agent pipeline routing.

## Invariants

- Edge inference is based on the import graph (`build_import_graph`), not LLM judgment — results are deterministic for a given codebase state.
- The `hydraflow-ul-edges` label causes `review_phase` to skip the agent pipeline; the structural inference IS the work (ADR-0058).
- Kill-switch is via `enabled_cb("edge_proposer")` (ADR-0049).
