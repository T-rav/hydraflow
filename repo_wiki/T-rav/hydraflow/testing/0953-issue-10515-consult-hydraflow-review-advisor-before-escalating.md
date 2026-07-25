---
id: 0953
topic: testing
source_issue: 10515
source_phase: review
created_at: 2026-07-25T09:50:02.028832+00:00
status: active
corroborations: 1
---

# Consult hydraflow-review-advisor before escalating severity on borderline findings

Before finalizing severity on findings like "missing fake-vs-real parity test," run them past the `hydraflow-review-advisor` subagent — in #10515 it correctly downgraded two initial concerns (missing parity test, "padding" diagrams) that were actually already covered by existing tests (`tests/test_issue_store.py:1122`, `:1732`) or established repo convention (per-issue `.likec4` diagrams are common, not PR-specific bloat).

**Why:** prevents overstating severity from an incomplete read of existing coverage/conventions before verifying against the advisor or the actual test suite.
