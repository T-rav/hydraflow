---
id: 0240
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T01:45:28.225489+00:00
status: superseded
corroborations: 1
supersedes: 0176,0177,0178,0179,0180,0181,0182,0183,0184,0185,0186,0187,0188,0189,0190,0191,0192,0193,0194,0195,0196,0197,0198,0199,0200,0201,0202,0203,0204,0205,0206,0207,0208,0209,0210,0211,0212,0213,0214,0215,0216,0217
superseded_by: 0260
---

# Preserve exact retry counter state during dispatcher refactoring

When refactoring state machine dispatchers, carry over retry counters and escalation conditions (e.g., epic-child label swaps) exactly — do not reset or re-derive them.

Example: Copy `issue.attempt_count` and `issue.escalation_triggered` into the refactored handler without modification.

**Why:** Dropping retry state silently resets attempt budgets, allowing previously-exhausted issues to cycle again or miss escalation thresholds.
