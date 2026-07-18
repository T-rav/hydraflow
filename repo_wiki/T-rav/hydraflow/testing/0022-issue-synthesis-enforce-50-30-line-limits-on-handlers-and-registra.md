---
id: 0022
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-13T05:43:53.410113+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
---

# Enforce 50/30-line limits on handlers and registration wiring

Keep handler functions to ≤ 50 lines and registration wiring to ≤ 30 lines. Extract nested closures into instance methods to hold nesting to ≤ 3 levels.

**Why:** Functions exceeding these limits are difficult to test in isolation; deeply nested closures cannot be mocked independently.
