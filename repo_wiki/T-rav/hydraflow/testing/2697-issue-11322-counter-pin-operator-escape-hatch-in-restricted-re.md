---
id: 2697
topic: testing
source_issue: 11322
source_phase: plan
created_at: 2026-08-16T09:00:07.880219+00:00
status: active
corroborations: 1
---

# Counter-pin operator escape hatch in restricted= regression tests

Regression tests for `restricted=` hardening must counter-pin the operator escape hatch: assert that `restricted` is sourced from `self._config.agent_unrestricted_tools`, not a hardcoded `True`.

The test suite in `tests/regressions/test_issue_11322.py` checks per site:
- No blanket bypass flag introduced
- WebFetch/WebSearch remain disallowed
- Operator escape hatch (`agent_unrestricted_tools`) is honored
- Pre-existing flags (`disallowed_tools`, `isolate_user_settings`, `effort`) preserved
- Prompt still carries issue text

**Why:** Without the counter-pin, a future change could hardcode `restricted=True` and pass the guard while silently removing the operator's ability to opt out of restriction.
