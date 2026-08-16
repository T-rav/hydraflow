---
id: 1352
topic: gotchas
source_issue: 11182
source_phase: plan
created_at: 2026-08-14T23:30:09.294021+00:00
status: stale
corroborations: 1
stale_reason: source issue #11182 closed
---

# ADR-0069 retry-window contract only binds where the parser can attribute branches

ADR-0069's retry-window contract for auto-agent sessions is meaningless if `WorkspaceGCLoop._parse_issue_from_branch` returns `None` for the branch namespace the session uses — phase 3 drops the branch before `_in_retry_window` is ever called.

- Adding the auto-agent prefix to `_ISSUE_BRANCH_RES` makes phase 3 consult `_in_retry_window` for that issue
- Pin with a spy asserting `_in_retry_window` was called for an in-flight session's real branch

**Why:** A guard that is architecturally correct but never reached because the parser fails upstream is an invisible escape — the contract must be testable end-to-end through the parser.
