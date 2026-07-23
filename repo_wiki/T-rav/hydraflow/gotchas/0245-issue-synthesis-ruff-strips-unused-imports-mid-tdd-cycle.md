---
id: 0245
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T02:45:05.804516+00:00
status: superseded
corroborations: 1
supersedes: 0180,0181,0182,0183,0184,0185,0186,0187,0188,0189,0190,0191,0192,0193,0194,0195,0196,0197,0198,0199,0200,0201,0202,0203,0204,0205,0206,0207,0208,0209,0210,0211,0212,0213
superseded_by: 0248
---

# Ruff strips unused imports mid-TDD cycle

During TDD, write the test body (which uses the new symbol) before adding its import — or use a function-local import inside the test body.

Example: add `from scripts.audit import score_rule` only after `score_rule` appears in the test function body.

**Why:** Pre-commit `ruff --fix` removes imports not yet referenced on the first save, producing `NameError` on the second save and breaking the TDD red-phase.

See also: gotchas — Grep for runtime references before removing an import.
