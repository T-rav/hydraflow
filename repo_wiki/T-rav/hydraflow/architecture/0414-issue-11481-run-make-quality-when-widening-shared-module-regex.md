---
id: 0414
topic: architecture
source_issue: 11481
source_phase: plan
created_at: 2026-08-20T09:13:45.273125+00:00
status: active
corroborations: 1
---

# Run make quality when widening shared module regexes

Run the full `make quality` suite when changing regex patterns in shared engines. File-targeted test subsets miss the blast radius of shared module regex updates.

**Why:** Regex widening in core modules like `src/pr_manager.py` can silently break loop wiring or integration scenarios, as seen in the PR #8460 lesson.
