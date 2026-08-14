---
id: 1279
topic: gotchas
source_issue: 11110
source_phase: plan
created_at: 2026-08-14T08:05:02.917601+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Wire git-history checks into fetch-depth:0 CI jobs only

A check that calls `git log` needs full history. In `.github/workflows/ci.yml`, the Architecture Check (`arch`) job is the only job with `fetch-depth: 0` and is already a `needs` of the required CI Gate. Wire git-history-dependent targets (like `make console-conformance`) into this job, not the `test` job, which clones shallow.

This avoids `gates.toml` record creation, ruleset regen, or ADDING-A-GATE ordering constraints.

**Why:** A shallow clone has no merge-base to resolve, so the check either silently degrades to the fallback or fails with an opaque git error.
