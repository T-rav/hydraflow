---
id: "01KY9SVFEJ9R2YMZ014QX2JT98"
name: "Term"
kind: "entity"
bounded_context: "shared-kernel"
code_anchor: "src/ubiquitous_language.py:Term"
aliases: ["ul term", "glossary term"]
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-07-24T10:13:36.338150+00:00"
updated_at: "2026-07-24T10:13:36.338154+00:00"
proposed_by: "TermProposerLoop"
proposed_at: "2026-07-24T10:13:36.338021+00:00"
proposal_signals: ["S2"]
proposal_imports_seen: 4
---

## Definition

Term is the first-class domain entity representing a single ubiquitous-language concept in HydraFlow: a canonical name, kind (aggregate/entity/service/loop/etc.), bounded context, one-paragraph definition, code anchor, and typed relations to other terms. Each Term is persisted as one markdown file under docs/wiki/terms/, carries a proposed → accepted → deprecated confidence lifecycle, and is grown and groomed by the UL caretaker loops (TermProposerLoop, EdgeProposerLoop, EntryEvidenceLoop, TermPrunerLoop) that keep the glossary a living artifact per ADR-0053.

## Invariants

- id defaults to a freshly generated ULID, giving each Term a stable identity independent of its name
- confidence moves through a closed lifecycle: proposed → accepted → deprecated
- code_anchor must resolve to a module:symbol pair so the term stays traceable to real code
