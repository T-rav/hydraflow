---
id: 2888
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-15T11:44:52.264500+00:00
status: superseded
corroborations: 1
supersedes: 2759
superseded_by: 3015
---

# Terminal sidecar verdicts must short-circuit EscapeAutoDiagnoser

`EscapeAutoDiagnoser.diagnose` (`src/escape/auto_diagnose.py`) must return the recorded terminal verdict without reading git or PRPort when a sidecar row already exists with `RESOLVED_ENCODED` or `DISMISSED`.

Example: `terminal_verdicts()` returns last-row-wins verdicts; `diagnose` checks it before any git/PRPort read. Without short-circuit, a DISMISSED row downgrades to INCONCLUSIVE on the next tick.

**Why:** Without the guard, a machine-DISMISSED escape buys exactly one quiet tick before the caller re-files it for a human.
