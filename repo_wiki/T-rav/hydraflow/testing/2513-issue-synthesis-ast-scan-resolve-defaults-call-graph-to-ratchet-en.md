---
id: 2513
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:50.760532+00:00
status: active
corroborations: 1
supersedes: 2324
---

# AST-scan resolve_defaults call graph to ratchet env-key coverage

Architecture tests must scan `resolve_defaults`'s AST to enumerate every function it calls, then assert each env-var literal read is either prefix-covered (`HYDRAFLOW_*`/`HYDRA_*`) or present in `env_override_keys()`.

Example: `tests/architecture/test_config_env_key_coverage.py` derives the scanned function list from the AST, not a hand-maintained list.

**Why:** A new resolution step with an unregistered env literal would otherwise slip past deterministic config construction undetected.
