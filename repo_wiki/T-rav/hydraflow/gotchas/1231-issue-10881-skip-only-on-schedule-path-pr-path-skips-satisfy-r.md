---
id: 1231
topic: gotchas
source_issue: 10881
source_phase: plan
created_at: 2026-07-31T07:22:08.358107+00:00
status: active
corroborations: 1
---

# Skip only on schedule path; PR-path skips satisfy required checks

Rule: In `rc-promotion-scenario.yml`, gating with `should_run=false` is safe only on the `schedule`/`workflow_dispatch` branch — those check runs attach to `staging`, not the RC PR's head SHA. On the `pull_request` branch a skipped job is treated as passing by branch protection; an untested RC promotes.

Example:
- Schedule path: probe `refs/pull/N/merge`; absent → `should_run=false` (safe).
- PR path: emit empty `pr_ref` so `actions/checkout` uses the event's resolved merge SHA.
- Precedent: `Sandbox (rc/* promotion PR full suite)` at `ci.yml:725`.

**Why:** Collapsing the two branches silently greens a required e2e gate against a bug that isn't in the suite. The README's "SKIPPED = not passed" warning covers path-filtered `staging` skips, a different mechanism.
