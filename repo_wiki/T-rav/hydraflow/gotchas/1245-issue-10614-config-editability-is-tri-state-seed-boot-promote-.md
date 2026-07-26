---
id: 1245
topic: gotchas
source_issue: 10614
source_phase: plan
created_at: 2026-07-26T11:22:50.701999+00:00
status: active
corroborations: 1
---

# Config editability is tri-state: seed boot, promote live with re-read cite

Every entry in `settings_registry.SETTINGS` must declare `editability: "live"|"boot"`. Seed `boot`; promote to `live` only where a per-tick re-read site is cited in code. A test fails when any `_ENV_*` entry lacks a verdict.
- `live`: fields re-read each reload cycle
- `boot`: path/profile/harmonize/docker fields needing `resolve_defaults`

**Why:** A `live` badge without a verified re-read site lies — the UI says editable but the value won't take effect until restart.
