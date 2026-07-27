---
id: 1147
topic: gotchas
source_issue: 10658
source_phase: plan
created_at: 2026-07-26T15:42:45.056055+00:00
status: active
corroborations: 1
---

# Degrade invalid stored overrides with warning, don't drop repo

When a stored override in `data_root/repos.json` fails validation (e.g. `max_workers: 0`), fall back to the default for that field and emit a warning naming the repo slug. Do not skip the repo.

`settings_registry.mutable_field_names()` validates at write time, but repos.json is hand-editable and schema may narrow across releases.

**Why:** Dropping a repo on boot because of one bad field is disproportionate; the operator loses visibility into an otherwise-healthy repo.
