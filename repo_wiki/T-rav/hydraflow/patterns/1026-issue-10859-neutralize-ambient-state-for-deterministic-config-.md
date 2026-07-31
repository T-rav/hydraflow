---
id: 1026
topic: patterns
source_issue: 10859
source_phase: plan
created_at: 2026-07-31T02:56:19.656585+00:00
status: active
corroborations: 1
---

# Neutralize ambient state for deterministic config: scrub env + temp repo_root

When building a declared-default config, pop all `HYDRAFLOW_`/`HYDRA_`-prefixed and `GIT_*` keys from `os.environ` and restore them byte-identically in a `finally` block — including when construction raises. Set `repo_root` to an empty temp dir.

- `declared_default_config()` in `src/config.py` suppresses `_dotenv_lookup` (no `.env` found) and git-remote detection (no identity).
- `os.environ` is byte-identical after the call on both success and exception paths.

**Why:** A developer's `.env` or git config leaking into audit baselines breaks ADR-0087's "same input → same score."
