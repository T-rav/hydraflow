---
id: "01KXV30G7W143XRZFQM9SCSX27"
name: "TribalWikiStore"
kind: "service"
bounded_context: "shared-kernel"
code_anchor: "src/tribal_wiki.py:TribalWikiStore"
aliases: ["tribal wiki", "global wiki", "cross-repo wiki"]
related: [{"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K6"}]
evidence: ["01KQNZNK5DWPQ75W9HBCJX2DJ6"]
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-07-18T17:05:01.692894+00:00"
updated_at: "2026-07-24T05:34:07.706352+00:00"
proposed_by: "TermProposerLoop"
proposed_at: "2026-07-18T17:05:01.692844+00:00"
proposal_signals: ["S2"]
proposal_imports_seen: 2
---

## Definition

Cross-repo knowledge store that mirrors the per-repo wiki layout (index.json + topic.md pages) but is not namespaced by repo. All entries carry source_repo='global' and are written only by the generalization pass (src/wiki_compiler.py) when the same principle is observed in two or more per-repo wikis. Loaded at every plan/implement/review phase alongside the target repo's wiki so tribal rules apply regardless of which repo is being worked on. Routes reads, writes, staleness filtering, and contradiction marking through the underlying RepoWikiStore to keep on-disk format consistent with per-repo wikis.

## Invariants

- All entries carry source_repo='global'; the store is pinned to a single 'global' slug.
- Entries are written only by the generalization pass when the same principle is observed in ≥2 per-repo wikis; direct modification from agent code is not a supported use case.
- On-disk layout, staleness filtering, contradiction marking, and supersession are delegated to the underlying RepoWikiStore so per-repo and tribal formats stay consistent.
