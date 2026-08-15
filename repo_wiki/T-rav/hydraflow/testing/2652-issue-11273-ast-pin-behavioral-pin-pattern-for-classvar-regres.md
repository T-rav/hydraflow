---
id: 2652
topic: testing
source_issue: 11273
source_phase: plan
created_at: 2026-08-15T20:41:55.284250+00:00
status: active
corroborations: 1
---

# AST-pin + behavioral-pin pattern for ClassVar regression tests

Regression tests for class-level flags should use an AST pin verifying the assignment occurs inside the class body — a comment or docstring mentioning the flag does not satisfy it. Pair with a behavioral pin that runs real `_execute_cycle()` under shrunk bounds.

Example: `tests/regressions/test_issue_11273.py` shrinks default→1s, LLM→120s, then runs a 3-issue queue with 2 mocked ~0.4s agent calls each, asserting no watchdog-timeout ERROR event.

**Why:** Structural pins catch flag removal; behavioral pins catch machinery regressions that structural-only tests miss.
