---
id: 1446
topic: gotchas
source_issue: 11331
source_phase: plan
created_at: 2026-08-16T09:57:29.108919+00:00
status: active
corroborations: 1
---

# restricted= dial hardens agent spawns across ADR-0092 boundary

Thread `restricted=not config.agent_unrestricted_tools` into every agent spawn that builds commands from issue/diff-derived prompts. This mirrors `src/base_runner.py:572` and `src/preflight/auto_agent_runner.py:66`.

- In restricted mode: command gets `--permission-mode acceptEdits` + `--allowedTools` allowlist instead of `bypassPermissions`.
- In unrestricted mode (`agent_unrestricted_tools=True`): reverts to `bypassPermissions`.

**Why:** Spawns that carry untrusted text cannot use ADR-0092's "trusted, non-issue spawns" carve-out unless they override `_build_command`; the dial provides a uniform hardening surface without exempting individual sites.
