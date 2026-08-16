---
id: 1425
topic: gotchas
source_issue: 11271
source_phase: plan
created_at: 2026-08-16T05:09:28.497218+00:00
status: active
corroborations: 1
---

# load_manifest tolerates absent permissions key (ADR-0021)

`load_manifest` in `scripts/merge_assets.py` must return an empty permissions record when the `permissions` key is absent — never raise `KeyError`. Legacy manifests written before this feature therefore revoke nothing on clean.

**Why:** ADR-0021 schema evolution requires forward-compatible reads; a missing key must degrade to "no permissions recorded" rather than crashing `clean_assets`.
