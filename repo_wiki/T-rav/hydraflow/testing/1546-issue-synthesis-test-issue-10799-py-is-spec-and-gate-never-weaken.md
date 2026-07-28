---
id: 1546
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-28T14:38:21.875466+00:00
status: active
corroborations: 1
supersedes: 1464
---

# test_issue_10799.py is spec and gate, never weaken

`tests/regressions/test_issue_10799.py` is pre-written, failing, and authoritative — its fixture combines real backend payloads from the stage map plus an AST scan of every `PHASE_CHANGE` publish site. Make it green; never weaken it.

**Why:** The guard encodes the cross-layer contract between backend `PHASE_CHANGE` emission and UI derivation; weakening it silently breaks an invariant the live stream cannot self-validate.
