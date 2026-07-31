---
id: 1235
topic: patterns
source_issue: 10894
source_phase: plan
created_at: 2026-07-31T11:12:50.925691+00:00
status: superseded
corroborations: 1
superseded_by: 1305
---

# Two gh callers in setup_branch_protection.py have divergent 404 handling

`gh_fetch_legacy_protection` (from `src/branch_protection_audit.py`) uses a `gh` helper that tolerates expected 404s. The script-local `_gh` in `scripts/setup_branch_protection.py` raises `SystemExit` on 404.

When reusing legacy-protection fetch logic inside the CLI, call `gh_fetch_legacy_protection`, not `_gh`.

**Why:** Using `_gh` for a fetch that legitimately 404s (no legacy protection on a branch) crashes the script instead of returning an empty result.
