---
id: 1464
topic: testing
source_issue: 10799
source_phase: plan
created_at: 2026-07-28T10:31:44.654967+00:00
status: superseded
corroborations: 1
superseded_by: 1546
---

# tests/regressions/test_issue_10799.py is spec and gate, never weaken

Rule: `tests/regressions/test_issue_10799.py` is pre-written, failing, and authoritative — its fixture combines real backend payloads from the stage map plus an AST scan of every `PHASE_CHANGE` publish site. Make it green; never weaken it. **Why:** The guard encodes the cross-layer contract between backend `PHASE_CHANGE` emission and UI derivation; weakening it silently breaks an invariant the live stream cannot self-validate.
