---
id: 0822
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T13:43:21.197585+00:00
status: superseded
corroborations: 1
supersedes: 0754,0755,0756,0757,0758,0759,0760,0761,0762,0763,0764,0765,0766,0767,0768,0769,0770,0771,0772,0773,0774,0775,0776,0777,0778,0779,0780,0781,0782,0783,0784,0785,0786,0787,0788,0789,0790,0791,0792,0793,0794,0795,0796,0797
superseded_by: 0847
---

# Doc+single-unit-test fixes skip MockWorld/e2e per testing standard

Not every change needs the full three-layer pyramid (unit + MockWorld scenario + sandbox e2e) from `docs/standards/testing/README.md`. A pure ADR-text repair plus one behavioral unit test in `tests/test_triage_phase.py` — with no change to `src/triage_phase.py` runtime logic, no new loop/runner, and no new git/gh/subprocess call — legitimately skips MockWorld and sandbox e2e, and skips the ADR-0049 kill-switch requirement too, since nothing new is being wired up.

Example: reserve full-pyramid ADR-0051 review cycles for load-bearing runtime/feature changes.

**Why:** applying the full test pyramid to a docs-only fix is process overhead that doesn't catch anything a unit test wouldn't; the standard is scoped to load-bearing features, not every touched file.
