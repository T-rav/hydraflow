---
id: 0871
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T16:22:24.453604+00:00
status: superseded
corroborations: 1
supersedes: 0798,0799,0800,0801,0802,0803,0804,0805,0806,0807,0808,0809,0810,0811,0812,0813,0814,0815,0816,0817,0818,0819,0820,0821,0822,0823,0824,0825,0826,0827,0828,0829,0830,0831,0832,0833,0834,0835,0836,0837,0838,0839,0840,0841,0842,0843,0844,0845,0846
superseded_by: 0898
---

# Doc+single-unit-test fixes skip MockWorld/e2e per testing standard

Not every change needs the full three-layer pyramid (unit + MockWorld scenario + sandbox e2e) from `docs/standards/testing/README.md`. A pure ADR-text repair plus one behavioral unit test in `tests/test_triage_phase.py` — with no change to `src/triage_phase.py` runtime logic, no new loop/runner, and no new git/gh/subprocess call — legitimately skips MockWorld and sandbox e2e, and skips the ADR-0049 kill-switch requirement too, since nothing new is being wired up.

Example: reserve full-pyramid ADR-0051 review cycles for load-bearing runtime/feature changes.

**Why:** applying the full test pyramid to a docs-only fix is process overhead that doesn't catch anything a unit test wouldn't; the standard is scoped to load-bearing features, not every touched file.
