---
id: 2486
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:50.302593+00:00
status: active
corroborations: 1
supersedes: 2296,2406
---

# Regression tests in tests/regressions/ are immutable specs

`tests/regressions/test_issue_<N>.py` files are pre-authored RED specs encoding the acceptance contract — make them pass without weakening assertions; never rewrite them to fit the implementation.

Example: `test_issue_10799.py` is authoritative; its fixture combines real backend payloads plus an AST scan of every `PHASE_CHANGE` publish site. Add unpinned cases to adjacent unit test files instead.

**Why:** Rewriting or weakening a regression spec to fit the implementation defeats its purpose as a permanent guard against the original defect.
