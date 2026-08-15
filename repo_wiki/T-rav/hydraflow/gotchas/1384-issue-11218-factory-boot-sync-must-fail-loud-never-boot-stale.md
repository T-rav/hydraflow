---
id: 1384
topic: gotchas
source_issue: 11218
source_phase: plan
created_at: 2026-08-15T06:29:26.164574+00:00
status: active
corroborations: 1
---

# Factory boot sync must fail loud, never boot stale

Per ADR-0041, the factory workspace is a disposable clone — upstream is the record, discard is the salvage rule. `scripts/run-factory-isolated.sh` must fail closed: if fetch fails or the workspace is unhealable after sync, exit non-zero with a loud `ERROR` before `make run`.

- Every boot logs a divergence report (ahead/behind, dirty/untracked paths, stash ages) before destroying anything — even when there is nothing to discard, log an explicit "no divergence" line.
- Post-sync verification asserts HEAD == `origin/$BRANCH`, clean tree, no stale stash.

**Why:** A silent stale boot masks upstream divergence and runs the factory against outdated code with no signal.
