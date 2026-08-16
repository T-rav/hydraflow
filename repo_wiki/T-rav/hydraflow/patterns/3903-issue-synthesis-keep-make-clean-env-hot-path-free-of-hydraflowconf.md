---
id: 3903
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T15:30:58.230695+00:00
status: active
corroborations: 1
supersedes: 3758
---

# Keep make_clean_env hot-path free of HydraFlowConfig

Do not instantiate `HydraFlowConfig` inside `make_clean_env` in `src/subprocess_util.py`. Use cheap `os.environ.get` for opt-in flags like `HYDRAFLOW_ALLOW_AMBIENT_ANTHROPIC_ROUTING`.

Example: `if os.environ.get("HYDRAFLOW_ALLOW_AMBIENT_ANTHROPIC_ROUTING"): ...`

**Why:** `make_clean_env` is on the gh/git hot path; loading config there introduces unacceptable latency to git operations.
