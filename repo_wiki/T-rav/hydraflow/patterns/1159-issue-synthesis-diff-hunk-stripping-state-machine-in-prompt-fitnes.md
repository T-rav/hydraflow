---
id: 1159
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T08:27:46.984608+00:00
status: superseded
corroborations: 1
supersedes: 1090
superseded_by: 1227
---

# Diff hunk stripping state machine in prompt_fitness.py

Enter diff mode only on real unified-diff headers (`diff --git `, `index <sha>..`, `--- `, `+++ `, `@@ `) and exit on the first non-diff line. Do not enforce `@@` line counts.

Example: `sampled_audit` renders truncated diffs, so strict line-count validation drops legitimate prompt prose. Prose resuming directly after a hunk with no intervening non-diff line stays in diff mode (known narrowing).

**Why:** Strict line-count validation drops legitimate prompt prose that `sampled_audit` renders as truncated diffs.
