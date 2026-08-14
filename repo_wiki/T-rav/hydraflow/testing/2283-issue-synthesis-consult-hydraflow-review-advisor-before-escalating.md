---
id: 2283
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T18:40:36.923287+00:00
status: superseded
corroborations: 1
supersedes: 2138
superseded_by: 2473
---

# Consult hydraflow-review-advisor before escalating severity

Before finalizing severity on findings like 'missing fake-vs-real parity test,' run them past the hydraflow-review-advisor subagent.

Example: in #10515 it correctly downgraded two initial concerns (missing parity test, 'padding' diagrams) that were already covered by existing tests (`tests/test_issue_store.py:1122`, `:1732`) or established repo convention.

**Why:** Prevents overstating severity from an incomplete read of existing coverage/conventions before verifying against the advisor or the actual test suite.
