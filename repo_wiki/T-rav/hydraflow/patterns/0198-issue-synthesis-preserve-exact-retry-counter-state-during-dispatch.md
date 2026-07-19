---
id: 0198
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T00:22:06.635706+00:00
status: superseded
corroborations: 1
supersedes: 0134,0135,0136,0137,0138,0139,0140,0141,0142,0143,0144,0145,0146,0147,0148,0149,0150,0151,0152,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175
superseded_by: 0218
---

# Preserve exact retry counter state during dispatcher refactoring

When refactoring state machine dispatchers, carry over retry counters and escalation conditions (e.g., epic-child label swaps) exactly — do not reset or re-derive them.

Example: copy `issue.attempt_count` and `issue.escalation_triggered` into the refactored handler without modification.

**Why:** Dropping retry state silently resets attempt budgets, allowing previously-exhausted issues to cycle again or miss escalation thresholds.
