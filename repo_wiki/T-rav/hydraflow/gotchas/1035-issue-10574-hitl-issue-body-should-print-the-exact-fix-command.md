---
id: 1035
topic: gotchas
source_issue: 10574
source_phase: plan
created_at: 2026-07-26T00:21:42.291384+00:00
status: superseded
corroborations: 1
superseded_by: 1039
---

# HITL issue body should print the exact fix command, not just the finding

`_render_finding` in `src/escape_ledger_loop.py` prints the literal `resolve_escape.py` command (with that row's id and the four valid `encoded_as` values) inline in the GitHub issue body it generates. A CLI that exists but isn't referenced from the surface that reports the problem tends to go undiscovered and unused.

**Why:** mitigates the top pre-mortem risk in the #10574 plan — "CLI is written but never discoverable."
