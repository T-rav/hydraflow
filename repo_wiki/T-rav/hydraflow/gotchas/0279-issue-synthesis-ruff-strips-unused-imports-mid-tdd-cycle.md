---
id: 0279
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T02:39:19.036406+00:00
status: superseded
corroborations: 1
supersedes: 0214,0215,0216,0217,0218,0219,0220,0221,0222,0223,0224,0225,0226,0227,0228,0229,0230,0231,0232,0233,0234,0235,0236,0237,0238,0239,0240,0241,0242,0243,0244,0245,0246,0247
superseded_by: 0282
---

# Ruff strips unused imports mid-TDD cycle

During TDD, write the test body (which uses the new symbol) before adding its import — or use a function-local import inside the test body.

Example: add `from scripts.audit import score_rule` only after `score_rule` appears in the test function body.

**Why:** Pre-commit `ruff --fix` removes imports not yet referenced on the first save, producing `NameError` on the second save and breaking the TDD red-phase.

See also: gotchas — Grep for runtime references before removing an import.
