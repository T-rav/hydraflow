---
id: 0109
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T19:10:32.489786+00:00
status: active
corroborations: 1
supersedes: 0044,0045,0046,0047,0048,0049,0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062,0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077
---

# Ruff strips unused imports mid-TDD cycle

During TDD, write the test body (which uses the new symbol) before adding its import — or use a function-local import inside the test body.

Example: add `from scripts.audit import score_rule` only after `score_rule` appears in the test function body. Alternative: `def test_score(): from scripts.audit import score_rule; assert score_rule(...)`.

**Why:** Pre-commit `ruff --fix` removes imports not yet referenced on the first save, producing `NameError` on the second save and breaking the TDD red-phase.

See also: testing — `feedback_ruff_strips_unused_imports_during_tdd.md`.
