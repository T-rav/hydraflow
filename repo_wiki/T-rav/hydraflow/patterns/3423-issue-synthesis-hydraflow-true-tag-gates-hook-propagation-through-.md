---
id: 3423
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T08:05:57.971314+00:00
status: superseded
corroborations: 1
supersedes: 3286
superseded_by: 3570
---

# _hydraflow: true tag gates hook propagation through merge

Every HydraFlow-owned hook object in `.claude/settings.json` must carry `"_hydraflow": true`. `merge_settings_file` (`scripts/merge_assets.py`) filters on this tag; untagged hooks are silently dropped from managed repos.

Example: The 23 hook objects all reference `$CLAUDE_PROJECT_DIR/.claude/hooks/hf.*` — all HydraFlow-owned, all need the tag. The convention is documented in `.claude/hooks/README.md`.

**Why:** Without tags, target repos receive hook scripts on disk but no settings wiring, so hooks never fire — the root cause of issue #11124.
