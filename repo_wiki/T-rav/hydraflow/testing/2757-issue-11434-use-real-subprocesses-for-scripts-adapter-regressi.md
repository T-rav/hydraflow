---
id: 2757
topic: testing
source_issue: 11434
source_phase: plan
created_at: 2026-08-18T06:57:14.697109+00:00
status: active
corroborations: 1
---

# Use real subprocesses for scripts/ adapter regressions

For `scripts/` process-tree adapters like `quality_host_lock.py`, use real-subprocess regression tests instead of MockWorld or Sandbox e2e.
- `tests/regressions/test_issue_11434.py` uses real fork/exec/ppid semantics.
- Explicitly state MockWorld/Sandbox e2e as N/A in the PR if they don't apply.
**Why:** Defects involving process groups, ppid changes, and signal handling cannot be reproduced or validated accurately with orchestrator mocks.
