---
id: 2308
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T18:40:36.989524+00:00
status: active
corroborations: 1
supersedes: 2163
---

# Extend SettingSpec with backend-derived UI metadata

Add UI-specific metadata (like `section`) directly to `SettingSpec` in `src/settings_registry.py` rather than maintaining a parallel UI-side allowlist.

Example: `build_settings_schema` emits `'section'` per row derived from a group→section map, with unmapped fields falling back to `'Other'`.

**Why:** Prevents newly registered settings from being silently hidden by stale frontend configurations and guarantees totality.
