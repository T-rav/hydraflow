---
id: 0028
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:09:18.316844+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007
---

# Set and clear trace context in a single try/finally block

Set/clear or begin/end pairs for tracing context MUST execute within a single try/finally — never split across separate methods.

Example: `token = ctx.set(val); try: ... finally: ctx.reset(token)` — both in one scope.

**Why:** Splitting the set/clear across call boundaries leaks trace state across issues or loop iterations, corrupting span attribution.
