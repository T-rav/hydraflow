---
id: 1184
topic: gotchas
source_issue: 10751
source_phase: plan
created_at: 2026-07-27T23:15:11.981974+00:00
status: active
corroborations: 1
---

# Keep regression_issue_10556.py green as over-correction guard

Do not suppress or normalize `error` in the boot seed. The restored-status branch and `loopsHealthy` honesty depend on last-known-state semantics from #10739.

`tests/regressions/regression_issue_10556.py` is the counter-pin: it must stay green when seeded events are excluded from tallies. If it breaks, the fix over-corrected by hiding restored errors from state views too.

**Why:** Suppressing error makes the console claim health it never observed and guts the restored-status branch.
