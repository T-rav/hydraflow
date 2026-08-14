---
id: 1310
topic: gotchas
source_issue: 11136
source_phase: plan
created_at: 2026-08-14T13:02:38.765861+00:00
status: active
corroborations: 1
---

# RED-pin regression files are pre-written and committed with fix

`tests/regressions/test_issue_11136.py` ships as untracked RED pins that must flip green with zero edits to that file. Workflow: write the regression file first (RED), implement the fix, confirm GREEN, then commit both together. If the regression file is not committed alongside the fix, the before/after evidence chain is lost.

**Why:** Committing the regression file separately or editing it post-hoc destroys the RED→GREEN proof.
