---
id: 0582
topic: patterns
source_issue: 10613
source_phase: plan
created_at: 2026-07-26T10:32:19.699657+00:00
status: superseded
corroborations: 1
superseded_by: 0613
---

# Maintain single dotenv parser and env key allowlist

Route all secret lookups through `EnvSecretsProvider`, collapsing duplicate parsers like `config._parse_dotenv_text` and `subprocess_util._read_dotenv`. Keep `_DOCKER_ENV_PASSTHROUGH_KEYS` in `subprocess_util.py` as the single key allowlist.
**Why:** Duplicating hardcoded key lists or parsers causes drift, leading to missing keys like `CLAUDE_CODE_OAUTH_TOKEN` in agent containers.
