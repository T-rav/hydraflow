---
id: 1195
topic: gotchas
source_issue: 10786
source_phase: plan
created_at: 2026-07-28T09:18:05.893402+00:00
status: active
corroborations: 1
---

# Handle aggregate config rejections in operator UI

Mirror `RuntimeSettingsPanel`'s disabled/aggregate-note behavior when `PATCH /api/control/config` rejects `repo=__all__` or per-repo aggregate fields like `gh_circuit_breaker_enabled`. When `repo=__all__` is selected, disable the controls and render a 'select a repo' note rather than allowing opaque save failures.

**Why:** Makes API route constraints (400 Bad Request) visible upfront, preventing user confusion and opaque PATCH failures.
