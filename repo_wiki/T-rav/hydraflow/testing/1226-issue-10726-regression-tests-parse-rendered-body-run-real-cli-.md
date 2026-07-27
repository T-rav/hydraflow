---
id: 1226
topic: testing
source_issue: 10726
source_phase: plan
created_at: 2026-07-27T18:34:31.163851+00:00
status: active
corroborations: 1
---

# Regression tests parse rendered body, run real CLI, assert closure

`tests/regressions/test_issue_10726.py` extracts the command string from `_render_finding`'s output, executes it against a temp ledger via the real `scripts/resolve_escape.py` CLI, and asserts the surfaced issue closes on the next reconcile pass. **Why:** Unit tests pinning body substrings alone cannot catch the render→execute→close disconnect; only an end-to-end parse-and-run test proves the printed command actually answers the surfacing.
