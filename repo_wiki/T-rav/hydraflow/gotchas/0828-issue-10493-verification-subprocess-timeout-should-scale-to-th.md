---
id: 0828
topic: gotchas
source_issue: 10493
source_phase: plan
created_at: 2026-07-24T23:45:36.554303+00:00
status: active
corroborations: 1
---

# Verification subprocess timeout should scale to the make-tier, not a fixed 120s

A hardcoded 120s subprocess timeout in agent bash calls is too short for scenario/browser verification and causes false-positive reaps. Add `agent_bash_timeout_secs` to `src/config.py` (make-tier default) and inject it as env into `stream_claude_process` in `src/runner_utils.py`, with explicit config overrides winning. Old state files must still load unchanged after this config addition.

**Why:** a fixed short timeout kills legitimate long-running verification mid-run, which is what caused issue #10493's stranded-PR bug in the first place.
