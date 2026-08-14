---
id: 2348
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T18:40:37.097764+00:00
status: superseded
corroborations: 1
supersedes: 2204
superseded_by: 2537
---

# Keep _dotenv_lookup pure; suppress via _config_dotenv_lookup wrapper

`_dotenv_lookup(path, *keys)` must stay a pure, unconditional `.env` reader. Route the three call sites through a new `_config_dotenv_lookup(config, *keys)` that returns `""` when the root was auto-detected *and* pytest is running. Explicit-`repo_root` configs bypass suppression — their `.env` fallback is load-bearing for cassette tests.

**Why:** Inlining conditional logic into `_dotenv_lookup` breaks the contract that real code and cassette tests rely on.
