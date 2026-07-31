---
id: 1625
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T01:04:04.454691+00:00
status: superseded
corroborations: 1
supersedes: 1543
superseded_by: 1708
---

# Extend SettingSpec with backend-derived UI metadata

Add UI-specific metadata (like section) directly to SettingSpec in src/settings_registry.py rather than maintaining a parallel UI-side allowlist. build_settings_schema emits 'section' per row derived from a group→section map, with unmapped fields falling back to 'Other'.

**Why:** Prevents newly registered settings from being silently hidden by stale frontend configurations and guarantees totality.
