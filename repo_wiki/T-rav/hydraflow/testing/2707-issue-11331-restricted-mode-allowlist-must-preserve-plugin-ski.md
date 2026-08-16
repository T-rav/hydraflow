---
id: 2707
topic: testing
source_issue: 11331
source_phase: plan
created_at: 2026-08-16T09:57:29.108966+00:00
status: active
corroborations: 1
---

# Restricted-mode allowlist must preserve plugin/skill resolution chain

`_RESTRICTED_ALLOWED_TOOLS` (`src/agent_cli.py:82`) must admit `Skill` and `Task` for the ultra deep-review tier to function. `/code-review` resolution depends on `--plugin-dir` flags surviving, which requires `isolate_user_settings=False` to remain untouched.

- The allowlist is not validated against a live run (caveat in ADR-0092).
- `agent_unrestricted_tools=True` is the documented revert if a needed tool is missing.

**Why:** Hardening that silently drops a tool breaks `/code-review` in production — unit tests on command shape cannot detect missing runtime tool access.
