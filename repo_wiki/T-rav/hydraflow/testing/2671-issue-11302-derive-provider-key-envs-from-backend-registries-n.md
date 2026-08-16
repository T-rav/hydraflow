---
id: 2671
topic: testing
source_issue: 11302
source_phase: plan
created_at: 2026-08-16T04:43:31.977997+00:00
status: active
corroborations: 1
---

# Derive provider key envs from backend registries, never hand-list

Export the provider-key surface as a runtime-derived set (`PROVIDER_API_KEY_ENVS` in `src/runner_utils.py`), computed by unioning every `api_key_envs` tuple across `_OPENAI_COMPAT_BACKENDS` and `_HARNESS_BACKENDS`.

Never hand-list provider key env names in conftest or test helpers. A new backend added to either registry must be automatically covered by the scrub.

**Why:** Hand-listed key sets silently drift when new backends are registered, re-opening the hermeticity gap the scrub was meant to close.
