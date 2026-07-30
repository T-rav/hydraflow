---
id: 0191
topic: architecture
source_issue: 10451
source_phase: plan
created_at: 2026-07-24T12:15:48.605763+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# docs/architecture/jsonl_ledger.likec4 lives on staging, not main

The LikeC4 diagram `docs/architecture/jsonl_ledger.likec4` tracks ledger classes that may not exist on `main` yet — branch from `staging` when editing it, and verify referenced class/file names exist on the merge base before merging, not just on `main`. Merge ordering matters: if a diagram PR lands before the code PR it documents (e.g. #10451 before #10403), it names classes that don't exist yet.
**Why:** no CI parses or validates `.likec4` symbol references, so a diagram merged out of order silently ships false documentation until the next reviewer notices.
