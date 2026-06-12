---
id: 0145
topic: architecture
source_issue: 9100
source_phase: review
created_at: 2026-06-12T09:13:44.467828+00:00
status: active
corroborations: 1
---

# SessionStart hook injects superpowers skill into every session including subagents

The `SessionStart:startup` hook fires before any agent work and injects the full `superpowers:using-superpowers` skill content as `additionalContext`. Headless/contract agents that expect clean JSON output will see this injected prompt and may deviate from their task.

- Mitigation: use `--setting-sources project` to isolate user settings (PR #9394)
- Alternative guard: add `<SUBAGENT-STOP>` block at the top of skills that should not activate in subagent dispatch contexts

**Why:** Without isolation, the injected "invoke a skill first" directive overrides the subagent's system prompt, causing triage/spec agents to emit skill-invocation behavior instead of the expected structured output.
