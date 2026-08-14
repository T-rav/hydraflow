---
id: 1313
topic: gotchas
source_issue: 11137
source_phase: plan
created_at: 2026-08-14T13:57:19.247648+00:00
status: active
corroborations: 1
---

# Filter terminal rows before budget cap, not after diagnosis

Apply the `escape_ledger_max_issues_per_tick` cap in `select_findings_to_surface` only after excluding terminally-diagnosed rows. Do not move the cap to run after `_auto_diagnose` — diagnosis does git/GitHub reads and must stay bounded.
- `select_findings_to_surface` (`src/escape_ledger_loop.py:181`) receives `terminally_diagnosed` ids and skips them pre-cap.
- `capped` no longer reports budget exhaustion caused by unreachable rows.
**Why:** Terminally-diagnosed rows (e.g. `dismissed` verdicts) that don't mutate the ledger stay eligible forever and refill the cap every tick, starving human-reachable findings.
