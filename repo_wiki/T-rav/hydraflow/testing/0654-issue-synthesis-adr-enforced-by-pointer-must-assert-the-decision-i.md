---
id: 0654
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T07:31:08.500257+00:00
status: superseded
corroborations: 1
supersedes: 0593,0594,0595,0596,0597,0598,0599,0600,0601,0602,0603,0604,0605,0606,0607,0608,0609,0610,0611,0612,0613,0614,0615,0616,0617,0618,0619,0620,0621,0622,0623,0624,0625,0626,0627,0628,0629,0630,0631
superseded_by: 0672
---

# ADR `Enforced by:` pointer must assert the decision itself

An ADR's `**Enforced by:**` pointer is only real enforcement if the target test asserts the actual behavioral claim — not merely touches a related symbol. ADR-0017's exclusion rule (`_maybe_decompose()` returning True must skip `increment_session_counter("triaged")`) had drifted to point at a test that referenced the counter but never checked the exclusion.

Example: repointing it at e.g. `test_state_mixin_decomposition.py` would satisfy a naive regex check while staying hollow; the fix must add a test in `tests/test_triage_phase.py` asserting the counter delta is zero when `routing_outcome == "epic_decomposed"` and exactly one when `routing_outcome == "plan"`.

**Why:** a regex-satisfying but behaviorally-empty enforcement pointer is a silent-green hole — CI stays green even if the exclusion regresses.
