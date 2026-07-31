---
id: 1818
topic: testing
source_issue: 10859
source_phase: plan
created_at: 2026-07-31T02:56:19.656594+00:00
status: active
corroborations: 1
---

# AST-scan resolve_defaults call graph to ratchet env-key coverage

Architecture tests must scan `resolve_defaults`'s AST to enumerate every function it calls, then assert each env-var literal read is either prefix-covered (`HYDRAFLOW_*`/`HYDRA_*`) or present in `env_override_keys()`.

- `tests/architecture/test_config_env_key_coverage.py` derives the scanned function list from the AST, not a hand-maintained list.
- Non-prefixed vars (e.g., `SENTRY_ORG`) stay covered only because the ratchet fails on a new literal.

**Why:** A new resolution step with an unregistered env literal would otherwise slip past deterministic config construction undetected.
