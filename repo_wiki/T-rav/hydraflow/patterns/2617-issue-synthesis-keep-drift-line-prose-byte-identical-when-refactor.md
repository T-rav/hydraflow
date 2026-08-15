---
id: 2617
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-15T08:32:48.911749+00:00
status: superseded
corroborations: 1
supersedes: 2494
superseded_by: 2740
---

# Keep drift-line prose byte-identical when refactoring audit output

Drift lines emitted by `audit_repo` in `src/branch_protection_audit.py` are hashed by `_drift_key` in `src/branch_protection_auditor_loop.py` for issue dedup. Never reword them during a refactor.

Example: Changing a drift line's text shifts its hash → the auditor re-files an already-open issue.

**Why:** Dedup breaks silently — duplicate drift issues pile up and auto-close logic misfires when drift clears.
