---
id: 0280
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T02:42:57.715627+00:00
status: superseded
corroborations: 1
supersedes: 0218,0219,0220,0221,0222,0223,0224,0225,0226,0227,0228,0229,0230,0231,0232,0233,0234,0235,0236,0237,0238,0239,0240,0241,0242,0243,0244,0245,0246,0247,0248,0249,0250,0251,0252,0253,0254,0255,0256,0257,0258,0259
superseded_by: 0302
---

# Set and clear trace context in a single try/finally block

Set/clear or begin/end pairs for tracing context MUST execute within a single try/finally — never split across separate methods.

Example: `token = ctx.set(val); try: ... finally: ctx.reset(token)` — both in one scope.

**Why:** Splitting the set/clear across call boundaries leaks trace state across issues or loop iterations, corrupting span attribution.
