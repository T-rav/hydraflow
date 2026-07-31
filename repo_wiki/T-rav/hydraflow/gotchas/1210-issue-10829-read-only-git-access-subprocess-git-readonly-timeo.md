---
id: 1210
topic: gotchas
source_issue: 10829
source_phase: plan
created_at: 2026-07-31T01:09:02.057446+00:00
status: active
corroborations: 1
---

# Read-only git access: subprocess + GIT_READONLY_TIMEOUT_S, not WorkspacePort

Modules needing read-only git data (e.g. `setpoint/authorship.py` for commit trailers) must follow the idiom in `escape/detect.py`: subprocess with `GIT_READONLY_TIMEOUT_S`, not `WorkspacePort` (no worktree involved).

- Cache results in the ledger so steady-state ticks issue no git calls.
- `authorship.py` degrades to `unknown` rather than raising when git history is absent.

**Why:** Spawning a new git access path or using WorkspacePort for a read-only query introduces unnecessary failure modes and worktree overhead.
