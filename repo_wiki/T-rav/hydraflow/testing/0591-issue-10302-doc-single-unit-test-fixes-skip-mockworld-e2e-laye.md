---
id: 0591
topic: testing
source_issue: 10302
source_phase: plan
created_at: 2026-07-24T03:55:54.536772+00:00
status: superseded
corroborations: 1
superseded_by: 0593
---

# Doc+single-unit-test fixes skip MockWorld/e2e layers under docs/standards/testing

Not every change needs the full three-layer pyramid (unit + MockWorld scenario + sandbox e2e) from `docs/standards/testing/README.md`. A pure ADR-text repair plus one behavioral unit test in `tests/test_triage_phase.py` — with no change to `src/triage_phase.py` runtime logic, no new loop/runner, and no new git/gh/subprocess call — legitimately skips MockWorld and sandbox e2e, and skips the ADR-0049 kill-switch requirement too, since nothing new is being wired up. Reserve full-pyramid ADR-0051 review cycles for load-bearing runtime/feature changes.

**Why:** applying the full test pyramid to a docs-only fix is process overhead that doesn't catch anything a unit test wouldn't; the standard is scoped to load-bearing features, not every touched file.
