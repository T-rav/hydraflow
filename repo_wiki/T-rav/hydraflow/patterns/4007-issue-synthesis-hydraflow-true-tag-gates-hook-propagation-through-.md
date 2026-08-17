---
id: 4007
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T17:41:43.889505+00:00
status: active
corroborations: 1
supersedes: 3860
---

# _hydraflow: true tag gates hook propagation through merge

Every HydraFlow-owned hook object in `.claude/settings.json` must carry `"_hydraflow": true`. `merge_settings_file` (`scripts/merge_assets.py`) filters on this tag; untagged hooks are silently dropped from managed repos.

Example: The 23 hook objects all reference `$CLAUDE_PROJECT_DIR/.claude/hooks/hf.*` — all HydraFlow-owned, all need the tag. The convention is documented in `.claude/hooks/README.md`.

**Why:** Without tags, target repos receive hook scripts on disk but no settings wiring, so hooks never fire — the root cause of issue #11124.
