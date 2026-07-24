---
id: 0694
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T09:08:28.864182+00:00
status: active
corroborations: 1
supersedes: 0632,0633,0634,0635,0636,0637,0638,0639,0640,0641,0642,0643,0644,0645,0646,0647,0648,0649,0650,0651,0652,0653,0654,0655,0656,0657,0658,0659,0660,0661,0662,0663,0664,0665,0666,0667,0668,0669,0670,0671
---

# ADR `Enforced by:` pointer must assert the decision itself

An ADR's `**Enforced by:**` pointer is only real enforcement if the target test asserts the actual behavioral claim — not merely touches a related symbol. ADR-0017's exclusion rule (`_maybe_decompose()` returning True must skip `increment_session_counter("triaged")`) had drifted to point at a test that referenced the counter but never checked the exclusion.

Example: repointing it at e.g. `test_state_mixin_decomposition.py` would satisfy a naive regex check while staying hollow; the real fix adds a test in `tests/test_triage_phase.py` asserting the counter delta is zero when `routing_outcome == "epic_decomposed"` and exactly one when `routing_outcome == "plan"`.

**Why:** a regex-satisfying but behaviorally-empty enforcement pointer is a silent-green hole — CI stays green even if the exclusion regresses.
