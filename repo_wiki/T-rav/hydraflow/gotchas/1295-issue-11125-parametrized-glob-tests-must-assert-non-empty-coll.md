---
id: 1295
topic: gotchas
source_issue: 11125
source_phase: plan
created_at: 2026-08-14T11:39:37.483951+00:00
status: active
corroborations: 1
---

# Parametrized glob tests must assert non-empty collection

A pytest parametrize over an empty glob collects zero tests and reports success — silently reproducing the bug the test was meant to catch.

- `tests/hooks/test_hook_shell_scripts.py` must include an explicit assertion that the glob returned ≥1 file before parametrizing.
- Without it, deleting all `tests/hooks/*.sh` makes the suite green instead of red.

**Why:** A vacuous green is the exact failure mode issue #11125 exists to prevent — unrun scripts passing forever in silence.
