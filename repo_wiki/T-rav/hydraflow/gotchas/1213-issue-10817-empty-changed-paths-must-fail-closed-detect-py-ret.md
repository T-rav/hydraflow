---
id: 1213
topic: gotchas
source_issue: 10817
source_phase: plan
created_at: 2026-07-31T01:28:07.214993+00:00
status: active
corroborations: 1
---

# Empty changed_paths must fail closed: detect.py returns None on git failure

`src/audit/detect.py`'s `merged_changes_for_range` must return `None` when the git path read fails, and return `MergedChange` with empty `changed_paths` only for genuinely empty commits. The consuming loop reports `changes_unavailable` rather than sampling nothing.

**Why:** `all([])` is `True`, so a git-read failure that yields empty paths for every change causes `is_self_chore_change` to exclude all self-chores AND everything else classifies as `routine` — a silent total audit bypass.
