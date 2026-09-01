---
id: 0442
topic: architecture
source_issue: 11947
source_phase: plan
created_at: 2026-09-01T10:45:05.630261+00:00
status: active
corroborations: 1
---

# Factory agents keep project-scope hooks via _CONTRACT_SETTING_SOURCES

`src/agent_cli.py` sets `_CONTRACT_SETTING_SOURCES = "project"`, which drops *user*-level hooks but keeps project scope. `.claude/settings.json` hooks DO reach factory-spawned agents — they are not bypassed by the agent runtime.

- New hooks in `.claude/settings.json` with `"_hydraflow": true` propagate to onboarded repos via `merge_assets.merge_settings_file`.
- Blocking PreToolUse is not a departure: `hf.enforce-migrations.sh` already exits 2 on `Write`/`Edit`.

**Why:** Assuming hooks don't reach factory agents leads to skipping the hook layer and relying on CI alone, missing the early-prevention path.
