---
id: "01KTAN51E5V2D2X7RY7B7P7Q0Q"
name: "Term"
kind: "entity"
bounded_context: "shared-kernel"
code_anchor: "src/ubiquitous_language.py:Term"
aliases: ["ul term", "glossary term", "ubiquitous language term"]
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-06-05T01:07:53.925403+00:00"
updated_at: "2026-06-05T01:07:53.925409+00:00"
proposed_by: "TermProposerLoop"
proposed_at: "2026-06-05T01:07:53.925264+00:00"
proposal_signals: ["S2"]
proposal_imports_seen: 4
---

## Definition

A first-class domain entity representing a named concept in HydraFlow's ubiquitous language. Each Term captures a load-bearing domain name with its definition, kind, bounded context, code anchor, relationships to other terms, lifecycle confidence (proposed → accepted → deprecated), and wiki-entry evidence. Terms are persisted as exactly one Markdown file in docs/wiki/terms/ and form the ontology that caretaker loops grow, enrich, and prune autonomously.

## Invariants

- A Term must have a unique ULID id, a non-empty name, and a valid code_anchor (module:symbol) pointing to its canonical source location.
- confidence follows a one-way lifecycle: proposed → accepted → deprecated; a deprecated Term carries a non-null superseded_by.
- Each Term is stored as exactly one Markdown file in docs/wiki/terms/, keyed by a slug derived from its name.
