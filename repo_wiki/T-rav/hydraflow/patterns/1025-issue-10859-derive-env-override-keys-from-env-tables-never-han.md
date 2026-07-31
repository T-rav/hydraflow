---
id: 1025
topic: patterns
source_issue: 10859
source_phase: plan
created_at: 2026-07-31T02:56:19.656558+00:00
status: active
corroborations: 1
---

# Derive env override keys from _ENV_* tables, never hand-list

Derive the set of env vars config resolution consults from the existing `_ENV_*` tables and `_DEPRECATED_ENV_ALIASES` at runtime. Never maintain a separate hand-listed mirror.

- `env_override_keys()` in `src/config.py` reads the tables directly.
- Adding a row to any `_ENV_*` table automatically changes the key set with no edit to the function.

**Why:** Hand-copied mirrors drift; a new env var added to a table but not the list silently breaks deterministic config construction for the audit harness.
