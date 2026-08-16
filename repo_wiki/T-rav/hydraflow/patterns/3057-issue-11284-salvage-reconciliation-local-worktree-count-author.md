---
id: 3057
topic: patterns
source_issue: 11284
source_phase: plan
created_at: 2026-08-16T01:29:44.315655+00:00
status: superseded
corroborations: 1
superseded_by: 3189
---

# Salvage reconciliation: local worktree count authoritative, origin only when unreadable

When reconciling potentially-salvaged work in `ImplementPhase._flow_screen` (`src/implement_phase.py`), consult the local worktree first via `git rev-list --count origin/<base>..<branch>`. Only fall back to origin-side `PRPort.branch_ahead_of_base` when the worktree is absent. Never salvage from origin when local is readable.

**Why:** A stale prior-attempt branch pushed to origin could be falsely "salvaged" if origin were consulted unconditionally; local count reflects the current attempt's actual work.
