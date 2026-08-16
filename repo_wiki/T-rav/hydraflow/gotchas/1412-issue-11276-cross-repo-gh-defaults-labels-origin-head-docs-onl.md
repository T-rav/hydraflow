---
id: 1412
topic: gotchas
source_issue: 11276
source_phase: plan
created_at: 2026-08-15T21:04:18.934656+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Cross-repo gh defaults: labels=[], origin/HEAD, docs-only preflight

When opening PRs against external repos via `auto_pr`, set `labels=[]` (targets lack HydraFlow's labels), `auto_merge=False`, and resolve the default branch via `origin/HEAD` rather than assuming `main`. Pass docs-only/minimal preflight since `PREFLIGHT_FULL` runs HydraFlow's toolchain against the target — verify accepted values in `auto_pr`.

**Why:** External repos have different label sets, branch names, and toolchain configurations; hardcoding HydraFlow's defaults causes gh failures or CI mismatches.
