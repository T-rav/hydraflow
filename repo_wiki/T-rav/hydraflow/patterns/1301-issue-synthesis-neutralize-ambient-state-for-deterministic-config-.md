---
id: 1301
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T12:41:40.115208+00:00
status: superseded
corroborations: 1
supersedes: 1230
superseded_by: 1375
---

# Neutralize ambient state for deterministic config: scrub env + temp repo_root

When building a declared-default config, pop all `HYDRAFLOW_`/`HYDRA_`-prefixed and `GIT_*` keys from `os.environ` and restore them byte-identically in a `finally` block — including when construction raises. Set `repo_root` to an empty temp dir.

Example: `declared_default_config()` in `src/config.py` suppresses `_dotenv_lookup` (no `.env` found) and git-remote detection (no identity). `os.environ` is byte-identical after the call on both success and exception paths.

**Why:** A developer's `.env` or git config leaking into audit baselines breaks ADR-0087's "same input → same score."
