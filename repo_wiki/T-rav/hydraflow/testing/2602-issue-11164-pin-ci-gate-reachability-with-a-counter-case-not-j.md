---
id: 2602
topic: testing
source_issue: 11164
source_phase: plan
created_at: 2026-08-14T18:58:35.986554+00:00
status: stale
corroborations: 1
stale_reason: source issue #11164 closed
---

# Pin CI gate reachability with a counter-case, not just a happy path

Regression pins for CI path-filter behavior must include known-false cases alongside the RED case. `tests/regressions/test_issue_11164.py` asserts `core_python` is false for `docs/adr/**` and `tests/regressions/**`, true for `src/*.py` — so a RED result on `agents/**` is a real gap, not a broken glob evaluator.

- Parse the live `.github/workflows/ci.yml` with `yaml.safe_load`; no fixtures.
- Evaluate globs the way `dorny/paths-filter` does.

**Why:** A hand-rolled evaluator that over-matches passes the pin without the gate actually firing.
