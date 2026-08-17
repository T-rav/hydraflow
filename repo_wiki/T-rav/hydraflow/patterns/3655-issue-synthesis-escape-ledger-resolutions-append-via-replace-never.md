---
id: 3655
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T13:50:48.682081+00:00
status: superseded
corroborations: 1
supersedes: 3510
superseded_by: 3800
---

# Escape ledger resolutions append via replace(), never rewrite

Resolution rows in `escape/ledger.py` are always appended as new superseding rows using `replace()` with an override dict — never rewrite an existing JSONL line, never hand-enumerate kwargs.

Example: `original_row.replace(encoded_as=new_value, confidence=...)` where missing keys preserve originals.

**Why:** Rewriting lines breaks the append-only invariant; hand-enumerated kwargs silently drop future schema fields added to the ledger row shape.
