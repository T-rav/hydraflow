---
id: 0070
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T04:09:01.908557+00:00
status: active
corroborations: 1
supersedes: 0008,0009,0010,0011,0012,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0037,0038,0039,0040,0041,0042,0043,0044,0045,0046,0047,0048,0049
---

# Set and clear trace context in a single try/finally block

Set/clear or begin/end pairs for tracing context MUST execute within a single try/finally — never split across separate methods.

Example: `token = ctx.set(val); try: ... finally: ctx.reset(token)` — both in one scope.

**Why:** Splitting the set/clear across call boundaries leaks trace state across issues or loop iterations, corrupting span attribution.
