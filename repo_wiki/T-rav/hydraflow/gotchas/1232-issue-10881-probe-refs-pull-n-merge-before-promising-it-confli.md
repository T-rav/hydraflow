---
id: 1232
topic: gotchas
source_issue: 10881
source_phase: plan
created_at: 2026-07-31T07:22:08.358141+00:00
status: active
corroborations: 1
---

# Probe refs/pull/N/merge before promising it; conflict suppresses the ref

Rule: Before emitting `pr_ref: refs/pull/N/merge` from any workflow `resolve` step, probe with `git ls-remote origin refs/pull/N/merge`. GitHub does not publish the merge ref for PRs with merge conflicts; `actions/checkout` then fails with `fatal: couldn't find remote ref` in 40–50s against a 45-min budget.

Example:
- Conflicting PR: only `refs/pull/N/head` exists → `should_run=false` (schedule) or empty `pr_ref` (PR event).
- On `pull_request` events, prefer empty `pr_ref` so checkout falls back to the event's already-resolved merge SHA, which always exists for a dispatched run.

**Why:** Treating the merge ref as always-present kills three required `main` checks every 30 min and trips `GateHealthLoop` into a false "NEVER passed".
