---
id: 3471
topic: patterns
source_issue: 11321
source_phase: plan
created_at: 2026-08-16T09:00:03.766484+00:00
status: superseded
corroborations: 1
superseded_by: 3617
---

# Include MultiEdit in Claude write-tool deny-lists

Include `MultiEdit` in any Claude write-tool deny-list.

`READ_ONLY_DISALLOWED_TOOLS = "Write,Edit,MultiEdit,NotebookEdit"` in `src/agent_cli.py`. Existing ad-hoc `"Write,Edit,NotebookEdit"` literals across the repo omit `MultiEdit` even though `_RESTRICTED_ALLOWED_TOOLS` grants it.

**Why:** Omitting `MultiEdit` leaves an open write path.
