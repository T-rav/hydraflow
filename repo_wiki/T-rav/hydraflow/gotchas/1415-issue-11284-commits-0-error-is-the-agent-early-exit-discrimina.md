---
id: 1415
topic: gotchas
source_issue: 11284
source_phase: plan
created_at: 2026-08-16T01:29:44.315646+00:00
status: active
corroborations: 1
---

# commits=0 + error is the agent early-exit discriminator, not a work count

In `AgentRunner.run` (`src/agent.py`), `commits=0` on a failed result is a deliberate signal meaning "loop never verified," not "nothing happened." Normal-path failed attempts (quality-gate failures) carry `commits>0` and keep no-PR retry semantics. Reconcile/salvage logic must only fire on the zero-commit-classified branch, never on quality-gate failures.

**Why:** Firing salvage on quality-gate failures would suppress legitimate from-scratch retries and mask real test failures as "delivered."
