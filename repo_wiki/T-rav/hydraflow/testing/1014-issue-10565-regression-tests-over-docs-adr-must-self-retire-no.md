---
id: 1014
topic: testing
source_issue: 10565
source_phase: plan
created_at: 2026-07-25T23:03:04.264305+00:00
status: active
corroborations: 1
---

# Regression tests over docs/adr must self-retire, not hardcode ADR numbers

`tests/regressions/test_issue_10565.py` asserts "no nudge row cites a non-live ADR" against the real `docs/adr` corpus rather than pinning specific numbers like ADR-0013 — so a future ADR renumbering or supersession doesn't break the pin. Model new drift/citation regression tests on this self-retiring pattern instead of asserting against a fixed ADR id.

**Why:** hardcoded ADR numbers in regression tests rot the moment the cited ADR is renumbered or superseded, causing unrelated CI breaks.
