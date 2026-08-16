---
id: 3606
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T12:13:23.333080+00:00
status: superseded
corroborations: 1
supersedes: 3459
superseded_by: 3751
---

# Salvage: local worktree count authoritative, origin only if unreadable

When reconciling potentially-salvaged work in `ImplementPhase._flow_screen` (`src/implement_phase.py`), consult the local worktree first via `git rev-list --count origin/<base>..<branch>`. Only fall back to origin-side `PRPort.branch_ahead_of_base` when the worktree is absent. Never salvage from origin when local is readable.

**Why:** A stale prior-attempt branch pushed to origin could be falsely "salvaged" if origin were consulted unconditionally; local count reflects the current attempt's actual work.
