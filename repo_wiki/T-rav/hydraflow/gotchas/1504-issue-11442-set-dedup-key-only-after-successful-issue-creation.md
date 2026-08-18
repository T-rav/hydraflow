---
id: 1504
topic: gotchas
source_issue: 11442
source_phase: plan
created_at: 2026-08-18T08:00:27.527787+00:00
status: active
corroborations: 1
---

# Set dedup key only after successful issue creation

In a filing actuator, call `dedup.add(key)` ONLY after `pr_manager.create_issue(...)` returns a positive issue number. On any port failure (create_issue raises, returns None), leave the key unset so the next host tick retries. Swallow and log every port failure — no exception may escape the host tick.

**Why:** Setting the key before the issue exists causes a permanent silent skip — the drift episode is never filed and the dedup store thinks it already was.
