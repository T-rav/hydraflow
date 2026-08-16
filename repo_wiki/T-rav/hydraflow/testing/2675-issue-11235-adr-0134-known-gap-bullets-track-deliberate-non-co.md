---
id: 2675
topic: testing
source_issue: 11235
source_phase: plan
created_at: 2026-08-16T05:30:59.489433+00:00
status: active
corroborations: 1
---

# ADR-0134 known-gap bullets track deliberate non-coverage

`docs/adr/0134-per-repo-model-harness-selection.md` maintains a "Known gap" section (`:148-165`) listing what the design does NOT cover. When closing a gap, rewrite the bullet — state what's now routed, what stays untouched and why, and cite the new tests.

**Why:** Future contributors distinguish intentional omissions (e.g., `report_issue_loop` deliberately bypassed) from forgotten work.
