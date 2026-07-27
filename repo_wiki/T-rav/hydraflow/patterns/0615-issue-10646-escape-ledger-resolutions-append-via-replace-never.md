---
id: 0615
topic: patterns
source_issue: 10646
source_phase: plan
created_at: 2026-07-26T12:21:36.986335+00:00
status: superseded
corroborations: 1
superseded_by: 0657
---

# Escape ledger resolutions append via replace(), never rewrite lines

Resolution rows in `escape/ledger.py` are always appended as new superseding rows using `replace()` with an override dict — never rewrite an existing JSONL line, never hand-enumerate kwargs. When a field like `encoded_as` is omitted on a confidence-only resolution, `replace()` carries the original row's value forward automatically.

Example: `original_row.replace(encoded_as=new_value, confidence=...)` where missing keys preserve originals.

**Why:** Rewriting lines breaks the append-only invariant; hand-enumerated kwargs silently drop future schema fields added to the ledger row shape.
