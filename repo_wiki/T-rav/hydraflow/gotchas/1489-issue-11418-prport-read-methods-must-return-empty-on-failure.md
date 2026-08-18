---
id: 1489
topic: gotchas
source_issue: 11418
source_phase: plan
created_at: 2026-08-18T03:42:49.483108+00:00
status: active
corroborations: 1
---

# PRPort read methods must return empty on failure

Implement `PRPort` read methods in `src/pr_manager.py` to catch `gh api` failures and return empty lists or strings. For example, `list_branch_refs` or `get_issue_body` must return `[]` or `""` on failure, never raise an exception.

**Why:** Caretaker loops like `stale_issue_loop` interpret "no data" as "nothing to GC"; raising exceptions alters tick behavior and crashes background loops.
