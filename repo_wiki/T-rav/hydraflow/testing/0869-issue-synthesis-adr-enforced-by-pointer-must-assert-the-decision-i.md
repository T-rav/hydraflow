---
id: 0869
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T16:22:24.447813+00:00
status: active
corroborations: 1
supersedes: 0798,0799,0800,0801,0802,0803,0804,0805,0806,0807,0808,0809,0810,0811,0812,0813,0814,0815,0816,0817,0818,0819,0820,0821,0822,0823,0824,0825,0826,0827,0828,0829,0830,0831,0832,0833,0834,0835,0836,0837,0838,0839,0840,0841,0842,0843,0844,0845,0846
---

# ADR `Enforced by:` pointer must assert the decision itself

An ADR's `**Enforced by:**` pointer is only real enforcement if the target test asserts the actual behavioral claim — not merely touches a related symbol. ADR-0017's exclusion rule (`_maybe_decompose()` returning True must skip `increment_session_counter("triaged")`) had drifted to point at a test that referenced the counter but never checked the exclusion.

Example: repointing it at e.g. `test_state_mixin_decomposition.py` would satisfy a naive regex check while staying hollow; the real fix adds a test in `tests/test_triage_phase.py` asserting the counter delta is zero when `routing_outcome == "epic_decomposed"` and exactly one when `routing_outcome == "plan"`.

**Why:** a regex-satisfying but behaviorally-empty enforcement pointer is a silent-green hole — CI stays green even if the exclusion regresses.
