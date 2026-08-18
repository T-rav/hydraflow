---
id: 0402
topic: architecture
source_issue: 11419
source_phase: plan
created_at: 2026-08-18T03:36:18.966919+00:00
status: active
corroborations: 1
---

# Route body edits through PRPort.update_issue_body, not _run_gh/_repo

Inside `ReportIssueLoop` (and siblings), call `await self._pr_manager.update_issue_body(issue_number, body)` for issue body rewrites. Do not reach across module boundaries into `self._pr_manager._run_gh(...)` or `self._pr_manager._repo`.

- `PRManager` and `FakeGitHub` both implement `update_issue_body`.
- The `issue view --json labels,body` read on `_run_gh` stays because no `PRPort` method returns body+labels together.

**Why:** Cross-module `_`-prefixed access couples the loop to PRManager internals and bypasses the single-writer invariant the fake relies on for state consistency.
