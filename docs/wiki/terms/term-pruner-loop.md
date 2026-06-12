---
id: "01KT3WKPR5MN8QJ14CF77W6K5"
name: "TermPrunerLoop"
kind: "loop"
bounded_context: "caretaker"
code_anchor: "src/term_pruner_loop.py:TermPrunerLoop"
aliases: ["term pruner loop", "UL pruner", "glossary pruner"]
related: [{"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K2"}, {"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K5"}, {"kind": "depends_on", "target": "01KQZR9QW4RJ5Q7TB2220V3JZN"}, {"kind": "implements", "target": "01KQV37D10M06PGF32CF77W6K5"}]
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-05-19T00:00:00.000000+00:00"
updated_at: "2026-06-12T04:17:13.434460+00:00"
---

## Definition

Caretaker background loop that autonomously prunes stale terms from the ubiquitous-language glossary (ADR-0057). On each tick it scans every `confidence == "accepted"` term in `docs/wiki/terms/`; for any term whose `code_anchor` no longer resolves in the live symbol index (built by `ubiquitous_language.build_symbol_index`), it opens an auto-merging bot PR that flips `confidence` to `deprecated` and records a `superseded_reason` with the broken anchor. The loop makes no LLM calls — detection is purely structural.

## Invariants

- Kill-switch: `enabled_cb("term_pruner")` AND `config.term_pruner_enabled` — both must be true for work to proceed.
- Opens at most one PR per tick, bundling all eligible terms into a single `hydraflow-ul-deprecated`-labelled PR.
- `ReviewPhase` skips routing for PRs carrying `TERM_PRUNER_PR_LABEL` so the deprecation PR is not sent through the agent pipeline.
- Companion to `TermProposerLoop`: together they implement the two-tick grow/prune cycle that keeps `make lint-ul` anchor-resolution green without human intervention.
