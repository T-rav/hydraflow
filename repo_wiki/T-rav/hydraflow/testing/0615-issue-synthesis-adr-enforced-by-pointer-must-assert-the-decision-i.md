---
id: 0615
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T05:57:59.589586+00:00
status: superseded
corroborations: 1
supersedes: 0567,0568,0569,0570,0571,0572,0573,0574,0575,0576,0577,0578,0579,0580,0581,0582,0583,0584,0585,0586,0587,0588,0589,0590,0591,0592
superseded_by: 0632
---

# ADR `Enforced by:` pointer must assert the decision itself

An ADR's `**Enforced by:**` pointer is only real enforcement if the target test asserts the actual behavioral claim — not merely touches a related symbol. ADR-0017's exclusion rule (`_maybe_decompose()` returning True must skip `increment_session_counter("triaged")`) had drifted to point at a test that referenced the counter but never checked the exclusion. Repointing it at e.g. `test_state_mixin_decomposition.py` would satisfy a naive regex check while staying hollow. The fix must add a test in `tests/test_triage_phase.py` asserting the counter delta is zero when `routing_outcome == "epic_decomposed"` and exactly one when `routing_outcome == "plan"`.

**Why:** a regex-satisfying but behaviorally-empty enforcement pointer is a silent-green hole — CI stays green even if the exclusion regresses.
