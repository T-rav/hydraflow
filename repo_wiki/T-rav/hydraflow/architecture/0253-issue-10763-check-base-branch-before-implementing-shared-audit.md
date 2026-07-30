---
id: 0253
topic: architecture
source_issue: 10763
source_phase: plan
created_at: 2026-07-28T00:17:34.080281+00:00
status: active
corroborations: 1
---

# Check base branch before implementing shared auditor APIs across PRs

When an API is designed in one issue but consumed by multiple landing-bound issues, check the base branch before implementing it. Reuse the landed version rather than duplicating.

Example: `src/wiki_lesson_coverage.py` was API-designed in #10655 and consumed by both #10758 and #10763. If #10758 lands first, the P1 task must verify its API contract and skip module creation rather than shipping a conflicting implementation.

**Why:** Duplicating a shared module with a divergent API causes merge conflicts and forces downstream consumers to rewrite against an unexpected interface.
