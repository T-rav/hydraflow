---
id: 0363
topic: architecture
source_issue: 11281
source_phase: plan
created_at: 2026-08-16T01:24:32.227570+00:00
status: active
corroborations: 1
---

# PRManager._issue_number_from_branch excludes auto-agent by design

Keep `PRManager._issue_number_from_branch` (`src/pr_manager.py`, ~line 3358) returning 0 for `agent/auto-agent-*` branches. Auto-agent PRs route through `DependabotMergeLoop`, not the review→merge pipeline.

Pin this with a test:
- `_issue_number_from_branch("agent/auto-agent-42")` returns 0

Document the deliberate exclusion and its DependabotMergeLoop routing in a comment at the method.

**Why:** Widening would pull factory-owned auto-agent sessions into a pipeline not designed for them, breaking the session lifecycle. This is a conscious routing decision, not an oversight — the issue explicitly requested confirmation of this boundary.
