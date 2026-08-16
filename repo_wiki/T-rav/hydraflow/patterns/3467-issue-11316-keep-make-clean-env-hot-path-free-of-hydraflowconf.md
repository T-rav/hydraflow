---
id: 3467
topic: patterns
source_issue: 11316
source_phase: plan
created_at: 2026-08-16T07:49:06.673171+00:00
status: active
corroborations: 1
---

# Keep make_clean_env hot-path free of HydraFlowConfig

Do not instantiate `HydraFlowConfig` inside `make_clean_env` in `src/subprocess_util.py`. Use cheap `os.environ.get` for opt-in flags like `HYDRAFLOW_ALLOW_AMBIENT_ANTHROPIC_ROUTING`.

Example: `if os.environ.get("HYDRAFLOW_ALLOW_AMBIENT_ANTHROPIC_ROUTING"): ...`

**Why:** `make_clean_env` is on the gh/git hot path; loading config there introduces unacceptable latency to git operations.
