---
id: 1247
topic: gotchas
source_issue: 10622
source_phase: plan
created_at: 2026-07-26T11:28:44.489426+00:00
status: active
corroborations: 1
---

# Waivers self-retire: non-zero signal with a waiver fails the gate

In `violations(repo_root)`, flag both shortfalls AND stale waivers — a declared-empty signal now non-zero yields a "remove the waiver" violation.

- A waivered signal at count 0 → no violation
- Same signal later non-zero → violation naming the signal and saying to remove the waiver
- This prevents waiver rows from accumulating silently

**Why:** Without self-retirement, temporary waivers become permanent exemptions that mask real regressions once the signal recovers.
