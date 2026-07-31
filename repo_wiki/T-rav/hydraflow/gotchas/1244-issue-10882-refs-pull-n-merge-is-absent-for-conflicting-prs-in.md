---
id: 1244
topic: gotchas
source_issue: 10882
source_phase: plan
created_at: 2026-07-31T12:09:08.255828+00:00
status: active
corroborations: 1
---

# refs/pull/N/merge is absent for CONFLICTING PRs in RC gate

GitHub computes no merge commit for an unmergeable PR — `git ls-remote origin 'refs/pull/N/*'` returns only `/head`, never `/merge`. In `.github/workflows/rc-promotion-scenario.yml`, the `gate` job's `resolve` step must probe `gh api repos/$REPO/git/ref/pull/$num/merge` before emitting `pr_ref`. On 404, emit `should_run=false` and `skip_reason=merge-ref-absent`.

- Failing run `30604729350`: Trust Gate, Browser Scenarios, Scenario Tests all died at `actions/checkout@v4` with `fatal: couldn't find remote ref refs/pull/10863/merge`.

**Why:** Downstream jobs die at checkout when handed a merge ref the remote never published.
