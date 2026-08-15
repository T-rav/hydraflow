---
id: 2997
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-15T20:34:48.105780+00:00
status: active
corroborations: 1
supersedes: 2870
---

# Two gh callers in setup_branch_protection.py have divergent 404 handling

When reusing legacy-protection fetch logic inside the CLI, call `gh_fetch_legacy_protection` from `src/branch_protection_audit.py`, not the script-local `_gh` in `scripts/setup_branch_protection.py`.

Example: `gh_fetch_legacy_protection` tolerates expected 404s; `_gh` raises `SystemExit` on 404, crashing the script on a branch with no legacy protection.

**Why:** The two `gh` callers have divergent 404 handling — using `_gh` for a fetch that legitimately 404s crashes instead of returning an empty result.
