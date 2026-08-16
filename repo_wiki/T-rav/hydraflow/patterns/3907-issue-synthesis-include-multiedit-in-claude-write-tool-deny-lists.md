---
id: 3907
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T15:30:58.332966+00:00
status: superseded
corroborations: 1
supersedes: 3762
superseded_by: 4054
---

# Include MultiEdit in Claude write-tool deny-lists

Include `MultiEdit` in any Claude write-tool deny-list.

Example: `READ_ONLY_DISALLOWED_TOOLS = "Write,Edit,MultiEdit,NotebookEdit"` in `src/agent_cli.py`. Existing ad-hoc `"Write,Edit,NotebookEdit"` literals across the repo omit `MultiEdit` even though `_RESTRICTED_ALLOWED_TOOLS` grants it. See also: [patterns] — _RESTRICTED_ALLOWED_TOOLS grants writes.

**Why:** Omitting `MultiEdit` leaves an open write path.
