---
id: 1234
topic: patterns
source_issue: 10894
source_phase: plan
created_at: 2026-07-31T11:12:50.925680+00:00
status: active
corroborations: 1
---

# Keep drift-line prose byte-identical when refactoring audit output

Drift lines emitted by `audit_repo` in `src/branch_protection_audit.py` are hashed by `_drift_key` in `src/branch_protection_auditor_loop.py` for issue dedup. Never reword them during a refactor.

- Changing a drift line's text shifts its hash.
- Shifted hashes cause the auditor to re-file an already-open issue.

**Why:** Dedup breaks silently — duplicate drift issues pile up and auto-close logic misfires when drift clears.
