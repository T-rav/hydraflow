---
id: 1454
topic: gotchas
source_issue: 11340
source_phase: plan
created_at: 2026-08-16T11:56:57.838071+00:00
status: active
corroborations: 1
---

# FakeIssue number-desc is the proxy for gh created-desc

Use issue number descending as the faithful proxy for `gh`'s created-descending default in `FakeGitHub`. `FakeIssue` has no `created_at` field, so number order *is* creation order.

- All three listing methods in `src/mockworld/fakes/fake_github.py` sort by issue number descending before slicing.
- Document this proxy choice in the method docstrings.

**Why:** The ordering — not just the cap — is what makes window defects reproduce; production drops the oldest rows and an insertion-order fake would drop the newest.
