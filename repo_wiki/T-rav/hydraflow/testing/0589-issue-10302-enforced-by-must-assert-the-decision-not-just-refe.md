---
id: 0589
topic: testing
source_issue: 10302
source_phase: plan
created_at: 2026-07-24T03:55:54.536758+00:00
status: active
corroborations: 1
---

# `Enforced by:` must assert the decision, not just reference the counter primitive

An ADR's `**Enforced by:**` pointer is only real enforcement if the target test asserts the actual behavioral claim — not merely touches a related symbol. ADR-0017's exclusion rule (`_maybe_decompose()` returning True must skip `increment_session_counter("triaged")`) had drifted to point at a test that referenced the counter but never checked the exclusion. Repointing it at e.g. `test_state_mixin_decomposition.py` would satisfy a naive regex check while staying hollow. The fix must add a test in `tests/test_triage_phase.py` asserting the counter delta is zero when `routing_outcome == "epic_decomposed"` and exactly one when `routing_outcome == "plan"`.

**Why:** a regex-satisfying but behaviorally-empty enforcement pointer is a silent-green hole — CI stays green even if the exclusion regresses.
