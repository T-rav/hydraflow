---
id: 1568
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T01:04:04.336873+00:00
status: active
corroborations: 1
supersedes: 1486
---

# ADR Enforced by: pointer must assert the decision itself

An ADR's Enforced by pointer is only real enforcement if the target test asserts the actual behavioral claim, not merely touches a related symbol.

Example: ADR-0017's exclusion rule (_maybe_decompose() returning True must skip increment_session_counter('triaged')) had drifted to point at a test that referenced the counter but never checked the exclusion.

**Why:** A regex-satisfying but behaviorally-empty enforcement pointer is a silent-green hole — CI stays green even if the exclusion regresses.
