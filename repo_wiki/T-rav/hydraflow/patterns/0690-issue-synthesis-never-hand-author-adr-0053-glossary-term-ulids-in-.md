---
id: 0690
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-27T22:37:52.923559+00:00
status: superseded
corroborations: 1
supersedes: 0645
superseded_by: 0747
---

# Never hand-author ADR-0053 glossary term ULIDs in docs/wiki/terms/

Glossary terms under `docs/wiki/terms/` are proposed by the term loop, not fabricated during feature work — even when a new feature clearly needs a canonical term.

Example: An ultra-review tier feature should not manually create a term ULID; instead let `src/term_proposer_loop.py` propose it through the ADR-0053 living-artifact workflow.

**Why:** A manually-invented ULID breaks the ADR-0053 living-artifact discipline that keeps term anchors in sync with generated docs (`docs/arch/generated/ubiquitous-language.md`).
