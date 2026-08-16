---
id: 1436
topic: gotchas
source_issue: 11317
source_phase: plan
created_at: 2026-08-16T07:49:38.021634+00:00
status: active
corroborations: 1
---

# Derive env lists from backend registries, not literals

Expose backend env vars via a public `backend_api_key_envs(provider: str | None)` accessor in `src/runner_utils.py`, derived at runtime from `_OPENAI_COMPAT_BACKENDS` and `_HARNESS_BACKENDS`.
**Why:** Hardcoded tuples drift when new OpenAI-compatible or harness lanes are added, causing silent credential leaks or false provider routing failures.
