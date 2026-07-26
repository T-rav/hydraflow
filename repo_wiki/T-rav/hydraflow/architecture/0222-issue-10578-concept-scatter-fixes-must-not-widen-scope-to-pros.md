---
id: 0222
topic: architecture
source_issue: 10578
source_phase: plan
created_at: 2026-07-26T01:20:17.466888+00:00
status: active
corroborations: 1
---

# Concept-scatter fixes must not widen scope to prose-only citations

When resolving a concept-scatter finding (e.g. #10104 on `escape_ledger.jsonl`), only touch modules that independently *compute* the resolution, not modules that merely mention it in a docstring or comment. `audit/store.py` and `intervention/ledger.py` only cite the escape ledger in prose and were explicitly left alone in the #10578 plan.
**Why:** widening a scatter-cleanup PR to sibling stores turns a scoped, reviewable refactor into an unbounded one — treat it as a separate issue instead.
