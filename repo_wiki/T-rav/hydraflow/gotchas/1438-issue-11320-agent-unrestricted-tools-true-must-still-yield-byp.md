---
id: 1438
topic: gotchas
source_issue: 11320
source_phase: plan
created_at: 2026-08-16T08:37:33.480373+00:00
status: active
corroborations: 1
---

# agent_unrestricted_tools=True must still yield bypassPermissions

When restricting both diagnostic stages to `acceptEdits` + `--allowedTools` with `WebFetch`/`WebSearch` on `--disallowedTools`, the `agent_unrestricted_tools=True` flag must still flip the spawn to `bypassPermissions`. This is a counter-pin in `tests/regressions/test_issue_11320.py`.

- Thread `restricted=` through `BaseRunner._build_command`; do not hardcode the mode.
- The escape hatch is the only legitimate path to `bypassPermissions`.

**Why:** Locking down both stages without preserving the escape hatch breaks operator override for trusted environments and fails the regression pin.
