---
id: "01KY9SW3PM6BQGQQVN7A42M185"
name: "TermStore"
kind: "service"
bounded_context: "shared-kernel"
code_anchor: "src/ubiquitous_language.py:TermStore"
aliases: ["term repository"]
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-07-24T10:13:57.076757+00:00"
updated_at: "2026-07-24T10:13:57.076760+00:00"
proposed_by: "TermProposerLoop"
proposed_at: "2026-07-24T10:13:57.076713+00:00"
proposal_signals: ["S2"]
proposal_imports_seen: 4
---

## Definition

TermStore is the persistence service for the ubiquitous-language glossary — it reads and lists Term entities from their one-file-per-term markdown representation under docs/wiki/terms/, giving the UL caretaker loops (TermProposerLoop, EdgeProposerLoop, EntryEvidenceLoop, TermPrunerLoop) a single canonical way to load and enumerate the term corpus rather than each loop parsing term files itself.

## Invariants

- Each Term corresponds to exactly one markdown file under docs/wiki/terms/, following the frontmatter + prose format written by dump_term_file
