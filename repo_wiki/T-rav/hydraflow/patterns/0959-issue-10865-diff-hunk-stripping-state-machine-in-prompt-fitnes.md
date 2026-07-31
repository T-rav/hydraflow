---
id: 0959
topic: patterns
source_issue: 10865
source_phase: plan
created_at: 2026-07-31T02:25:44.330099+00:00
status: superseded
corroborations: 1
superseded_by: 1023
---

# Diff hunk stripping state machine in prompt_fitness.py

Enter diff mode only on real unified-diff headers (`diff --git `, `index <sha>..`, `--- `, `+++ `, `@@ `) and exit on the first non-diff line. Do not enforce `@@` line counts.
**Why:** `sampled_audit` renders truncated diffs, so strict line-count validation drops legitimate prompt prose. Prose resuming directly after a hunk with no intervening non-diff line stays in diff mode (known narrowing).
