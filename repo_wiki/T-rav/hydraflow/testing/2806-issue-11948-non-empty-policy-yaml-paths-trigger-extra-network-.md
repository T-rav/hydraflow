---
id: 2806
topic: testing
source_issue: 11948
source_phase: plan
created_at: 2026-09-01T10:57:18.007839+00:00
status: active
corroborations: 1
---

# Non-empty policy.yaml paths trigger extra network reads at merge seams

When `policy.yaml` ships non-empty `paths:`, `has_change_matchers` flips to True, so every autonomous merge now calls `get_pr_diff_names` plus a raw `gh pr view --json labels`. Before landing any path-matched policy entry, verify `tests/regressions/test_sandbox_merge_policy_airgap_9754.py` and offline/sandbox scenarios still pass.

**Why:** Prevents breaking the airgap boundary that pins no-network merge enforcement for sandboxed CI lanes.
