---
id: 1311
topic: gotchas
source_issue: 11135
source_phase: plan
created_at: 2026-08-14T13:08:51.034608+00:00
status: active
corroborations: 1
---

# Orphan hf.*.sh hooks ship to managed repos via merge_assets glob

Any `hf.*.sh` script in `.claude/hooks/` that `.claude/settings.json` does not invoke is still copied to every onboarded repo by `copy_namespaced_files(source, target, ".claude/hooks", "hf.")` (`scripts/merge_assets.py:299`). 

- The set of `hf.*.sh` on disk must equal the set referenced in `settings.json`.
- A header comment claiming a hook is wired does not make it so — verify by parsing `settings.json`.

**Why:** Dead hooks land in managed repos that lack the HydraFlow-specific paths and make targets they depend on, causing confusing failures or silent no-ops.
