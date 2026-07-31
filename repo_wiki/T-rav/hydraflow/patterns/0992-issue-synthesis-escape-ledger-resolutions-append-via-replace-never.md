---
id: 0992
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T04:11:10.529113+00:00
status: superseded
corroborations: 1
supersedes: 0928
superseded_by: 1059
---

# Escape ledger resolutions append via replace(), never rewrite

Resolution rows in `escape/ledger.py` are always appended as new superseding rows using `replace()` with an override dict — never rewrite an existing JSONL line, never hand-enumerate kwargs.

Example: `original_row.replace(encoded_as=new_value, confidence=...)` where missing keys preserve originals.

**Why:** Rewriting lines breaks the append-only invariant; hand-enumerated kwargs silently drop future schema fields added to the ledger row shape.
