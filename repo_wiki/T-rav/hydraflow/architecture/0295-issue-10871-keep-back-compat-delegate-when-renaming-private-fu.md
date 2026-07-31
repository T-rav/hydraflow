---
id: 0295
topic: architecture
source_issue: 10871
source_phase: review
created_at: 2026-07-31T16:47:39.085922+00:00
status: stale
corroborations: 1
stale_reason: source issue #10871 closed
---

# Keep back-compat delegate when renaming private functions

When renaming a private function in `src/`, always leave a delegate at the old name forwarding to the new name — even if zero callers are found.

- `src/prompt_fitness.py`: `_load_audit_module()` → `load_audit_module()`; old name kept as delegate.
- Wiki entries 0279/0281 explicitly forbid removing the delegate; #10296 and #10310 are prior recurrences of the same class.

**Why:** Out-of-tree or wiki-documented callers may depend on the old name; the repo treats the delegate as permanent hygiene, not optional.
