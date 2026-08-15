---
id: 1395
topic: gotchas
source_issue: 11238
source_phase: plan
created_at: 2026-08-15T09:37:15.548521+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Use getattr for HydraFlowConfig fields pending in later PRs

Read not-yet-landed config fields via `getattr(self._config, "repo_provider", "")` rather than direct attribute access.

Example: `repo_provider` is absent from `HydraFlowConfig` until #11211 merges; `getattr` returns `""` which falls through to the claude-native default in classification.

**Why:** Direct reads raise `AttributeError` when a PR ships before its config-field dependency lands.
