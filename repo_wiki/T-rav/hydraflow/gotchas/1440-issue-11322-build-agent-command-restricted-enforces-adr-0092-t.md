---
id: 1440
topic: gotchas
source_issue: 11322
source_phase: plan
created_at: 2026-08-16T09:00:07.880165+00:00
status: active
corroborations: 1
---

# build_agent_command restricted= enforces ADR-0092 trust boundary

Every `build_agent_command(...)` spawn whose prompt carries issue-derived text (title, body, comments, CI logs, agent transcript) must pass `restricted=not self._config.agent_unrestricted_tools` — never hardcode `restricted=True`.

Examples of call sites requiring hardening:
- `src/bug_reproducer.py` `_build_command` (~L188)
- `src/research_runner.py` `_build_command` (~L104)
- `src/discover_runner.py` `_build_command` (~L511)
- `src/shape_runner.py` `_build_command` (~L339)

Mirror the pattern from `src/base_runner.py:572` and `src/preflight/auto_agent_runner.py:66`, keeping existing `disallowed_tools=` lists intact.

**Why:** Omitting `restricted=` lets untrusted issue text influence tool selection, breaching the ADR-0092 §2 trust boundary; hardcoding `True` removes the operator escape hatch.
