---
id: 3762
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T13:50:50.793521+00:00
status: active
corroborations: 1
supersedes: 3617
---

# Include MultiEdit in Claude write-tool deny-lists

Include `MultiEdit` in any Claude write-tool deny-list.

Example: `READ_ONLY_DISALLOWED_TOOLS = "Write,Edit,MultiEdit,NotebookEdit"` in `src/agent_cli.py`. Existing ad-hoc `"Write,Edit,NotebookEdit"` literals across the repo omit `MultiEdit` even though `_RESTRICTED_ALLOWED_TOOLS` grants it.

**Why:** Omitting `MultiEdit` leaves an open write path.
