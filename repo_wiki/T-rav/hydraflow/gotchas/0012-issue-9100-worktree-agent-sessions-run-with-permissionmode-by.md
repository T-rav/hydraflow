---
id: 0012
topic: gotchas
source_issue: 9100
source_phase: review
created_at: 2026-06-12T09:13:44.467873+00:00
status: active
corroborations: 1
---

# Worktree agent sessions run with permissionMode=bypassPermissions

Agents launched in a worktree context (e.g. `issue-9100`) initialize with `permissionMode: "bypassPermissions"`, meaning all tool calls execute without user confirmation prompts.

- This is intentional for lights-off factory operation
- Destructive tool calls (force-push, branch deletion, file removal) will execute immediately without a prompt gate
- Review any automation that spawns worktree agents to ensure destructive paths are explicitly guarded in code, not assumed to be caught by permission prompts

**Why:** Assuming permission prompts will catch dangerous operations in worktree agents is wrong — bypassPermissions removes that safety net entirely.
