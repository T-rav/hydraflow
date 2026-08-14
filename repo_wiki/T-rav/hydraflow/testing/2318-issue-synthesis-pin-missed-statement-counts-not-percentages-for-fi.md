---
id: 2318
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T18:40:37.016206+00:00
status: superseded
corroborations: 1
supersedes: 2173
superseded_by: 2508
---

# Pin missed-statement counts, not percentages, for fixture ratchets

Ratchet absolute missed-statement counts for fixture branch coverage, never percentages. A pin like `reviewer_build_review: 17 missed` may only decrease.

Example: `ci_enabled` defaults to true, so reviewer's `use_quality_gate_in_review` elif/else branches are dead in production. A missed-count pin absorbs this naturally.

**Why:** Percentages hide absolute regressions (20→19 missed while adding 10 total statements looks like progress at the same %) and demand exemption machinery for production-unreachable code.
