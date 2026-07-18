---
id: 0143
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T20:37:07.471507+00:00
status: active
corroborations: 1
supersedes: 0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091,0092,0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111
---

# Ruff strips unused imports mid-TDD cycle

During TDD, write the test body (which uses the new symbol) before adding its import — or use a function-local import inside the test body.

Example: add `from scripts.audit import score_rule` only after `score_rule` appears in the test function body. Alternative: `def test_score(): from scripts.audit import score_rule; assert score_rule(...)`.

**Why:** Pre-commit `ruff --fix` removes imports not yet referenced on the first save, producing `NameError` on the second save and breaking the TDD red-phase.

See also: testing — `feedback_ruff_strips_unused_imports_during_tdd.md`.
