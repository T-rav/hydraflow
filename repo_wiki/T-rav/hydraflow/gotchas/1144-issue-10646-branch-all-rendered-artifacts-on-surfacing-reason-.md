---
id: 1144
topic: gotchas
source_issue: 10646
source_phase: plan
created_at: 2026-07-26T12:21:36.986307+00:00
status: active
corroborations: 1
---

# Branch all rendered artifacts on surfacing reason in escape_ledger_loop

When `_render_finding` in `escape_ledger_loop.py` branches issue title (`_SURFACE_REASON_TEXT`) and close comment (`_resolution_comment`) on surfacing reason, the resolution command block must also branch. Leaving it unbranched strands issues: a `low-confidence` finding renders only `--encoded-as`, but `_surfacing_answered` requires `attribution_confidence != "low"` to close — the command can never satisfy the close condition. Fix: reason-branch every operator-facing artifact in `_render_finding`.

**Why:** Partial branching creates dead-end instructions that look correct but are structurally unable to close the issue.
