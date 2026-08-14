---
id: 0320
topic: architecture
source_issue: 11125
source_phase: plan
created_at: 2026-08-14T11:39:37.484108+00:00
status: active
corroborations: 1
---

# impacted_tests.py lacks mapping rules for .claude/** assets

`scripts/impacted_tests.py` has `_hard_full_suite_reason` rules for `.githooks/**` but no rule for `.claude/**`. Only `.claude/hooks/` was patched in #11125; `.claude/settings.json`, `.claude/agents/`, and `.claude/skills/` still select only the architecture+smoke floor.

- A diff touching `.claude/settings.json` runs no hook or agent-related tests.
- These files control agent tool-gating, secret scanning, and pre-commit validation.

**Why:** Changes to agent configuration can break runtime behavior with zero test signal, since impacted-tests selection treats them as no-ops.
