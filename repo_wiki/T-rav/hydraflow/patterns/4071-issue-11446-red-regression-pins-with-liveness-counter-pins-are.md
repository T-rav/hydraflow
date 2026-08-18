---
id: 4071
topic: patterns
source_issue: 11446
source_phase: plan
created_at: 2026-08-18T09:14:02.932574+00:00
status: active
corroborations: 1
---

# RED regression pins with liveness counter-pins are acceptance oracles

Issue regression tests at `tests/regressions/test_issue_NNNNN.py` pair failing RED pins with green liveness counter-pins (e.g. 5 failing + 3 green for issue #11446).

- Do not weaken or delete the failing pins — they are the acceptance oracle.
- The green counter-pins prove the test harness itself runs; if all pins fail, the test is broken, not the code.
- A class-sweep pin (e.g. "0 of 22 offenders") catches future builders reintroducing the anti-pattern.

**Why:** Without counter-pins, an all-red regression file is indistinguishable from a broken test environment, and the fix cannot be trusted.
