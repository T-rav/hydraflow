---
id: 1246
topic: gotchas
source_issue: 10882
source_phase: plan
created_at: 2026-07-31T12:09:08.255882+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Workflow steps probing gh api must not set -e on expected 404s

In `.github/workflows/rc-promotion-scenario.yml`, the `resolve` step's merge-ref probe calls `gh api repos/$REPO/git/ref/pull/$num/merge`, which returns 404 for CONFLICTING PRs. The step must not `set -e` out on this expected failure — handle the exit code explicitly before deciding `should_run` and `skip_reason`.

- Probe 404 → `should_run=false`, `skip_reason=merge-ref-absent`
- Probe 200 → `should_run=true`, `pr_ref=refs/pull/<n>/merge`

**Why:** A `set -e` failure on the expected 404 aborts the step before it can emit `should_run=false`, causing the gate to silently skip without recording a reason.
