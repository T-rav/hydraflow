---
id: 2713
topic: testing
source_issue: 11333
source_phase: plan
created_at: 2026-08-16T11:30:55.516425+00:00
status: active
corroborations: 1
---

# Cross-module test imports require public constants (no leading underscore)

When `scripts/find_class_check.py` imports a constant from `src/pr_manager.py` to keep its fold-window in sync, that constant must be public — `OPEN_LABEL_LIST_LIMIT`, not `_OPEN_LABEL_LIST_LIMIT`.

- Drift guard test asserts the CLI's gh invocation requests a window ≥ `pr_manager.OPEN_LABEL_LIST_LIMIT`.
- The two fold paths (Python `file_or_fold` and CLI `find_class_check.py`) must not disagree on fold-vs-file.

**Why:** A private constant blocks the cross-module drift guard, and divergent windows between the two fold paths reintroduce silent sibling filing.
