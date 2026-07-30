---
id: 1174
topic: gotchas
source_issue: 10747
source_phase: plan
created_at: 2026-07-27T22:30:25.835033+00:00
status: stale
corroborations: 1
stale_reason: source issue #10747 closed
---

# Untracked test files don't survive ADR-0112 fresh per-issue clones

Untracked RED test files left in the factory workspace from earlier runs (e.g., `tests/regressions/test_issue_10747.py`) do not travel to a fresh per-issue clone under ADR-0112. Treat them as evidence of prior work, not as starting code — author the regression from the live codebase.

**Why:** Assuming the file already exists leads to missing or empty test files in the actual execution environment.
