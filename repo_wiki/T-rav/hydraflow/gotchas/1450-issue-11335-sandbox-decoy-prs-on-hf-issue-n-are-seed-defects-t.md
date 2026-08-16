---
id: 1450
topic: gotchas
source_issue: 11335
source_phase: plan
created_at: 2026-08-16T10:56:33.810897+00:00
status: active
corroborations: 1
---

# Sandbox decoy PRs on hf/issue-N are seed defects to repair

Rule: if fixing `FakeIssueFetcher` flips a sandbox scenario outcome, treat the flipped outcome as a seed defect — repair the seed, don't soften the fix.

- Scenarios `s04`/`s08` seed decoy PRs on `hf/issue-N` with `issue_number=1` that the Fake previously resolved before the pipeline's `agent/issue-1` PR.
- After the branch-based fix, the pipeline PR wins; any changed assertion means the old seed was masking the bug.

**Why:** the old behavior was the divergence; softening it re-hides the defect the fix was meant to expose.
