---
id: 3947
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T17:41:42.451746+00:00
status: active
corroborations: 1
supersedes: 3800
---

# Escape ledger resolutions append via replace(), never rewrite

Resolution rows in `escape/ledger.py` are always appended as new superseding rows using `replace()` with an override dict — never rewrite an existing JSONL line, never hand-enumerate kwargs.

Example: `original_row.replace(encoded_as=new_value, confidence=...)` where missing keys preserve originals.

**Why:** Rewriting lines breaks the append-only invariant; hand-enumerated kwargs silently drop future schema fields added to the ledger row shape.
