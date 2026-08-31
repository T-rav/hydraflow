---
id: 2780
topic: testing
source_issue: 11547
source_phase: plan
created_at: 2026-08-30T07:44:19.983856+00:00
status: active
corroborations: 1
---

# Env-key coverage guard sees only inspect.getsource(config)

Widen `tests/architecture/test_config_env_key_coverage.py`'s `_module_function_defs()` whenever env reads move to new modules. The guard parses `inspect.getsource(config)` only, so after extraction to `src/config_env.py` it keeps passing while covering nothing.
- Add a test that injects an unregistered `os.environ.get("SOME_KEY")` into `config_env.py` and asserts the guard fails
- Without this, the ratchet is silently dead
**Why:** A blind guard launders unregistered `HYDRAFLOW_*` env reads into the codebase undetected.
