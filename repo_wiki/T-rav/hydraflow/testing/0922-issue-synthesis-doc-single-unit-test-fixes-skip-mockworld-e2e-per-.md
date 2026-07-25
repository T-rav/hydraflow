---
id: 0922
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T02:46:40.801044+00:00
status: superseded
corroborations: 1
supersedes: 0847,0848,0849,0850,0851,0852,0853,0854,0855,0856,0857,0858,0859,0860,0861,0862,0863,0864,0865,0866,0867,0868,0869,0870,0871,0872,0873,0874,0875,0876,0877,0878,0879,0880,0881,0882,0883,0884,0885,0886,0887,0888,0889,0890,0891,0892,0893,0894,0895
superseded_by: 0953
---

# Doc+single-unit-test fixes skip MockWorld/e2e per testing standard

Not every change needs the full three-layer pyramid (unit + MockWorld scenario + sandbox e2e) from `docs/standards/testing/README.md`. A pure ADR-text repair plus one behavioral unit test in `tests/test_triage_phase.py` — with no change to `src/triage_phase.py` runtime logic, no new loop/runner, and no new git/gh/subprocess call — legitimately skips MockWorld and sandbox e2e, and skips the ADR-0049 kill-switch requirement too, since nothing new is being wired up.

Example: reserve full-pyramid ADR-0051 review cycles for load-bearing runtime/feature changes.

**Why:** applying the full test pyramid to a docs-only fix is process overhead that doesn't catch anything a unit test wouldn't; the standard is scoped to load-bearing features, not every touched file.
