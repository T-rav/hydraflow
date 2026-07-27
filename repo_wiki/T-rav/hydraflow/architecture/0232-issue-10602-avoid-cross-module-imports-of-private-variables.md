---
id: 0232
topic: architecture
source_issue: 10602
source_phase: plan
created_at: 2026-07-26T10:26:40.201316+00:00
status: active
corroborations: 1
---

# Avoid cross-module imports of private variables

Do not import `_`-prefixed private variables across modules. When needing to check OpenAI compatibility from `src/provider_canary.py`, use the public `is_openai_compat_provider` in `src/runner_utils.py` rather than importing `_OPENAI_COMPAT_BACKENDS`. **Why:** Enforces encapsulation and prevents breaking changes when internal backend lists are refactored.
