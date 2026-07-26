---
id: 0912
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T23:15:44.766538+00:00
status: superseded
corroborations: 1
supersedes: 0764,0765,0766,0767,0768,0769,0770,0771,0772,0773,0774,0775,0776,0777,0778,0779,0780,0781,0782,0783,0784,0785,0786,0787,0788,0789,0790,0791,0792,0793,0794,0795,0796,0797,0798,0799,0800,0801,0802,0803,0804,0805,0806,0807,0808,0809,0810,0811,0812,0813,0814,0815,0816,0817,0818,0819,0820,0821,0822,0823,0824,0826,0827,0828,0829,0830,0833,0834,0838,0839,0840,0841,0842,0843,0844,0848,0848,0848,0849,0850
superseded_by: 0940
---

# Classify subprocess reaps (timeout/OOM/kill) apart from quality verdicts

When a verification subprocess dies from infra causes, don't treat it the same as a failing quality check. `src/implement_recovery.py`'s reap classifier treats "did not complete within its 120s timeout and was murdered" as an infra reap (salvageable), but "make quality failed: 3 tests failed" as a real verdict (not salvageable) — ADR-0005's "no PR for failing work" still applies to the latter. A committed-and-pushed fresh attempt that gets reaped by infra should still open a PR; one that fails quality should not.

**Why:** conflating the two either strands good work behind a flaky 120s timeout, or opens PRs on genuinely broken code.
