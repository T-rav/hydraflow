---
id: 1404
topic: gotchas
source_issue: 11246
source_phase: plan
created_at: 2026-08-15T20:20:19.664537+00:00
status: active
corroborations: 1
---

# FakeGitHub fakes must raise RuntimeError on unknown gh entities

FakeGitHub methods that look up an entity by number (issue view, issue edit) must `raise RuntimeError` when the number is unseeded — never silently return empty/default data.

Real `gh` exits non-zero on missing issues, and `PRManager._run_gh` (src/report_issue_loop.py) surfaces that as `RuntimeError`. Both real consumers (`ReportIssueLoop._verify_issue`) catch it, so raising is the faithful contract.

**Why:** Returning `{"comments": []}` or similar defaults masks the real failure mode and causes repair paths to fire unconditionally under MockWorld, diverging from production behavior.
