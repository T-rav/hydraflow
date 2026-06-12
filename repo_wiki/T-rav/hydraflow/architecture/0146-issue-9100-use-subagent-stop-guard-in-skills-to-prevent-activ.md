---
id: 0146
topic: architecture
source_issue: 9100
source_phase: review
created_at: 2026-06-12T09:13:44.467863+00:00
status: active
corroborations: 1
---

# Use <SUBAGENT-STOP> guard in skills to prevent activation during headless dispatch

Place a `<SUBAGENT-STOP>` block at the top of any skill that should not run when the agent is dispatched as a subagent executing a specific task.

```
<SUBAGENT-STOP>
If you were dispatched as a subagent to execute a specific task, skip this skill.
</SUBAGENT-STOP>
```

This is the pattern used in `superpowers:using-superpowers` to prevent the skill-selection loop from hijacking contract/JSON agents.

**Why:** Skills loaded via SessionStart apply globally; without the guard, every subagent—including headless ones with strict output schemas—will attempt skill invocation before doing any work.
