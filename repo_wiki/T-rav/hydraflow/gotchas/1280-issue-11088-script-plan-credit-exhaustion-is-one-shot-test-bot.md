---
id: 1280
topic: gotchas
source_issue: 11088
source_phase: plan
created_at: 2026-08-14T08:31:19.200145+00:00
status: active
corroborations: 1
---

# script_plan_credit_exhaustion is one-shot; test both raise and resume

`FakeLLM.script_plan_credit_exhaustion` arms a one-shot condition: the first `planners.plan` raises `CreditExhaustedError`, the second returns a normal plan result.

- Assert public attributes on the exception: `resume_at`, `authoritative=True`.
- Assert a second `plan` call on the same issue succeeds.
- `message`/`resume_at`/`authoritative` are keyword-only — call accordingly.

**Why:** Asserting on private FakeLLM/planner-runner state would couple to implementation; the one-shot contract is the load-bearing behavior that must not silently break.
