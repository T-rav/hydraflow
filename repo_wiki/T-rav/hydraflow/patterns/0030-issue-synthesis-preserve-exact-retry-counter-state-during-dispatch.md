---
id: 0030
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:09:18.317258+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007
---

# Preserve exact retry counter state during dispatcher refactoring

When refactoring state machine dispatchers, carry over retry counters and escalation conditions (e.g., epic-child label swaps) exactly — do not reset or re-derive them.

Example: copy `issue.attempt_count` and `issue.escalation_triggered` into the refactored handler without modification.

**Why:** Dropping retry state silently resets attempt budgets, allowing previously-exhausted issues to cycle again or miss escalation thresholds.
