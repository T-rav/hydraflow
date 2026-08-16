---
id: 2716
topic: testing
source_issue: 11338
source_phase: plan
created_at: 2026-08-16T12:34:38.645116+00:00
status: active
corroborations: 1
---

# Canonical issue branch is config.branch_for_issue(N), never hardcoded

Use `HydraFlowConfig.branch_for_issue(N)` to derive `agent/issue-{N}` everywhere — fakes, seeds, and tests. Never re-hardcode the string.

The counter-pins in `tests/regressions/test_issue_11338.py` assert the canonical payload passes, the missing-key payload passes, and a seeded value provably overrides the phase's own branch.

**Why:** Every `agent/issue-*` consumer keys off this namespace; hardcoding a literal breaks when the config schema changes and makes the branch namespace incoherent across layers.
