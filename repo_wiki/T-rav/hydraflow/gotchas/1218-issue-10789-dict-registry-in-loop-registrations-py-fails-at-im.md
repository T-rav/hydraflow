---
id: 1218
topic: gotchas
source_issue: 10789
source_phase: plan
created_at: 2026-07-31T02:16:58.506546+00:00
status: active
corroborations: 1
---

# Dict-registry in loop_registrations.py fails at import, not assertion

When removing a loop builder from `tests/scenarios/catalog/loop_registrations.py`, delete both the builder function and its dict registry entry together.

- Removing `_build_adr_drift_resolver` without its `:2269` entry raises at import time, not at test assertion — masking the real failure behind an import error.
- The registry is a plain dict, so missing keys surface immediately on module load.

**Why:** Import-time failures obscure the actual test result and can mislead debugging; deleting function and entry atomically keeps the failure mode at the assertion level where it's diagnosable.
