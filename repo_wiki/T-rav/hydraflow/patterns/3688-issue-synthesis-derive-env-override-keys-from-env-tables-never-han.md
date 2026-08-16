---
id: 3688
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T13:50:49.340452+00:00
status: active
corroborations: 1
supersedes: 3543
---

# Derive env override keys from _ENV_* tables, never hand-list

Derive the set of env vars config resolution consults from the existing `_ENV_*` tables and `_DEPRECATED_ENV_ALIASES` at runtime. Never maintain a separate hand-listed mirror.

Example: `env_override_keys()` in `src/config.py` reads the tables directly. Adding a row to any `_ENV_*` table automatically changes the key set with no edit to the function.

**Why:** Hand-copied mirrors drift; a new env var added to a table but not the list silently breaks deterministic config construction for the audit harness.
