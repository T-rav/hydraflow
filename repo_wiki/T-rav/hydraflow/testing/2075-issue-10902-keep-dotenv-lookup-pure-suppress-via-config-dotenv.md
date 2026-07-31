---
id: 2075
topic: testing
source_issue: 10902
source_phase: plan
created_at: 2026-07-31T11:38:13.878524+00:00
status: superseded
corroborations: 1
superseded_by: 2204
---

# Keep _dotenv_lookup pure; suppress via _config_dotenv_lookup wrapper

`_dotenv_lookup(path, *keys)` must stay a pure, unconditional `.env` reader with its existing `(Path, *str)` signature. Route the three call sites (`src/config.py:6136`, `6461`, `6475`) through a new `_config_dotenv_lookup(config, *keys)` that returns `""` when the root was auto-detected *and* pytest is running.

- Explicit-`repo_root` configs bypass suppression — their `.env` fallback is load-bearing for cassette tests.
- Production resolution order is identical: suppression fires only under pytest + auto-detection.

**Why:** Inlining conditional logic into `_dotenv_lookup` breaks the contract that real code and cassette tests rely on.
