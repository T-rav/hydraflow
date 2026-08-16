---
id: 0389
topic: architecture
source_issue: 11333
source_phase: plan
created_at: 2026-08-16T11:30:55.516344+00:00
status: active
corroborations: 1
---

# PRManager open-issue listings use bounded windows with saturation warnings

Every open-issue listing in `src/pr_manager.py` must read from a single module constant (`OPEN_LABEL_LIST_LIMIT`) and log a WARNING when results exactly fill it. Both `list_issues_by_label` and `list_open_issues` point at the same constant so one number owns the window.

- Saturation guard: `logger.warning("...", label, limit)` with literal format string.
- A short board costs the same — `gh` returns only what exists.

**Why:** A silent truncation at `--limit 100` caused `find_class_key.file_or_fold` to miss older class issues and file siblings instead of folding, the exact board growth #11292 targets.
