---
id: 0519
topic: patterns
source_issue: 10555
source_phase: plan
created_at: 2026-07-25T22:52:11.067270+00:00
status: active
corroborations: 1
---

# Never hand-author ADR-0053 glossary term ULIDs in `docs/wiki/terms/`

Glossary terms under `docs/wiki/terms/` are proposed by the term loop, not fabricated during feature work — even when a new feature (e.g. an ultra-review tier) clearly needs a canonical term.

**Why:** a manually-invented ULID breaks the ADR-0053 living-artifact discipline that keeps term anchors in sync with generated docs (`docs/arch/generated/ubiquitous-language.md`).
