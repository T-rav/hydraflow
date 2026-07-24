---
id: 0736
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T10:42:21.328138+00:00
status: superseded
corroborations: 1
supersedes: 0672,0673,0674,0675,0676,0677,0678,0679,0680,0681,0682,0683,0684,0685,0686,0687,0688,0689,0690,0691,0692,0693,0694,0695,0696,0697,0698,0699,0700,0701,0702,0703,0704,0705,0706,0707,0708,0709,0710,0711
superseded_by: 0754
---

# Doc+single-unit-test fixes skip MockWorld/e2e per testing standard

Not every change needs the full three-layer pyramid (unit + MockWorld scenario + sandbox e2e) from `docs/standards/testing/README.md`. A pure ADR-text repair plus one behavioral unit test in `tests/test_triage_phase.py` — with no change to `src/triage_phase.py` runtime logic, no new loop/runner, and no new git/gh/subprocess call — legitimately skips MockWorld and sandbox e2e, and skips the ADR-0049 kill-switch requirement too, since nothing new is being wired up.

Example: reserve full-pyramid ADR-0051 review cycles for load-bearing runtime/feature changes.

**Why:** applying the full test pyramid to a docs-only fix is process overhead that doesn't catch anything a unit test wouldn't; the standard is scoped to load-bearing features, not every touched file.
