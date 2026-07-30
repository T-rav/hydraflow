---
id: 0813
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-28T12:54:49.516459+00:00
status: superseded
corroborations: 1
supersedes: 0757
superseded_by: 0868
---

# Maintain single dotenv parser and env key allowlist

Route all secret lookups through `EnvSecretsProvider`, collapsing duplicate parsers like `config._parse_dotenv_text` and `subprocess_util._read_dotenv`. Keep `_DOCKER_ENV_PASSTHROUGH_KEYS` in `subprocess_util.py` as the single key allowlist.

Example: A single `EnvSecretsProvider` replaces both `config._parse_dotenv_text` and `subprocess_util._read_dotenv`.

**Why:** Duplicating hardcoded key lists or parsers causes drift, leading to missing keys like `CLAUDE_CODE_OAUTH_TOKEN` in agent containers.
