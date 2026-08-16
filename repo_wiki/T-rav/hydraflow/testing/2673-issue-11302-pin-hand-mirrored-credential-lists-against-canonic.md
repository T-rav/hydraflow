---
id: 2673
topic: testing
source_issue: 11302
source_phase: plan
created_at: 2026-08-16T04:43:31.978023+00:00
status: active
corroborations: 1
---

# Pin hand-mirrored credential lists against canonical registry

When a module hand-mirrors a credential env list that a registry already owns canonically (e.g., `credit_failover._ZAI_API_KEY_ENVS` mirrors the zai harness tuple by comment), add a drift pin asserting the subset relationship against `PROVIDER_API_KEY_ENVS`.

Import the private symbol test-side (`_`-import), matching the convention in `tests/test_llm_provider.py` for `_OPENAI_COMPAT_BACKENDS`. Do not import it from `src/`.

**Why:** Hand-mirrored copies silently drift from the canonical registry when new keys are added, causing the mirror to miss keys that `zai_key_present()` should detect.
