---
id: 0075
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T06:16:33.341947+00:00
status: superseded
corroborations: 1
supersedes: 0012,0012,0013,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0037,0038,0039,0040,0041,0042,0043
superseded_by: 0078
---

# Ruff strips unused imports mid-TDD cycle

During TDD, write the test body (which uses the new symbol) before adding its import — or use a function-local import inside the test body.

Example: add `from scripts.audit import score_rule` only after `score_rule` appears in the test function body. Alternative: `def test_score(): from scripts.audit import score_rule; assert score_rule(...)`.

**Why:** Pre-commit `ruff --fix` removes imports not yet referenced on the first save, producing `NameError` on the second save and breaking the TDD red-phase.

See also: testing — `feedback_ruff_strips_unused_imports_during_tdd.md`.
