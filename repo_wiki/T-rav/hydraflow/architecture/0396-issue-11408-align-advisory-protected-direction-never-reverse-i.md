---
id: 0396
topic: architecture
source_issue: 11408
source_phase: plan
created_at: 2026-08-18T02:52:22.040856+00:00
status: active
corroborations: 1
---

# Align advisory→protected direction, never reverse, in retirement_picks

Rule: When aligning null-vs-empty semantics between `protected_labels` and `advisory_labels` in `src/backlog_budget.py`, always migrate advisory toward protected's identity-check pattern, never the reverse. When the two readings disagree, choose the interpretation that retires fewer candidates.

Example: `protected_set` already used `is not None`; `advisory_labels` was migrated to match. The docstring must state the contract for BOTH parameters symmetrically.

**Why:** `retirement_picks` is a valve that closes issues — a wrong-direction fix retiring more than intended is irreversible and silently closes issues the caller never declared advisory.
