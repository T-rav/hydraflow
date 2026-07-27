---
id: 1300
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-27T20:11:03.521197+00:00
status: active
corroborations: 1
supersedes: 1226
---

# Regression tests parse rendered body, run real CLI, assert closure

Regression tests for escape resolution must parse the rendered command from `_render_finding`'s output, execute it via the real `scripts/resolve_escape.py` CLI against a temp ledger, and assert the surfaced issue closes on the next reconcile pass.

Example: `tests/regressions/test_issue_10726.py` extracts the command string from rendered output, runs it, and asserts closure.

**Why:** Unit tests pinning body substrings alone cannot catch the render→execute→close disconnect; only an end-to-end parse-and-run test proves the printed command actually answers the surfacing.
