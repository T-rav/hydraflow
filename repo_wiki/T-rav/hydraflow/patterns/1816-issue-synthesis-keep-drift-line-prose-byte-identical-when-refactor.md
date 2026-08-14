---
id: 1816
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T12:50:04.172328+00:00
status: superseded
corroborations: 1
supersedes: 1720
superseded_by: 1914
---

# Keep drift-line prose byte-identical when refactoring audit output

Drift lines emitted by `audit_repo` in `src/branch_protection_audit.py` are hashed by `_drift_key` in `src/branch_protection_auditor_loop.py` for issue dedup. Never reword them during a refactor.

Example: Changing a drift line's text shifts its hash → the auditor re-files an already-open issue.

**Why:** Dedup breaks silently — duplicate drift issues pile up and auto-close logic misfires when drift clears.
