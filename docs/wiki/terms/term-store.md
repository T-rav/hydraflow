---
id: "01KTAN6ASKZFQ7Z4DX99H70VSP"
name: "TermStore"
kind: "service"
bounded_context: "shared-kernel"
code_anchor: "src/ubiquitous_language.py:TermStore"
aliases: ["term repository", "ul store"]
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-06-05T01:08:36.275839+00:00"
updated_at: "2026-06-05T01:08:36.275842+00:00"
proposed_by: "TermProposerLoop"
proposed_at: "2026-06-05T01:08:36.275775+00:00"
proposal_signals: ["S2"]
proposal_imports_seen: 4
---

## Definition

TermStore is the persistence service for HydraFlow's ubiquitous-language glossary. It reads and writes Term records stored as one markdown file per term under docs/wiki/terms/, and exposes a list() interface consumed by EdgeProposerLoop, EntryEvidenceLoop, TermProposerLoop, and TermPrunerLoop to iterate over and mutate the live term collection. It is the single authoritative access point for the on-disk term corpus.

## Invariants

- Each Term is backed by exactly one markdown file under docs/wiki/terms/.
- list() reflects the current on-disk state, parsed deterministically via load_term_file.
