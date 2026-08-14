---
id: 1683
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T11:12:30.382687+00:00
status: superseded
corroborations: 1
supersedes: 1589
superseded_by: 1779
---

# Escape ledger resolutions append via replace(), never rewrite

Resolution rows in `escape/ledger.py` are always appended as new superseding rows using `replace()` with an override dict — never rewrite an existing JSONL line, never hand-enumerate kwargs.

Example: `original_row.replace(encoded_as=new_value, confidence=...)` where missing keys preserve originals.

**Why:** Rewriting lines breaks the append-only invariant; hand-enumerated kwargs silently drop future schema fields added to the ledger row shape.
