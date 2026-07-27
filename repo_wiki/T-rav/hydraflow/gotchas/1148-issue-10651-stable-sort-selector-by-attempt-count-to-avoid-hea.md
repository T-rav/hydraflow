---
id: 1148
topic: gotchas
source_issue: 10651
source_phase: plan
created_at: 2026-07-26T15:47:34.663688+00:00
status: active
corroborations: 1
---

# Stable-sort selector by attempt count to avoid head-of-line blocking

When `select_findings_to_surface` builds its `eligible` list, stable-sort by prior failed attempts ascending before applying `escape_ledger_max_issues_per_tick`. Exclude abandoned fingerprint/reason pairs entirely.

- Before: ledger append order meant a permanently-unfileable pair consumed a filing slot every tick.
- After: never-tried findings sort ahead of repeatedly-failed ones.

**Why:** Head-of-line blocking from stuck pairs starves fresh findings of per-tick filing budget indefinitely.
