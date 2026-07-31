---
id: 2030
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T12:50:53.807388+00:00
status: active
corroborations: 1
supersedes: 1903
---

# Pin key-parity between reason-text and reason-remediation maps

When _render_finding selects both title and body from reason-keyed maps (_SURFACE_REASON_TEXT, _SURFACE_REASON_REMEDIATION in src/escape_ledger_loop.py), assert identical key sets in a test. Each SURFACE_REASON_* constant must appear in both maps.

Example: `assert set(_SURFACE_REASON_TEXT) == set(_SURFACE_REASON_REMEDIATION)`.

**Why:** A new reason that ships in only one map renders a finding whose printed remediation cannot close it, causing the issue to re-fire every tick.
