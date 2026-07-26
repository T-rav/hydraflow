---
id: 1038
topic: gotchas
source_issue: 10567
source_phase: review
created_at: 2026-07-26T01:57:49.299025+00:00
status: active
corroborations: 1
---

# PRManager gh-output parsers must filter blank interior lines

When `PRManager` parses line-delimited `gh` CLI output (labels, etc.), filter blank/whitespace-only interior lines defensively and cover it with a dedicated test.

- See `test_blank_lines_are_filtered` in `tests/test_pr_manager_queries.py`, added alongside `get_pr_labels` to mirror `get_issue_labels`'s existing filtering.

**Why:** `gh` output can include stray blank lines depending on flags/version, which otherwise turn into phantom empty-string labels downstream.
