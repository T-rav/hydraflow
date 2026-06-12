---
id: "01KRBL0F20M01PGF32CF88W9B8"
name: "EntryEvidenceLoop"
kind: "loop"
bounded_context: "caretaker"
code_anchor: "src/entry_evidence_loop.py:EntryEvidenceLoop"
aliases: ["entry evidence loop", "wiki entry evidence loop", "UL evidence loop"]
related: [{"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K5"}, {"kind": "depends_on", "target": "01KQZR9QW4RJ5Q7TB2220V3JZN"}, {"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K6"}, {"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K2"}, {"kind": "implements", "target": "01KQV37D10M06PGF32CF77W6K5"}]
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-05-19T20:00:00.000000+00:00"
updated_at: "2026-06-12T04:17:13.434460+00:00"
---

## Definition

Caretaker loop that backfills `Term.evidence` links by matching wiki entries to ubiquitous-language terms via LLM (ADR-0062). Each tick processes up to `entry_evidence_max_entries_per_tick` unmatched entries, calls the LLM once per entry to identify genuinely related terms (not superficial name-fragment matches), and opens auto-merge bot PRs labeled `hydraflow-ul-evidence` with the updated term files. A `DedupStore` prevents re-processing entries that already have evidence on subsequent ticks. Mirrors `EdgeProposerLoop` (ADR-0058) and `TermProposerLoop` (ADR-0054) in structure but is LLM-driven rather than static-analysis-driven.

## Invariants

- One LLM call per wiki entry per tick — no batching across entries within a single call.
- The `hydraflow-ul-evidence` label causes `review_phase` to skip agent pipeline routing; the LLM-driven matching IS the work (ADR-0062).
- Kill-switch is via `enabled_cb("entry_evidence")` (ADR-0049); no config field.
- `entry_evidence_max_entries_per_tick` bounds the LLM spend per cycle.
