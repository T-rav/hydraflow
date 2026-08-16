---
id: 0368
topic: architecture
source_issue: 11271
source_phase: plan
created_at: 2026-08-16T05:09:28.497182+00:00
status: active
corroborations: 1
---

# Manifest permissions keyed by settings filename, not flat

When recording installed permission patterns in `.hydraflow/assets.json`, key the `permissions` block by settings filename (`settings.json`, `settings.local.json`). `SETTINGS_FILES` merges two files independently, so the same pattern may be user-authored in one and HF-installed in the other.

Example shape:
- `{"permissions": {"settings.json": {"allow": [...]}, "settings.local.json": {"deny": [...]}}}`

**Why:** Keying by filename ensures `_revoke_permissions` strips a pattern only from the file where HydraFlow installed it, preserving user-authored entries in the sibling file.
