---
id: "01KVJPAQ8987YPSRSWWWJJTBSG"
name: "ADRIndex"
kind: "service"
bounded_context: "shared-kernel"
code_anchor: "src/adr_index.py:ADRIndex"
aliases: ["adr cache", "adr catalog", "architecture decision index"]
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-06-20T14:18:05.961056+00:00"
updated_at: "2026-06-20T14:18:05.961059+00:00"
proposed_by: "TermProposerLoop"
proposed_at: "2026-06-20T14:18:05.960978+00:00"
proposal_signals: ["S2"]
proposal_imports_seen: 1
---

## Definition

Mtime-based runtime cache over the ADR directory that parses docs/adr/*.md on first access and re-scans only when the directory mtime changes. Exposes parsed ADR records — including normalized status, context summary, cited source files, and symbol-level citations — to caretaker loops and agent prompts. Acts as the authoritative in-process view of architecture decisions, enabling loops such as AdrTouchpointAuditorLoop to check which Accepted ADRs cite a given source file without re-reading the filesystem on every tick. The module docstring frames it explicitly as load-bearing: agents must know what has already been decided before they plan.

## Invariants

- Re-scans the ADR directory only when its mtime changes; returns the cached ADR list on a stable directory
- Status values are normalized to one of Accepted, Proposed, Superseded, Deprecated, or Unknown — no raw status strings escape the parser
