---
id: 1220
topic: gotchas
source_issue: 10862
source_phase: plan
created_at: 2026-07-31T02:48:15.326683+00:00
status: active
corroborations: 1
---

# Guard iterdir TOCTOU in discover_plugin_skills

When scanning directories in `src/plugin_skill_registry.py` (`discover_plugin_skills`), wrap `is_dir()` checks in `try/except FileNotFoundError`. Skip entries that vanish between `iterdir()` and `is_dir()`.

**Why:** Marketplaces or cache subdirectories can be deleted mid-scan; unhandled `FileNotFoundError` will abort discovery of surviving sibling plugins.
