---
id: 1324
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-27T22:47:42.294750+00:00
status: active
corroborations: 1
supersedes: 1250
---

# Doc+single-unit-test fixes skip MockWorld/e2e

A pure ADR-text repair plus one behavioral unit test in tests/test_triage_phase.py — with no change to src/triage_phase.py runtime logic — legitimately skips MockWorld, sandbox e2e, and the ADR-0049 kill-switch requirement.

Example: reserve full-pyramid ADR-0051 review cycles for load-bearing runtime/feature changes. See also: Pure-function + log-line changes skip MockWorld/sandbox e2e.

**Why:** Applying the full test pyramid to a docs-only fix is process overhead that doesn't catch anything a unit test wouldn't.
