---
id: 1175
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-27T18:41:12.861012+00:00
status: active
corroborations: 1
supersedes: 1106
---

# ADR Enforced by: pointer must assert the decision itself

An ADR's Enforced by pointer is only real enforcement if the target test asserts the actual behavioral claim, not merely touches a related symbol.

Example: ADR-0017's exclusion rule (_maybe_decompose() returning True must skip increment_session_counter("triaged")) had drifted to point at a test that referenced the counter but never checked the exclusion. The fix added a test asserting counter delta is zero for epic_decomposed routing.

**Why:** A regex-satisfying but behaviorally-empty enforcement pointer is a silent-green hole — CI stays green even if the exclusion regresses.
