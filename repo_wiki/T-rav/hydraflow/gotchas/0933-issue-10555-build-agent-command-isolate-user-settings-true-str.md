---
id: 0933
topic: gotchas
source_issue: 10555
source_phase: plan
created_at: 2026-07-25T22:52:11.067249+00:00
status: superseded
corroborations: 1
superseded_by: 0940
---

# `build_agent_command(isolate_user_settings=True)` strips `--plugin-dir` flags

Passing `isolate_user_settings=True` to `agent_cli.build_agent_command` (agent_cli.py:138) drops the `--plugin-dir` flags, so any spawned agent command referencing a plugin slash command (e.g. `/code-review`) fails to resolve. Any runner that needs a plugin-provided command must call it with `isolate_user_settings=False`.

**Why:** the failure is silent — the spawn succeeds but the plugin command isn't found, so the tier looks "enabled but useless" instead of erroring.
