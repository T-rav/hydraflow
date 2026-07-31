---
id: 1342
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T14:16:20.836304+00:00
status: superseded
corroborations: 1
supersedes: 1268
superseded_by: 1421
---

# Suppress ~/.claude mounts when injecting ANTHROPIC_AUTH_TOKEN

When injecting `ANTHROPIC_AUTH_TOKEN` for a non-default provider, suppress the `~/.claude/` and `~/.claude.json` bind-mounts and include the fallback flag in the user-tool-mount cache key (`src/docker_runner.py:430-446`).

Example: The claude CLI may prefer live OAuth credentials in the mounted config over the env token, silently routing traffic to the exhausted account.

**Why:** Prevents silent credential precedence that makes fallback appear functional while hitting the wrong account.
