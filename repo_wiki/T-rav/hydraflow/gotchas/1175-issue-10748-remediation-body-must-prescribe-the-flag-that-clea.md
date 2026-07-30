---
id: 1175
topic: gotchas
source_issue: 10748
source_phase: plan
created_at: 2026-07-27T22:35:59.585758+00:00
status: active
corroborations: 1
---

# Remediation body must prescribe the flag that clears its surfacing reason

A finding's remediation body must name the CLI flag that `_surfacing_answered` checks for that reason — not just any resolution flag.

- `low-confidence` findings are cleared by `attribution_confidence != "low"`, so the body must offer `--confidence`.
- `aging` findings are cleared by the aging-outcome path, so `--encoded-as` suffices there.
- A low-confidence body that only emits `--encoded-as` cannot close its own issue.

**Why:** `_render_finding` and `_resolution_comment` were already reason-scoped in `src/escape_ledger_loop.py`, but the body was not — so prescribed commands were inert for the reason they addressed.
