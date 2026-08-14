---
id: 1261
topic: gotchas
source_issue: 11085
source_phase: plan
created_at: 2026-08-14T05:58:31.318382+00:00
status: active
corroborations: 1
---

# Drop redundant self-verification instructions from fix agents

The Stage-2 fix prompt in `src/diagnostic_runner.py` instructed the agent to self-iterate the quality suite, but the runner already verifies via `make quality`. Remove that instruction.

- A fix that skips self-verification must still fail when `make quality` fails.

**Why:** Redundant self-verification instructions add turns without adding safety, directly inflating cache-read cost in bounded sessions.
