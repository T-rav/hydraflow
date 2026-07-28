---
id: 1543
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-28T14:38:21.869586+00:00
status: active
corroborations: 1
supersedes: 1457
---

# Extend SettingSpec with backend-derived UI metadata

Add UI-specific metadata (like `section`) directly to `SettingSpec` in `src/settings_registry.py` rather than maintaining a parallel UI-side allowlist. `build_settings_schema` emits `"section"` per row derived from a group→section map, with unmapped fields falling back to `Other`.

**Why:** Prevents newly registered settings from being silently hidden by stale frontend configurations and guarantees totality.
