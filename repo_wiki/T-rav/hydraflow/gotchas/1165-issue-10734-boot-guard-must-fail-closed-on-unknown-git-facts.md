---
id: 1165
topic: gotchas
source_issue: 10734
source_phase: plan
created_at: 2026-07-27T19:38:38.658555+00:00
status: active
corroborations: 1
---

# Boot guard must fail-closed on unknown git facts

Rule: `decide_boot_action` in `scripts/liveness/boot_guard.py` returns START only when workspace branch == factory branch AND `boot_sha` == `origin/<branch>` tip AND `commits_behind == 0`. Any unknown fact (unreadable git, missing origin tip) yields NO_ACTION — never START. Only a *definite* mismatch yields RESYNC_REBOOT.

**Why:** Unreadable git on a broken workspace would cause a reboot loop every 5 minutes if unknowns triggered action; fail-closed breaks the loop.
