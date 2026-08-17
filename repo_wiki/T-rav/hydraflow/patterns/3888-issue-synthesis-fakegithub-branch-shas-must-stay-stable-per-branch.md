---
id: 3888
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T15:30:57.992212+00:00
status: superseded
corroborations: 1
supersedes: 3743
superseded_by: 4035
---

# FakeGitHub branch SHAs must stay stable per branch unless force-pushed

Use deterministic SHAs keyed by branch name, refreshed only on `force=True` pushes. This mirrors the existing `_RC_FIXED_DATE` / `sha-{branch}` convention in `fake_github.py`.

Example: `push_branch("feature-x")` always yields the same SHA; `push_branch("feature-x", force=True)` yields a new one.

**Why:** SHA-dedup paths in `ReviewPhase` (last-reviewed-sha gate) and `StagingPromotionLoop` (red-sha tracking) flip if SHAs change unexpectedly, exhausting scripted LLM results in scenarios.
