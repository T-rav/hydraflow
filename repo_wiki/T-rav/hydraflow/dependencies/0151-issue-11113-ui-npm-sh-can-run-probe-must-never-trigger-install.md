---
id: 0151
topic: dependencies
source_issue: 11113
source_phase: plan
created_at: 2026-08-14T09:30:40.586174+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# ui-npm.sh --can-run probe must never trigger installation

The `--can-run` probe walks the same manager chain as normal execution but gates every `run_with_*` provisioning step behind an internal no-install flag. On a node-less machine it exits non-zero silently; `make quality` then prints `[ui-tests SKIPPED]` and exits 0.

**Why:** Reusing the `--version` path without a no-install flag turns `make quality` on a node-less machine into `brew install node@22`, breaking the green-degradation guarantee from #9875.
