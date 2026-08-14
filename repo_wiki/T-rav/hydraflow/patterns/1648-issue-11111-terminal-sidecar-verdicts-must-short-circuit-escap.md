---
id: 1648
topic: patterns
source_issue: 11111
source_phase: plan
created_at: 2026-08-14T09:08:28.015626+00:00
status: superseded
corroborations: 1
superseded_by: 1739
---

# Terminal sidecar verdicts must short-circuit EscapeAutoDiagnoser

`EscapeAutoDiagnoser.diagnose` (`src/escape/auto_diagnose.py`) must return the recorded terminal verdict without reading git or PRPort when a sidecar row already exists with `RESOLVED_ENCODED` or `DISMISSED`.

- `terminal_verdicts()` returns last-row-wins verdicts; `diagnose` checks it before any git/PRPort read
- Without short-circuit, a DISMISSED row downgrades to INCONCLUSIVE on the next tick

**Why:** Without the guard, a machine-DISMISSED escape buys exactly one quiet tick before the caller re-files it for a human.
