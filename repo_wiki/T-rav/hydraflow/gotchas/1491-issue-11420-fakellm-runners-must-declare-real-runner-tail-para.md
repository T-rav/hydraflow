---
id: 1491
topic: gotchas
source_issue: 11420
source_phase: plan
created_at: 2026-08-18T03:48:25.160790+00:00
status: active
corroborations: 1
---

# FakeLLM runners must declare real runner tail params explicitly

Declare every positional tail param from the real runner on each `FakeLLM` nested runner — `**_unused` cannot absorb a positional argument.

- `_FakePlannerRunner.plan`: declare `guidance`, `force_scale`
- `_FakeAgentRunner.run`: declare `human_guidance`, `attempt_number`, `known_traps`
- `_FakeReviewRunner.fix_ci`: declare `attempt`, `worker_id`, `ci_logs`, `code_scanning_alerts`

**Why:** A call site passing these positionally against the real runner raises `TypeError` on the fake, breaking MockWorld drop-in parity.
