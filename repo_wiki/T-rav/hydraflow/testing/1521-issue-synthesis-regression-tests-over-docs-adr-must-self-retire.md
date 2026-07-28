---
id: 1521
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-28T14:38:21.821051+00:00
status: active
corroborations: 1
supersedes: 1433
---

# Regression tests over docs/adr must self-retire

Assert "no nudge row cites a non-live ADR" against the real `docs/adr` corpus rather than pinning specific ADR numbers.

Example: `tests/regressions/test_issue_10565.py` models this self-retiring pattern — a future ADR renumbering or supersession doesn't break the pin.

**Why:** Hardcoded ADR numbers in regression tests rot the moment the cited ADR is renumbered or superseded, causing unrelated CI breaks.
