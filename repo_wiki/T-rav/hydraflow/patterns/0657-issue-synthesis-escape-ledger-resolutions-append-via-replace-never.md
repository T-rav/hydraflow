---
id: 0657
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-27T20:03:14.326645+00:00
status: active
corroborations: 1
supersedes: 0615
---

# Escape ledger resolutions append via replace(), never rewrite

Resolution rows in `escape/ledger.py` are always appended as new superseding rows using `replace()` with an override dict — never rewrite an existing JSONL line, never hand-enumerate kwargs. When a field like `encoded_as` is omitted on a confidence-only resolution, `replace()` carries the original row's value forward automatically.

Example: `original_row.replace(encoded_as=new_value, confidence=...)` where missing keys preserve originals.

**Why:** Rewriting lines breaks the append-only invariant; hand-enumerated kwargs silently drop future schema fields added to the ledger row shape.
