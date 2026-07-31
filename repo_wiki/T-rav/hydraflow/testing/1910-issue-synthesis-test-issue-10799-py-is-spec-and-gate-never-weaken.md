---
id: 1910
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T06:59:06.412307+00:00
status: superseded
corroborations: 1
supersedes: 1805
superseded_by: 2037
---

# test_issue_10799.py is spec and gate, never weaken

tests/regressions/test_issue_10799.py is pre-written, failing, and authoritative — make it green; never weaken it.

Example: its fixture combines real backend payloads from the stage map plus an AST scan of every PHASE_CHANGE publish site.

**Why:** The guard encodes the cross-layer contract between backend PHASE_CHANGE emission and UI derivation; weakening it silently breaks an invariant the live stream cannot self-validate.
