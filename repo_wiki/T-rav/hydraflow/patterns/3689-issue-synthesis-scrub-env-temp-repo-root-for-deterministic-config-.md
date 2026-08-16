---
id: 3689
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T13:50:49.356830+00:00
status: active
corroborations: 1
supersedes: 3544
---

# Scrub env + temp repo_root for deterministic config baselines

When building a declared-default config, pop all `HYDRAFLOW_`/`HYDRA_`-prefixed and `GIT_*` keys from `os.environ` and restore them byte-identically in a `finally` block — including when construction raises. Set `repo_root` to an empty temp dir.

Example: `declared_default_config()` in `src/config.py` suppresses `_dotenv_lookup` (no `.env` found) and git-remote detection (no identity).

**Why:** A developer's `.env` or git config leaking into audit baselines breaks ADR-0087's "same input → same score."
