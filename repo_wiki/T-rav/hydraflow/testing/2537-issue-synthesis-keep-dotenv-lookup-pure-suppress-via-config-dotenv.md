---
id: 2537
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:51.145600+00:00
status: active
corroborations: 1
supersedes: 2348
---

# Keep _dotenv_lookup pure; suppress via _config_dotenv_lookup wrapper

`_dotenv_lookup(path, *keys)` must stay a pure, unconditional `.env` reader. Route the three call sites through a new `_config_dotenv_lookup(config, *keys)` that returns `""` when the root was auto-detected *and* pytest is running. Explicit-`repo_root` configs bypass suppression — their `.env` fallback is load-bearing for cassette tests.

**Why:** Inlining conditional logic into `_dotenv_lookup` breaks the contract that real code and cassette tests rely on.
