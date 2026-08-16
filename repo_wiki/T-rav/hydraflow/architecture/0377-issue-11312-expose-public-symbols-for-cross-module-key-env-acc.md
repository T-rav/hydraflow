---
id: 0377
topic: architecture
source_issue: 11312
source_phase: plan
created_at: 2026-08-16T07:21:09.104053+00:00
status: active
corroborations: 1
---

# Expose public symbols for cross-module key env access

When another module needs a key-env list owned by `src/credit_failover.py`, add a public accessor like `zai_key_envs() -> tuple[str, ...]` rather than importing `_ZAI_API_KEY_ENVS` across module boundaries.

- Both new surface symbols (`PROVIDER_API_KEY_ENVS` in `runner_utils`, `zai_key_envs()` in `credit_failover`) are public — no `_` prefix.
- Tuple membership stays unchanged; only the access path changes.

**Why:** Cross-module `_`-prefixed imports create hidden coupling; a rename or restructure of the private tuple silently breaks dependent modules.
