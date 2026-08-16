---
id: 2701
topic: testing
source_issue: 11329
source_phase: plan
created_at: 2026-08-16T09:40:01.182592+00:00
status: active
corroborations: 1
---

# agent_unrestricted_tools is the hardened-spawn config dial

`agent_unrestricted_tools` (on `self._config`) toggles restricted vs unrestricted agent spawns at every ADR-0092 §2 site; it must be threaded, never hard-coded.

- When `True`: spawn emits `bypassPermissions`, no allowlist.
- When `False`: spawn emits `acceptEdits` + `--allowedTools` allowlist, WebFetch/WebSearch disallowed.
- Test pin: `tests/regressions/test_issue_11329.py` asserts both branches at both sites.

**Why:** Hard-coding `restricted=True` would silently break operators who rely on the config dial for trusted local runs; the regression file is the enforcement layer.
